"""Refactor strategy — complexity-driven refactoring loop.

Runs: check complexity → identify worst offenders → refactor → re-check → loop
"""

from __future__ import annotations

import os
import re
import subprocess
import time

from loopforge.llm.types import LLMMessage
from loopforge.models import (
    ActionStep,
    Constraints,
    Decision,
    LoopState,
    RoundResult,
)
from loopforge.strategy.base import (
    ActionPlan,
    ActionResult,
    BaseStrategy,
    EvaluateResult,
)

REFACTOR_PLAN_PROMPT = """\
You are a code refactoring expert. Given complexity metrics and source code, find the most complex or messy function and propose a clean refactoring.

Rules:
1. Target ONE function per round — the one with highest complexity
2. Reduce cognitive load: split large functions, eliminate deep nesting, remove duplication
3. Keep all existing behavior — tests must still pass
4. Prefer clear, obvious transformations over clever rewrites

Output format exactly:
GOAL: <one sentence describing the refactoring>
FILE: <path to edit>
SEARCH: <<<
<exact lines to find in the file>
>>>
REPLACE: <<<
<replacement lines>
>>>
"""


class RefactorStrategy(BaseStrategy):
    name = "refactor"
    description = "Complexity-driven refactoring — reduce complexity, keep tests green"

    def __init__(self, llm, **kwargs):
        super().__init__(llm=llm, **kwargs)
        self._baseline_complexity: int | None = None

    # ── Plan ────────────────────────────────────────────────────────

    async def plan(self, state: LoopState) -> ActionPlan:
        target = state.config.target
        eval_cmd = state.config.constraints.evaluation

        output = self._run_cmd(eval_cmd, cwd=self._target_dir(target))
        complexity = self._parse_complexity(output)

        if self._baseline_complexity is None:
            self._baseline_complexity = complexity

        files = self._read_target_files(target)

        status = f"Complexity score: {complexity}"
        if self._baseline_complexity:
            delta = complexity - self._baseline_complexity
            status += f" (baseline: {self._baseline_complexity}, delta: {delta:+d})"

        ctx = f"""Evaluation command: `{eval_cmd}`

--- OUTPUT ---
{output[:6000]}

{status}

--- SOURCE FILES ---
{files[:8000]}

Previous rounds: {len(state.rounds)}
Best score: {state.best_score}
"""

        resp = await self.llm.chat(
            messages=[LLMMessage(role="user", content=ctx)],
            system=REFACTOR_PLAN_PROMPT,
            max_tokens=2048,
            temperature=0.2,
        )

        goal, filepath, search, replace = self._parse_plan(resp.content)

        if not goal:
            return ActionPlan(
                goal="No refactoring target found.",
                steps=[],
                reasoning=resp.content[:500],
            )

        steps = []
        if filepath and search is not None and replace is not None:
            steps.append(f"Edit {filepath}: {goal[:120]}")

        return ActionPlan(
            goal=goal,
            steps=steps,
            reasoning=resp.content[:500],
            filepath=filepath,
            search=search,
            replace=replace,
        )

    def _parse_plan(self, content: str) -> tuple[str, str | None, str | None, str | None]:
        goal = ""
        filepath = None
        search = None
        replace = None

        for line in content.split("\n"):
            s = line.strip()
            if s.upper().startswith("GOAL:"):
                goal = s.split(":", 1)[1].strip()
            elif s.upper().startswith("FILE:"):
                filepath = s.split(":", 1)[1].strip()

        s_match = re.search(r'SEARCH:\s*<<<\s*\n(.*?)\n\s*>>>', content, re.DOTALL)
        r_match = re.search(r'REPLACE:\s*<<<\s*\n(.*?)\n\s*>>>', content, re.DOTALL)

        if s_match:
            search = s_match.group(1)
        if r_match:
            replace = r_match.group(1)

        return goal, filepath, search, replace

    # ── Act ─────────────────────────────────────────────────────────

    async def act(self, plan: ActionPlan, state: LoopState) -> ActionResult:
        actions = []
        success = True
        error_msg = None

        if plan.filepath and plan.search is not None and plan.replace is not None:
            start = time.time()
            try:
                self._apply_edit(plan.filepath, plan.search, plan.replace)
                actions.append(ActionStep(
                    description=f"Refactored {plan.filepath}: {plan.goal[:120]}",
                    tool="write_file",
                    input_summary=plan.search[:200],
                    output_summary=plan.replace[:200],
                    duration_ms=int((time.time() - start) * 1000),
                ))
            except Exception as e:
                success = False
                error_msg = str(e)
                actions.append(ActionStep(
                    description=f"Failed edit {plan.filepath}: {str(e)[:100]}",
                    tool="write_file",
                    input_summary=plan.search[:200],
                    output_summary=str(e),
                    duration_ms=int((time.time() - start) * 1000),
                    error=str(e),
                ))
            return ActionResult(success=success, actions=actions, error=error_msg)

        for step in plan.steps:
            actions.append(ActionStep(
                description=f"Plan: {step[:200]}",
                tool="llm_call",
                input_summary=plan.goal[:200],
                output_summary=plan.reasoning[:300],
                duration_ms=0,
            ))

        return ActionResult(success=True, actions=actions)

    # ── Evaluate ────────────────────────────────────────────────────

    async def evaluate(self, result: ActionResult, state: LoopState) -> EvaluateResult:
        eval_cmd = state.config.constraints.evaluation
        target = state.config.target

        try:
            output = self._run_cmd(eval_cmd, cwd=self._target_dir(target))
            complexity = self._parse_complexity(output)
            tests_pass = self._tests_passing(output)

            if self._baseline_complexity is None:
                self._baseline_complexity = complexity

            if not tests_pass:
                return EvaluateResult(
                    score=0.0,
                    raw_output=output[:5000],
                    metrics={"complexity": complexity, "tests_pass": False},
                )

            # Score: lower complexity = higher score
            if self._baseline_complexity > 0:
                reduction = (self._baseline_complexity - complexity) / self._baseline_complexity
                score = 0.5 + 0.5 * max(reduction, -0.5)
            else:
                score = 0.5

            score = round(min(max(score, 0.0), 1.0), 3)

            return EvaluateResult(
                score=score,
                raw_output=output[:5000],
                metrics={
                    "complexity": complexity,
                    "baseline_complexity": self._baseline_complexity,
                    "tests_pass": tests_pass,
                },
            )
        except Exception as e:
            return EvaluateResult(score=0.0, raw_output=str(e))

    # ── Decide ──────────────────────────────────────────────────────

    async def decide(
        self,
        score: float,
        history: list[RoundResult],
        constraints: Constraints,
    ) -> Decision:
        if score >= constraints.threshold:
            return Decision.STOP

        if len(history) >= 3:
            recent = history[-3:]
            if all(r.score < 0.55 for r in recent):
                return Decision.STOP

        if len(history) >= 2 and score < history[-2].score - 0.15:
            return Decision.BACKTRACK

        if len(history) >= 4:
            recent = history[-4:]
            if max(r.score for r in recent) <= history[-4].score + 0.05:
                return Decision.STOP

        return Decision.CONTINUE

    # ── Helpers ─────────────────────────────────────────────────────

    def _run_cmd(self, cmd: str, cwd: str | None = None) -> str:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=300, cwd=cwd,
            )
            return (result.stdout + "\n" + result.stderr).strip()
        except subprocess.TimeoutExpired:
            return "Command timed out after 300s"
        except Exception as e:
            return str(e)

    def _parse_complexity(self, output: str) -> int:
        """Extract a complexity score from evaluation output.

        Looks for patterns like:
            - "radon cc ... Average complexity: B (8)"
            - "mccabe: 12"
            - "complexity: 15"
            - "flake8 ... 3 issues"
            - counts "error", "warning", "issue" mentions as fallback
        """
        # Try explicit complexity numbers
        for pattern in [
            r'(?:average|avg|total)\s+complexity[:\s]+(?:is\s+)?[A-Fa-f]?\s*\(?(\d+)\)?',
            r'complexity[:\s]+(\d+)',
            r'mccabe[:\s]+(\d+)',
            r'cognitive\s+complexity[:\s]+(\d+)',
        ]:
            m = re.search(pattern, output, re.IGNORECASE)
            if m:
                return int(m.group(1))

        # Count issues/errors/warnings
        total = 0
        for kw in ("error", "warning", "issue", "violation"):
            total += len(re.findall(rf'\b{kw}\b', output, re.IGNORECASE))

        if total > 0:
            return total

        # Last resort: count lines as rough complexity proxy
        return max(output.count("\n"), 1)

    def _tests_passing(self, output: str) -> bool:
        """Check if tests passed in the output."""
        failure_markers = (
            "FAILED", "ERRORS", "FAILURES",
            "AssertionError", "assert",
            "tests failed", "test failed",
            "failing",
        )
        for marker in failure_markers:
            if marker.lower() in output.lower():
                # Check if it's "0 failed" or similar negation
                negated = re.search(
                    rf'(?:0|no|zero)\s+{re.escape(marker.lower())}',
                    output, re.IGNORECASE,
                )
                if not negated:
                    return False

        # Check for pytest passed line
        if re.search(r'\d+\s+passed', output, re.IGNORECASE):
            return True

        # Check exit code pattern
        if "exit code 0" in output.lower() or "exit: 0" in output.lower():
            return True

        return False

    def _target_dir(self, target) -> str | None:
        if target.path and os.path.isdir(target.path):
            return target.path
        if target.path and os.path.isfile(target.path):
            return os.path.dirname(target.path) or "."
        return None

    def _read_target_files(self, target) -> str:
        parts = []
        p = target.path
        if not p:
            return ""

        if os.path.isfile(p):
            try:
                with open(p) as f:
                    parts.append(f"=== {p} ===\n{f.read()}")
            except Exception:
                pass
        elif os.path.isdir(p):
            for root, _, files in os.walk(p):
                for fn in sorted(files):
                    if fn.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h")):
                        fpath = os.path.join(root, fn)
                        try:
                            with open(fpath) as f:
                                content = f.read()
                            if len(content) < 50000:
                                parts.append(f"=== {fpath} ===\n{content}")
                        except Exception:
                            pass
                if len(parts) > 20:
                    break

        return "\n\n".join("\n".join(parts)[:8000])

    def _apply_edit(self, filepath: str, search: str, replace: str):
        if not os.path.exists(filepath):
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w") as f:
                f.write(replace)
            return

        with open(filepath) as f:
            content = f.read()

        if search in content:
            content = content.replace(search, replace, 1)
        elif search.strip() in content:
            content = content.replace(search.strip(), replace.strip(), 1)
        else:
            content += f"\n# FIXME: could not auto-apply refactor — {replace[:100]}\n"

        with open(filepath, "w") as f:
            f.write(content)

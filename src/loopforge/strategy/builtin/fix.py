"""Fix strategy — find and fix issues iteratively.

Runs: check command → parse errors → fix each error → re-check → loop
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

FIX_PLAN_PROMPT = """\
You are a precise code fixer. Given error output and file contents, produce a fix plan.

Rules:
1. Fix ONE issue per round — be minimal and surgical
2. Syntax errors take priority over logic errors
3. Read the full file context before proposing a change
4. Output in the format below

Output format exactly:
GOAL: <one sentence>
FILE: <path to edit>
SEARCH: <<<
<exact lines to find in the file>
>>>
REPLACE: <<<
<replacement lines>
>>>
"""


class FixStrategy(BaseStrategy):
    name = "fix"
    description = "Iteratively find and fix errors — runs a check command, fixes issues, re-checks"

    def __init__(self, llm, **kwargs):
        super().__init__(llm=llm, **kwargs)

    # ── Plan ────────────────────────────────────────────────────────

    async def plan(self, state: LoopState) -> ActionPlan:
        target = state.config.target
        eval_cmd = state.config.constraints.evaluation

        errors = self._run_cmd(eval_cmd, cwd=self._target_dir(target))
        files = self._read_target_files(target)

        if not errors.strip() or "ALL_TESTS_PASSED" in errors:
            return ActionPlan(
                goal="No errors detected — all checks pass.",
                steps=[],
                reasoning="Evaluation command returned clean output.",
            )

        ctx = f"""Evaluation command: `{eval_cmd}`

--- ERRORS ---
{errors[:6000]}

--- FILES ---
{files[:8000]}

Previous rounds: {len(state.rounds)}
Best score: {state.best_score}
"""

        resp = await self.llm.chat(
            messages=[LLMMessage(role="user", content=ctx)],
            system=FIX_PLAN_PROMPT,
            max_tokens=2048,
            temperature=0.2,
        )

        goal, filepath, search, replace = self._parse_plan(resp.content)

        if not goal:
            goal = "Fix detected errors"

        steps = []
        if filepath and search is not None and replace is not None:
            steps.append(f"Edit {filepath}: replace '{search[:80]}' with '{replace[:80]}'")

        return ActionPlan(
            goal=goal,
            steps=steps,
            reasoning=resp.content[:500],
            filepath=filepath,
            search=search,
            replace=replace,
        )

    def _parse_plan(self, content: str) -> tuple[str, str | None, str | None, str | None]:
        """Parse GOAL/FILE/SEARCH/REPLACE from LLM output."""
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

        # Extract SEARCH/REPLACE blocks
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

        # Use edit data from plan directly (no second LLM call needed)
        if plan.filepath and plan.search is not None and plan.replace is not None:
            start = time.time()
            try:
                self._apply_edit(plan.filepath, plan.search, plan.replace)
                actions.append(ActionStep(
                    description=f"Edited {plan.filepath}: {plan.goal[:120]}",
                    tool="write_file",
                    input_summary=plan.search[:200],
                    output_summary=plan.replace[:200],
                    duration_ms=int((time.time() - start) * 1000),
                ))
            except Exception as e:
                success = False
                error_msg = str(e)
                actions.append(ActionStep(
                    description=f"Failed edit {plan.filepath}: {plan.goal[:100]}",
                    tool="write_file",
                    input_summary=plan.search[:200],
                    output_summary=str(e),
                    duration_ms=int((time.time() - start) * 1000),
                    error=str(e),
                ))
            return ActionResult(success=success, actions=actions, error=error_msg)

        # Fallback: describe what we would do
        for step in plan.steps:
            actions.append(ActionStep(
                description=f"Plan (no direct edit data): {step[:200]}",
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
            error_lines = [
                l for l in output.split("\n")
                if any(kw in l.lower() for kw in ("error", "fail", "traceback", "syntaxerror"))
            ]

            if not error_lines and "ALL_TESTS_PASSED" not in output:
                # No errors and not explicitly passing — still good
                score = 1.0 if output.strip() == "" else 0.95
            elif not error_lines:
                score = 1.0
            else:
                score = max(0.0, 1.0 - len(error_lines) * 0.08)

            return EvaluateResult(
                score=round(min(score, 1.0), 3),
                raw_output=output[:5000],
                metrics={"error_count": len(error_lines)},
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
            if all(r.score < 0.6 for r in recent):
                return Decision.STOP

        if len(history) >= 2 and score < history[-2].score - 0.15:
            return Decision.BACKTRACK

        return Decision.CONTINUE

    # ── Helpers ─────────────────────────────────────────────────────

    def _run_cmd(self, cmd: str, cwd: str | None = None) -> str:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=120, cwd=cwd,
            )
            return (result.stdout + "\n" + result.stderr).strip()
        except subprocess.TimeoutExpired:
            return "Command timed out after 120s"
        except Exception as e:
            return str(e)

    def _target_dir(self, target) -> str | None:
        """Resolve working directory from target path."""
        if target.path and os.path.isdir(target.path):
            return target.path
        if target.path and os.path.isfile(target.path):
            return os.path.dirname(target.path) or "."
        return None

    def _read_target_files(self, target) -> str:
        """Read files from the target path."""
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
                    if fn.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".sql", ".yaml", ".yml", ".json", ".toml")):
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

        return "\n\n".join(parts[:8000])

    def _apply_edit(self, filepath: str, search: str, replace: str):
        """Find search text in file and replace it."""
        if not os.path.exists(filepath):
            # New file
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w") as f:
                f.write(replace)
            return

        with open(filepath) as f:
            content = f.read()

        if search in content:
            content = content.replace(search, replace, 1)
        else:
            # Try stripping whitespace differences
            search_stripped = search.strip()
            if search_stripped in content:
                content = content.replace(search_stripped, replace.strip(), 1)
            else:
                # Append suggestion as comment if exact match fails
                content += f"\n# FIXME: could not auto-apply — {replace[:100]}\n"

        with open(filepath, "w") as f:
            f.write(content)

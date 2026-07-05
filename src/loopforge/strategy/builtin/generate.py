"""Generate strategy — spec-driven code generation loop.

Given a spec file or test file, generates implementation code that satisfies it.
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

GENERATE_PLAN_PROMPT = """\
You are a software engineer. Given a specification (docstring, test file, or requirements), generate the implementation code.

Rules:
1. Write complete, working code — no stubs or TODOs
2. Handle edge cases and errors properly
3. Follow the language idioms and best practices
4. Match the interfaces defined in the tests or spec exactly

Output format exactly:
GOAL: <one sentence describing what you are implementing>
FILE: <path to the output file>
SEARCH: <<<
<<<FILE_START>>>
>>>
REPLACE: <<<
<the complete implementation code>
>>>
"""


class GenerateStrategy(BaseStrategy):
    name = "generate"
    description = "Generate implementation code from specifications or tests"

    def __init__(self, llm, **kwargs):
        super().__init__(llm=llm, **kwargs)

    # ── Plan ────────────────────────────────────────────────────────

    async def plan(self, state: LoopState) -> ActionPlan:
        target = state.config.target
        eval_cmd = state.config.constraints.evaluation

        # Run evaluation to see current state
        output = self._run_cmd(eval_cmd, cwd=self._target_dir(target))
        spec_files = self._read_target_files(target)

        ctx = f"""Evaluation command: `{eval_cmd}`

--- CURRENT OUTPUT ---
{output[:4000]}

--- SPEC / TEST FILES ---
{spec_files[:8000]}

Round {state.current_round} of {state.config.constraints.max_rounds}
Current best score: {state.best_score}
"""

        resp = await self.llm.chat(
            messages=[LLMMessage(role="user", content=ctx)],
            system=GENERATE_PLAN_PROMPT,
            max_tokens=4096,
            temperature=0.2,
        )

        goal, filepath, search, replace = self._parse_plan(resp.content)

        if not goal:
            return ActionPlan(
                goal="Generate implementation from spec",
                steps=[],
                reasoning=resp.content[:500],
            )

        steps = []
        if filepath and replace:
            steps.append(f"Write {filepath}")

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

        if plan.filepath and plan.replace is not None:
            start = time.time()
            try:
                search_text = plan.search or "<<<FILE_START>>>"
                self._apply_edit(plan.filepath, search_text, plan.replace)
                actions.append(ActionStep(
                    description=f"Generated {plan.filepath}: {plan.goal[:120]}",
                    tool="write_file",
                    input_summary=plan.goal[:200],
                    output_summary=plan.replace[:200],
                    duration_ms=int((time.time() - start) * 1000),
                ))
            except Exception as e:
                success = False
                error_msg = str(e)
                actions.append(ActionStep(
                    description=f"Failed to write {plan.filepath}: {str(e)[:100]}",
                    tool="write_file",
                    input_summary=plan.goal[:200],
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

            passed = len(re.findall(r'\bPASSED\b', output))
            failed = len(re.findall(r'\bFAILED\b', output))
            total = passed + failed

            if total > 0:
                score = round(passed / total, 3)
            elif "error" in output.lower() or "traceback" in output.lower():
                score = 0.0
            else:
                score = 0.95

            return EvaluateResult(
                score=score,
                raw_output=output[:5000],
                metrics={"passed": passed, "failed": failed, "total": total},
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
            if all(r.score < 0.5 for r in recent):
                return Decision.STOP

        if len(history) >= 2 and score < history[-2].score - 0.1:
            return Decision.BACKTRACK

        if len(history) >= 4 and max(r.score for r in history[-4:]) <= history[-4].score + 0.03:
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
                    if fn.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".sql", ".yaml", ".yml", ".json", ".toml", ".md", ".txt")):
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
        elif search == "<<<FILE_START>>>":
            # Creating new file — overwrite
            pass
        else:
            content += f"\n# TODO: could not auto-apply — {replace[:100]}\n"

        with open(filepath, "w") as f:
            f.write(content)

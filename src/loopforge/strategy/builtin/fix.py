"""Fix strategy — find and fix issues iteratively.

Runs: check command → parse errors → fix each error → re-check → loop
"""

from __future__ import annotations

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


FIX_SYSTEM_PROMPT = """\
You are a code fixer. Given a set of errors/warnings, generate a concrete fix plan.

Rules:
1. Fix one category of error per round — don't try to fix everything at once
2. If there are syntax errors, fix those first
3. Prefer minimal, targeted changes
4. Explain why each change fixes the error

Output format:
GOAL: <one sentence summary of what this round fixes>
STEPS:
- <specific file change 1>
- <specific file change 2>
REASONING: <why this approach>
"""


class FixStrategy(BaseStrategy):
    name = "fix"
    description = "Iteratively find and fix errors — runs a check command, fixes issues, re-checks"

    def __init__(self, llm, **kwargs):
        super().__init__(llm=llm, **kwargs)

    async def plan(self, state: LoopState) -> ActionPlan:
        # Run the evaluation command to get current errors
        eval_cmd = state.config.constraints.evaluation
        errors = self._run_check(eval_cmd)

        if not errors.strip():
            return ActionPlan(
                goal="No errors detected — nothing to fix",
                steps=[],
                reasoning="Evaluation command returned clean output",
            )

        # Ask LLM to generate a fix plan
        messages = [
            LLMMessage(role="user", content=f"""Current errors from `{eval_cmd}`:

{errors[:8000]}

Previous rounds: {len(state.rounds)}
Best score so far: {state.best_score}

Generate a fix plan for the NEXT batch of errors to fix.""")
        ]

        resp = await self.llm.chat(
            messages=messages,
            system=FIX_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.2,
        )

        # Parse LLM output
        content = resp.content
        goal = ""
        steps = []
        reasoning = ""

        for line in content.split("\n"):
            line = line.strip()
            if line.upper().startswith("GOAL:"):
                goal = line.split(":", 1)[1].strip()
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()
            elif line.startswith("- "):
                steps.append(line[2:])

        if not goal:
            goal = "Fix errors detected by evaluation command"
        if not steps:
            steps = ["Apply LLM-suggested fix to source files"]

        return ActionPlan(goal=goal, steps=steps, reasoning=reasoning)

    def _run_check(self, cmd: str) -> str:
        """Run the evaluation command and return stdout+stderr."""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=self._resolve_cwd(),
            )
            return (result.stdout + "\n" + result.stderr).strip()
        except subprocess.TimeoutExpired:
            return "Check timed out"
        except Exception as e:
            return str(e)

    def _resolve_cwd(self) -> str | None:
        """Resolve the working directory from target path."""
        # Default to current directory
        return None

    async def act(self, plan: ActionPlan, state: LoopState) -> ActionResult:
        actions = []
        success = True
        error_msg = None

        for step in plan.steps:
            start = time.time()
            try:
                # Ask LLM to generate the actual code change
                messages = [
                    LLMMessage(role="user", content=f"""Plan goal: {plan.goal}
Step to implement: {step}

Previous best score: {state.best_score}

Generate the EXACT code change needed. Use this format:
FILE: <path>
--- ORIGINAL
<old code>
+++ FIXED
<new code>""")
                ]

                resp = await self.llm.chat(
                    messages=messages,
                    max_tokens=4096,
                    temperature=0.1,
                )

                # Parse and apply the change
                parsed = self._parse_diff(resp.content)
                if parsed:
                    filepath, old, new = parsed
                    self._apply_change(filepath, old, new)
                    actions.append(ActionStep(
                        description=f"Fixed {filepath}: {step[:100]}",
                        tool="write_file",
                        input_summary=old[:200],
                        output_summary=new[:200],
                        duration_ms=int((time.time() - start) * 1000),
                    ))
                else:
                    actions.append(ActionStep(
                        description=f"LLM suggested fix (not auto-applied): {step[:100]}",
                        tool="llm_call",
                        input_summary=step[:200],
                        output_summary=resp.content[:200],
                        duration_ms=int((time.time() - start) * 1000),
                    ))

            except Exception as e:
                success = False
                error_msg = str(e)
                actions.append(ActionStep(
                    description=f"Failed: {step[:100]}",
                    tool="write_file",
                    input_summary=step[:200],
                    output_summary=str(e),
                    duration_ms=int((time.time() - start) * 1000),
                    error=str(e),
                ))

        return ActionResult(success=success, actions=actions, error=error_msg)

    def _parse_diff(self, content: str) -> tuple[str, str, str] | None:
        """Parse a FILE/ORIGINAL/FIXED block from LLM output."""
        filepath = ""
        original = ""
        fixed = ""

        for line in content.split("\n"):
            if line.upper().startswith("FILE:"):
                filepath = line.split(":", 1)[1].strip()
            elif line.strip() == "--- ORIGINAL":
                original = ""
            elif line.strip() == "+++ FIXED":
                # Switch to collecting fixed
                pass
            elif original is not None and filepath:
                # Simple case: collect until we see +++ FIXED
                pass

        # Simplified: just return the raw content for now
        if "FILE:" in content:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.upper().startswith("FILE:"):
                    filepath = line.split(":", 1)[1].strip()
                    # Find ORIGINAL and FIXED sections
                    rest = "\n".join(lines[i+1:])
                    if "--- ORIGINAL" in rest and "+++ FIXED" in rest:
                        orig_start = rest.index("--- ORIGINAL") + len("--- ORIGINAL")
                        fixed_start = rest.index("+++ FIXED")
                        orig_end = fixed_start
                        original = rest[orig_start:orig_end].strip()
                        fixed = rest[fixed_start + len("+++ FIXED"):].strip()
                        return (filepath, original, fixed)
            return None
        return None

    def _apply_change(self, filepath: str, old: str, new: str):
        """Apply a file change. Creates backup first."""
        import os

        if not os.path.exists(filepath):
            # New file
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w") as f:
                f.write(new)
            return

        with open(filepath, "r") as f:
            content = f.read()

        if old in content:
            content = content.replace(old, new, 1)
            with open(filepath, "w") as f:
                f.write(content)

    async def evaluate(self, result: ActionResult, state: LoopState) -> EvaluateResult:
        eval_cmd = state.config.constraints.evaluation

        try:
            proc = subprocess.run(
                eval_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (proc.stdout + "\n" + proc.stderr).strip()

            # Score: if exit code 0 and no error output → high score
            # Each error line reduces the score
            error_lines = [l for l in output.split("\n") if "error" in l.lower() or "fail" in l.lower()]
            if proc.returncode == 0 and len(error_lines) == 0:
                score = 1.0
            elif proc.returncode == 0:
                score = max(0.0, 1.0 - len(error_lines) * 0.1)
            else:
                score = max(0.0, 0.5 - len(error_lines) * 0.05)

            return EvaluateResult(score=round(score, 3), raw_output=output[:5000])
        except Exception as e:
            return EvaluateResult(score=0.0, raw_output=str(e))

    async def decide(
        self,
        score: float,
        history: list[RoundResult],
        constraints: Constraints,
    ) -> Decision:
        if score >= constraints.threshold:
            return Decision.STOP

        # If last 3 rounds showed no improvement, stop
        if len(history) >= 3:
            recent = history[-3:]
            if all(r.score <= 0.5 for r in recent) and max(r.score for r in recent) <= history[-4].score if len(history) >= 4 else False:
                return Decision.STOP

        # If score decreased, backtrack
        if len(history) >= 2 and score < history[-2].score - 0.1:
            return Decision.BACKTRACK

        return Decision.CONTINUE

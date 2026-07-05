"""Optimize strategy — benchmark-driven performance optimization loop.

Runs: benchmark → profile bottleneck → optimize → re-benchmark → loop
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

OPTIMIZE_PLAN_PROMPT = """\
You are a performance engineer. Given benchmark output and source code, find the biggest bottleneck and propose a targeted optimization.

Rules:
1. Focus on ONE bottleneck per round — the one with the highest impact
2. Use profiling data to guide your choice, don't guess
3. Prefer algorithmic improvements over micro-optimizations
4. Keep the code correct — all existing behavior must be preserved

Output format exactly:
GOAL: <one sentence describing the optimization>
FILE: <path to edit>
SEARCH: <<<
<exact lines to find in the file>
>>>
REPLACE: <<<
<replacement lines>
>>>
"""


class OptimizeStrategy(BaseStrategy):
    name = "optimize"
    description = "Benchmark-driven optimization — profile, optimize, measure, repeat"

    def __init__(self, llm, **kwargs):
        super().__init__(llm=llm, **kwargs)
        self._baseline: float | None = None
        self._last_metric: float | None = None

    # ── Plan ────────────────────────────────────────────────────────

    async def plan(self, state: LoopState) -> ActionPlan:
        target = state.config.target
        eval_cmd = state.config.constraints.evaluation

        bench_output = self._run_cmd(eval_cmd, cwd=self._target_dir(target))
        current = self._parse_metric(bench_output)

        # Track baseline from first round
        if self._baseline is None and current is not None:
            self._baseline = current
        self._last_metric = current

        if self._baseline and current:
            improvement = ((current - self._baseline) / self._baseline) * 100
            perf_line = f"Current: {current:.4f}, Baseline: {self._baseline:.4f} ({improvement:+.1f}%)"
        elif current:
            perf_line = f"Current metric: {current:.4f}"
        else:
            perf_line = "No numeric metric found in benchmark output."

        files = self._read_target_files(target)

        ctx = f"""Benchmark command: `{eval_cmd}`

--- BENCHMARK OUTPUT ---
{bench_output[:6000]}

{perf_line}

--- SOURCE FILES ---
{files[:8000]}

Previous rounds: {len(state.rounds)}
Best score: {state.best_score}
"""

        resp = await self.llm.chat(
            messages=[LLMMessage(role="user", content=ctx)],
            system=OPTIMIZE_PLAN_PROMPT,
            max_tokens=2048,
            temperature=0.2,
        )

        goal, filepath, search, replace = self._parse_plan(resp.content)

        if not goal:
            return ActionPlan(
                goal="No clear optimization target found.",
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
                    description=f"Optimized {plan.filepath}: {plan.goal[:120]}",
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
            current = self._parse_metric(output)

            if current is None:
                return EvaluateResult(
                    score=0.5,
                    raw_output=output[:5000],
                    metrics={"error": "No metric found in output"},
                )

            if self._baseline is None:
                self._baseline = current

            # Score: improvement over baseline, clamped to [0, 1]
            # Lower metric = better (e.g. time), so improvement = (baseline - current) / baseline
            if self._baseline > 0:
                ratio = current / self._baseline
                if ratio <= 1.0:
                    # Got faster or same
                    score = 0.5 + 0.5 * (1.0 - ratio)
                else:
                    # Got slower
                    score = max(0.0, 0.5 - 0.5 * min(ratio - 1.0, 1.0))
            else:
                score = 0.5

            score = round(min(max(score, 0.0), 1.0), 3)

            return EvaluateResult(
                score=score,
                raw_output=output[:5000],
                metrics={
                    "current": current,
                    "baseline": self._baseline,
                    "improvement_pct": round((1.0 - current / self._baseline) * 100, 2) if self._baseline > 0 else 0,
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

        # Stop if no improvement for many rounds
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

    def _parse_metric(self, output: str) -> float | None:
        """Extract a numeric performance metric from benchmark output.

        Tries to find patterns like:
            - "Time: 0.1234s" or "time: 123ms"
            - "ops/sec: 1234.5"
            - "elapsed: 0.5"
            - plain number at end of line: "benchmark: 0.5432"
        """
        # Try explicit time patterns first
        for pattern in [
            r'(?:time|elapsed|duration)[:=]\s*([\d.]+)\s*(?:s|sec|seconds?|ms)?',
            r'([\d.]+)\s*(?:s|sec|seconds?)\s+(?:per|/)\s+',
        ]:
            matches = re.findall(pattern, output, re.IGNORECASE)
            if matches:
                return float(matches[0])

        # Try ops/sec or throughput
        m = re.search(r'(?:ops|throughput|it)\s*(?:/|per)\s*sec[:=]\s*([\d.]+)', output, re.IGNORECASE)
        if m:
            return float(m.group(1))

        # Try lines like "average: 0.123" or "mean: 42.5"
        for line in output.split("\n"):
            m = re.search(r'(?:avg|average|mean|median|total)[:=]\s*([\d.]+)', line, re.IGNORECASE)
            if m:
                return float(m.group(1))

        # Last resort: try any standalone number on its own line
        for line in reversed(output.split("\n")):
            line = line.strip()
            m = re.match(r'^([\d.]+)$', line)
            if m and '.' in m.group(1):
                return float(m.group(1))

        return None

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
                    if fn.endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".sql")):
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
            content += f"\n# FIXME: could not auto-apply optimization — {replace[:100]}\n"

        with open(filepath, "w") as f:
            f.write(content)

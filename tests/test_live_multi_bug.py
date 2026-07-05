"""Live test: fix strategy on a file with 3 bugs. Requires DeepSeek API key in .env."""
import asyncio
import os
import sys

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("LOOPFORGE_MODEL", "deepseek-chat")

from loopforge.db import init_db, save_loop
from loopforge.engine import LoopEngine
from loopforge.models import LoopConfig, LoopState, TargetSpec, Constraints

EVAL_CMD = (
    "cd /tmp/loopforge_demo && "
    "python3 -c 'import buggy2; "
    "print(buggy2.divide_numbers(10, 2)); "
    "print(buggy2.divide_numbers(10, 0)); "
    "print(buggy2.get_first([1,2,3])); "
    "print(buggy2.sum_list([1,2,3]))' 2>&1"
)


async def main():
    init_db()

    config = LoopConfig(
        name="fix-3-bugs",
        strategy="fix",
        target=TargetSpec(path="/tmp/loopforge_demo/buggy2.py", language="python"),
        constraints=Constraints(
            max_rounds=6,
            evaluation=EVAL_CMD,
            threshold=0.95,
        ),
        llm_model="deepseek-chat",
    )

    state = LoopState(config=config)
    save_loop(state)

    print(f"Target: /tmp/loopforge_demo/buggy2.py")
    print(f"Bugs: syntax error (line 7), syntax error (line 13), NameError typo (line 21)")
    print()

    engine = LoopEngine(state)
    result = await engine.run()

    print(f"Status: {result.status.value}")
    print(f"Rounds: {result.current_round}")
    print(f"Best score: {result.best_score}")
    print()

    for r in result.rounds:
        print(f"--- Round {r.round_number} ---")
        print(f"Plan: {r.plan[:200]}")
        print(f"Score: {r.score}  Decision: {r.decision.value}")
        for a in r.actions:
            if a.tool == "write_file":
                print(f"  ✅ Applied: {a.description[:150]}")
            elif a.error:
                print(f"  ❌ Error: {a.error[:150]}")
        print()

    print("=== Final file ===")
    with open("/tmp/loopforge_demo/buggy2.py") as f:
        print(f.read())

    if result.errors:
        print("Errors:", result.errors)

    # Verify: file should now compile and run without errors
    try:
        import subprocess
        r = subprocess.run(
            EVAL_CMD, shell=True, capture_output=True, text=True, timeout=10
        )
        print(f"\nFinal eval: {r.stdout.strip()}")
        print(f"Exit: {r.returncode}")
        if r.returncode == 0 and "NameError" not in r.stdout and "SyntaxError" not in r.stdout:
            print("✅ All 3 bugs fixed!")
        else:
            print(f"⚠️  Some issues remain (fixed {result.current_round}/{result.best_score:.0%} rounds, score={result.best_score})")
    except Exception as e:
        print(f"Verification failed: {e}")

    save_loop(result)


if __name__ == "__main__":
    asyncio.run(main())

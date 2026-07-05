"""Live test: fix strategy on a buggy Python file with DeepSeek."""
import asyncio
import os
import sys

# Read .env
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


async def main():
    init_db()

    config = LoopConfig(
        name="fix-buggy-py",
        strategy="fix",
        target=TargetSpec(path="/tmp/loopforge_demo", language="python"),
        constraints=Constraints(
            max_rounds=3,
            evaluation="cd /tmp/loopforge_demo && python3 -c 'import buggy; print(buggy.broken_function(5))' 2>&1",
            threshold=0.9,
        ),
        llm_model="deepseek-chat",
    )

    state = LoopState(config=config)
    save_loop(state)

    print(f"Loop ID: {state.id}")
    print(f"Target: /tmp/loopforge_demo/buggy.py")
    print(f"Eval: python3 -m py_compile + import check")
    print()

    engine = LoopEngine(state)
    result = await engine.run()

    print(f"Status: {result.status.value}")
    print(f"Rounds: {result.current_round}")
    print(f"Best score: {result.best_score}")
    print()

    for r in result.rounds:
        print(f"=== Round {r.round_number} ===")
        print(f"Plan: {r.plan[:500]}")
        print(f"Score: {r.score}")
        print(f"Decision: {r.decision.value}")
        for a in r.actions:
            desc = a.description[:300]
            print(f"  [{a.tool}] {desc}")
            if a.error:
                print(f"  ERROR: {a.error[:200]}")
        print()

    # Show final file content
    print("=== Final buggy.py ===")
    with open("/tmp/loopforge_demo/buggy.py") as f:
        print(f.read())

    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  - {e}")

    save_loop(result)
    return result


if __name__ == "__main__":
    result = asyncio.run(main())
    print(f"\nDone: {result.current_round} rounds, score={result.best_score}")

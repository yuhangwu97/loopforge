"""Live integration test with DeepSeek — one round of fix strategy."""
import asyncio
import os
import sys

# Read API key from .env
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
        name="live-test-deepseek",
        strategy="fix",
        target=TargetSpec(path="./src/loopforge"),
        constraints=Constraints(
            max_rounds=1,
            evaluation="echo ALL_TESTS_PASSED",
            threshold=0.9,
        ),
        llm_model="deepseek-chat",
    )

    state = LoopState(config=config)
    save_loop(state)

    print(f"Loop ID: {state.id}")
    print(f"Model: {config.llm_model}")
    print(f"Strategy: {config.strategy}")
    print()

    engine = LoopEngine(state)
    result = await engine.run()

    print(f"Status: {result.status.value}")
    print(f"Rounds: {result.current_round}")
    print(f"Best score: {result.best_score}")
    print()

    for r in result.rounds:
        print(f"--- Round {r.round_number} ---")
        print(f"Plan: {r.plan[:300]}")
        print(f"Score: {r.score}")
        print(f"Decision: {r.decision.value}")
        for a in r.actions:
            print(f"  Action: {a.description[:200]}")
            if a.error:
                print(f"  Error: {a.error}")
        print()

    if result.errors:
        print("Errors:")
        for e in result.errors:
            print(f"  - {e}")

    save_loop(result)
    return result


if __name__ == "__main__":
    result = asyncio.run(main())
    if result.status.value == "done" and result.current_round >= 1:
        print("SUCCESS: Loop completed with DeepSeek")
        sys.exit(0)
    else:
        print(f"FAILED: status={result.status.value}, rounds={result.current_round}")
        sys.exit(1)

# LoopForge

> **AI-powered engineering loop engine.** Runs iterative refinement cycles as a background service.
>
> Given a goal → Plan → Execute → Evaluate → Improve → Loop again → until satisfied.

## Quick Start (planned)

```bash
pip install loopforge

# One-shot
loopforge run --strategy optimize --target ./src --eval "python bench.py"

# As a service
loopforge serve --port 8848
```

## Architecture

See [DESIGN.md](DESIGN.md) for the full architecture.

## License

MIT

"""CLI Entry Point."""

import typer
from rich.console import Console

app = typer.Typer(name="loopforge", help="AI-powered engineering loop engine")
console = Console()


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8848,
    reload: bool = False,
):
    """Start LoopForge as a background service (FastAPI + worker)."""
    import uvicorn

    console.print(f"[bold green]LoopForge v0.1.0[/]")
    console.print(f"  API:  http://{host}:{port}")
    console.print(f"  Docs: http://{host}:{port}/docs")
    console.print(f"  Health: http://{host}:{port}/health")

    uvicorn.run(
        "loopforge.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def run(
    strategy: str = typer.Option(..., help="Strategy name: fix, optimize, refactor"),
    target: str = typer.Option(..., help="Target path or directory"),
    eval_cmd: str = typer.Option("pytest", help="Evaluation command to run"),
    max_rounds: int = typer.Option(10, help="Maximum loop rounds"),
    threshold: float = typer.Option(0.9, help="Score threshold to stop (0-1)"),
):
    """Run a one-shot loop task (no server needed)."""
    import asyncio
    from loopforge.db import init_db, save_loop
    from loopforge.engine import LoopEngine
    from loopforge.models import LoopState, LoopConfig, TargetSpec, Constraints

    init_db()

    config = LoopConfig(
        name=f"{strategy}-{target.replace('/', '-')}",
        strategy=strategy,
        target=TargetSpec(path=target),
        constraints=Constraints(
            max_rounds=max_rounds,
            evaluation=eval_cmd,
            threshold=threshold,
        ),
    )

    state = LoopState(config=config)
    save_loop(state)

    console.print(f"[bold]Strategy:[/] {strategy}")
    console.print(f"[bold]Target:[/] {target}")
    console.print(f"[bold]Eval:[/] {eval_cmd}")
    console.print(f"[bold]Max rounds:[/] {max_rounds}")
    console.print()

    engine = LoopEngine(state)

    async def run_loop():
        result = await engine.run()
        console.print(f"\n[bold]Done:[/] {result.status.value}")
        console.print(f"Rounds: {result.current_round}")
        console.print(f"Best score: {result.best_score}")
        if result.errors:
            console.print(f"\n[red]Errors:[/]")
            for e in result.errors:
                console.print(f"  - {e}")
        return result

    final_state = asyncio.run(run_loop())
    save_loop(final_state)


@app.command()
def bot(
    repo: str = typer.Option(..., help="GitHub repository: owner/repo"),
    port: int = typer.Option(8848, help="Port to listen on"),
):
    """Start a GitHub bot server — listens for PR webhooks and auto-fixes code."""
    import uvicorn

    console.print(f"[bold green]LoopForge GitHub Bot[/]")
    console.print(f"  Repo: {repo}")
    console.print(f"  Webhook URL: http://<host>:{port}/api/v1/webhook/github")
    console.print()
    console.print("Configure this URL in your GitHub repo settings:")
    console.print(f"  Settings → Webhooks → Add webhook")
    console.print(f"  Payload URL: http://<your-server>:{port}/api/v1/webhook/github")
    console.print(f"  Content type: application/json")
    console.print(f"  Events: Pull requests")

    uvicorn.run(
        "loopforge.server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


@app.command()
def worker(
    concurrency: int = 1,
    queues: str = "celery",
):
    """Start a Celery worker for background task processing."""
    from loopforge.celery_app import celery_app, is_redis_available

    if not is_redis_available():
        console.print("[red]Redis is not available.[/]")
        console.print("Set LOOPFORGE_REDIS_URL or start Redis first.")
        console.print("  e.g. docker run -d -p 6379:6379 redis:7")
        raise typer.Exit(1)

    console.print(f"[bold green]Starting LoopForge worker[/]")
    console.print(f"  Broker: {celery_app.conf.broker_url}")
    console.print(f"  Concurrency: {concurrency}")

    argv = [
        "worker",
        "--loglevel=info",
        f"--concurrency={concurrency}",
        f"--queues={queues}",
    ]
    celery_app.worker_main(argv)


@app.command()
def strategies():
    """List available strategies."""
    from loopforge.strategy.registry import list_strategies

    for s in list_strategies():
        console.print(f"  [bold]{s['name']}[/] — {s['description']}")


def cli():
    app()

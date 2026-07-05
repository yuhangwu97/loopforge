"""Strategy registry — discovers and loads strategies."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from loopforge.strategy.base import BaseStrategy


_registry: dict[str, type[BaseStrategy]] = {}


def register(name: str, cls: type[BaseStrategy]):
    """Register a strategy class."""
    _registry[name] = cls


def discover():
    """Discover strategies from installed entry points."""
    try:
        eps = entry_points(group="loopforge.strategies")
        for ep in eps:
            try:
                cls = ep.load()
                if issubclass(cls, BaseStrategy):
                    register(ep.name, cls)
            except Exception:
                pass
    except Exception:
        pass


def get_strategy(name: str, **kwargs) -> BaseStrategy:
    """Get a strategy instance by name."""
    discover()

    if name not in _registry:
        # Try importing builtins
        from loopforge.strategy.builtin.fix import FixStrategy
        from loopforge.strategy.builtin.optimize import OptimizeStrategy
        from loopforge.strategy.builtin.refactor import RefactorStrategy
        from loopforge.strategy.builtin.generate import GenerateStrategy
        from loopforge.strategy.builtin.review import ReviewStrategy

        builtins = {
            "fix": FixStrategy,
            "optimize": OptimizeStrategy,
            "refactor": RefactorStrategy,
            "generate": GenerateStrategy,
            "review": ReviewStrategy,
        }
        for n, cls in builtins.items():
            register(n, cls)

    if name not in _registry:
        raise ValueError(f"Strategy '{name}' not found. Available: {list(_registry.keys())}")

    return _registry[name](**kwargs)


def list_strategies() -> list[dict[str, Any]]:
    """List all registered strategies with metadata."""
    discover()

    from loopforge.strategy.builtin.fix import FixStrategy
    from loopforge.strategy.builtin.optimize import OptimizeStrategy
    from loopforge.strategy.builtin.refactor import RefactorStrategy
    from loopforge.strategy.builtin.generate import GenerateStrategy
    from loopforge.strategy.builtin.review import ReviewStrategy

    builtins = {
        "fix": FixStrategy,
        "optimize": OptimizeStrategy,
        "refactor": RefactorStrategy,
        "generate": GenerateStrategy,
        "review": ReviewStrategy,
    }
    for n, cls in builtins.items():
        if n not in _registry:
            register(n, cls)

    return [
        {"name": name, "description": cls.description or cls.__doc__ or ""}
        for name, cls in _registry.items()
    ]

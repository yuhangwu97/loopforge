"""Tests for the database layer."""

import tempfile
import os
import sys


def test_crud_operations(monkeypatch):
    """Test create, read, list, delete operations."""
    # Use temp file for test DB
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("loopforge.db.DB_PATH", tmp.name)

    from loopforge.db import init_db, save_loop, load_loop, list_loops, delete_loop
    from loopforge.models import LoopConfig, LoopState, TargetSpec, Constraints

    init_db()

    # Create
    state = LoopState(
        config=LoopConfig(
            name="test-loop",
            strategy="fix",
            target=TargetSpec(path="/tmp/test"),
            constraints=Constraints(max_rounds=3, evaluation="pytest"),
        ),
    )
    save_loop(state)

    # Read
    loaded = load_loop(state.id)
    assert loaded is not None
    assert loaded.config.name == "test-loop"
    assert loaded.config.strategy == "fix"
    assert loaded.current_round == 0

    # List
    loops = list_loops()
    assert len(loops) == 1
    assert loops[0]["name"] == "test-loop"

    # Delete
    delete_loop(state.id)
    assert load_loop(state.id) is None
    assert list_loops() == []

    os.unlink(tmp.name)


def test_save_and_update(monkeypatch):
    """Test that saving updates existing records."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("loopforge.db.DB_PATH", tmp.name)

    from loopforge.db import init_db, save_loop, load_loop
    from loopforge.models import LoopConfig, LoopState, LoopStatus, TargetSpec, Constraints

    init_db()

    state = LoopState(
        config=LoopConfig(
            name="update-test",
            strategy="fix",
            target=TargetSpec(path="/tmp/test"),
            constraints=Constraints(max_rounds=5),
        ),
    )
    save_loop(state)

    # Update
    state.status = LoopStatus.DONE
    state.current_round = 3
    state.best_score = 0.95
    save_loop(state)

    loaded = load_loop(state.id)
    assert loaded.status == LoopStatus.DONE
    assert loaded.current_round == 3
    assert loaded.best_score == 0.95

    os.unlink(tmp.name)


def test_list_loops_filtered(monkeypatch):
    """Test listing loops filtered by status."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("loopforge.db.DB_PATH", tmp.name)

    from loopforge.db import init_db, save_loop, list_loops
    from loopforge.models import LoopConfig, LoopState, LoopStatus, TargetSpec, Constraints

    init_db()

    for i, status in enumerate([LoopStatus.DONE, LoopStatus.FAILED, LoopStatus.DONE]):
        state = LoopState(
            config=LoopConfig(
                name=f"loop-{i}",
                strategy="fix",
                target=TargetSpec(path="/tmp"),
                constraints=Constraints(),
            ),
        )
        state.status = status
        save_loop(state)

    assert len(list_loops()) == 3
    assert len(list_loops(status="done")) == 2
    assert len(list_loops(status="failed")) == 1
    assert len(list_loops(status="idle")) == 0

    os.unlink(tmp.name)

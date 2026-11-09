"""Хранилище проблем дома: атомарность, версия, повреждённый файл."""

from __future__ import annotations

import json

from core.persistence.health_store import HealthStore, empty_state


def test_save_and_load_roundtrip(tmp_path) -> None:
    """Сохранённое состояние читается тем же составом."""
    path = tmp_path / "health.json"
    store = HealthStore(path)
    state = empty_state()
    state["problems"] = [{"id": "a", "kind": "stale"}]
    state["notification"] = {"fingerprint": "x", "active": True}

    store.save(state)

    loaded = HealthStore(path).load()
    assert loaded["problems"] == [{"id": "a", "kind": "stale"}]
    assert loaded["notification"]["active"] is True
    assert loaded["version"] == 1


def test_missing_file_is_empty_state(tmp_path) -> None:
    """Первый запуск: файла нет — пустое состояние, без ошибки."""
    loaded = HealthStore(tmp_path / "none.json").load()

    assert loaded == empty_state()


def test_corrupted_file_is_empty_state(tmp_path) -> None:
    """Битый JSON не роняет обход: пустое состояние и предупреждение."""
    path = tmp_path / "health.json"
    path.write_text("{ not json", encoding="utf-8")

    loaded = HealthStore(path).load()

    assert loaded == empty_state()


def test_unknown_version_is_empty_state(tmp_path) -> None:
    """Чужая версия схемы не читается молча."""
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"version": 99, "problems": [{"id": "x"}]}), encoding="utf-8")

    loaded = HealthStore(path).load()

    assert loaded == empty_state()


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path) -> None:
    """После записи рядом не остаётся временных файлов."""
    path = tmp_path / "health.json"
    store = HealthStore(path)
    store.save(empty_state())

    assert path.exists()
    assert not list(tmp_path.glob(".health.json.*.tmp"))

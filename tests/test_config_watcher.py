#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

"""Тесты ConfigWatcher: жизненный цикл, детекция манифеста, reload, wiring (Q3).

ConfigWatcher подключён к приложению под env-флагом HOT_RELOAD (default OFF),
см. Known Issue #8 в .ai/01_PROJECT_STATE.md.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.config_watcher import ConfigWatcher, create_watcher, hot_reload_enabled


def _make_env(tmp_path: Path) -> dict[str, str]:
    """Создать tmp-окружение (instances + features) и вернуть пути."""
    import shutil

    instances = tmp_path / "instances"
    features = tmp_path / "features"
    (instances / "test_house").mkdir(parents=True)
    features.mkdir(parents=True)
    manifest = instances / "test_house" / "manifest.yaml"
    # Валидный манифест: копия реального (упрощённый YAML не проходит Pydantic)
    real_manifest = Path(__file__).parent.parent / "instances" / "leonids_house" / "manifest.yaml"
    shutil.copy(real_manifest, manifest)
    return {
        "manifest": str(manifest),
        "features": str(features),
        "instances": str(instances),
    }


def _make_watcher(tmp_path: Path) -> tuple[ConfigWatcher, dict[str, str]]:
    """Создать ConfigWatcher с мок-зависимостями на tmp-окружении."""
    paths = _make_env(tmp_path)
    engine = MagicMock()
    engine.get_all_states.return_value = {}
    watcher = ConfigWatcher(
        factory=MagicMock(),
        engine=engine,
        registry=MagicMock(),
        manifest_path=paths["manifest"],
        features_dir=paths["features"],
        instances_dir=paths["instances"],
    )
    return watcher, paths


class TestLifecycle:
    """Жизненный цикл start/stop."""

    def test_start_stop_lifecycle(self, tmp_path):
        watcher, _ = _make_watcher(tmp_path)
        assert not watcher.is_running
        watcher.start()
        assert watcher.is_running
        watcher.stop()
        assert not watcher.is_running

    def test_start_idempotent(self, tmp_path):
        watcher, _ = _make_watcher(tmp_path)
        watcher.start()
        watcher.start()  # повторный start — warning, не ошибка
        assert watcher.is_running
        watcher.stop()

    def test_stop_without_start_is_safe(self, tmp_path):
        watcher, _ = _make_watcher(tmp_path)
        watcher.stop()  # не должен падать (join до start)
        assert not watcher.is_running

    def test_stop_idempotent(self, tmp_path):
        watcher, _ = _make_watcher(tmp_path)
        watcher.start()
        watcher.stop()
        watcher.stop()  # повторный stop безопасен
        assert not watcher.is_running


class TestManifestDetection:
    """_is_manifest_file: абсолютные пути, чужие инстансы."""

    def test_main_manifest_matches(self, tmp_path):
        watcher, paths = _make_watcher(tmp_path)
        assert watcher._is_manifest_file(Path(paths["manifest"]))

    def test_nested_foreign_manifest_matches(self, tmp_path):
        """Чужой instances/other/manifest.yaml должен распознаваться (recursive watch)."""
        watcher, paths = _make_watcher(tmp_path)
        other = Path(paths["instances"]) / "other" / "manifest.yaml"
        assert watcher._is_manifest_file(other)

    def test_non_manifest_yaml_ignored(self, tmp_path):
        watcher, paths = _make_watcher(tmp_path)
        assert not watcher._is_manifest_file(Path(paths["instances"]) / "config.yaml")


class TestManifestReload:
    """Изменение манифеста пересоздаёт FSM через factory/engine."""

    def test_manifest_change_triggers_reload(self, tmp_path):
        watcher, paths = _make_watcher(tmp_path)
        watcher.start()
        try:
            manifest = Path(paths["manifest"])
            # debounce 0.5s + FS-event: ждём до 5с
            manifest.write_text(manifest.read_text() + "\n# touch\n")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if watcher._factory.create_from_manifest.called:
                    break
                time.sleep(0.1)
            assert watcher._factory.create_from_manifest.called, "reload манифеста не сработал"
        finally:
            watcher.stop()

    def test_reload_error_is_logged_not_raised_to_loop(self, tmp_path):
        """Ошибка reload не роняет наблюдателя (обрабатывается в _on_yaml_changed)."""
        watcher, paths = _make_watcher(tmp_path)
        watcher._factory.create_from_manifest.side_effect = RuntimeError("boom")
        watcher.start()
        try:
            manifest = Path(paths["manifest"])
            manifest.write_text(manifest.read_text() + "\n# touch2\n")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if watcher._factory.create_from_manifest.called:
                    break
                time.sleep(0.1)
            assert watcher._factory.create_from_manifest.called
            assert watcher.is_running
        finally:
            watcher.stop()


class TestWiring:
    """Env-флаг HOT_RELOAD и фабрика create_watcher."""

    def test_hot_reload_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("HOT_RELOAD", raising=False)
        assert not hot_reload_enabled()

    @pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on"])
    def test_hot_reload_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("HOT_RELOAD", value)
        assert hot_reload_enabled()

    @pytest.mark.parametrize("value", ["0", "false", "", "nope"])
    def test_hot_reload_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("HOT_RELOAD", value)
        assert not hot_reload_enabled()

    def test_create_watcher_factory(self, tmp_path):
        paths = _make_env(tmp_path)
        watcher = create_watcher(
            factory=MagicMock(),
            engine=MagicMock(),
            registry=MagicMock(),
            manifest_path=paths["manifest"],
            features_dir=paths["features"],
            instances_dir=paths["instances"],
        )
        assert isinstance(watcher, ConfigWatcher)
        assert not watcher.is_running

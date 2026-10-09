"""
Global test configuration and fixtures for Smart Home FSM Platform tests.

This module sets up:
- Python path for imports from src/
- Изоляцию каталога данных: тесты не должны писать в ./data репозитория
- Common pytest fixtures
- Mock configurations
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import os
import sys
import tempfile
from pathlib import Path

import pytest


# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Изоляция каталога данных.
#
# Без этого прогон тестов создавал в корне репозитория настоящий ./data с
# history.db, sources.json и состояниями автоматов — то есть тесты писали в
# данные разработчика. Причина в том, что хранилища создаются на уровне модуля
# (`event_store = EventStore()` в src/webui/routes/__init__.py:36), поэтому
# каталог появляется уже при ИМПОРТЕ, задолго до какой-либо фикстуры.
# Минимальное воспроизведение: `PYTHONPATH=src python -c "import webui.routes"`
# создаёт ./data.
#
# Переменная выставляется именно здесь, на этапе импорта conftest, потому что
# обычная фикстура слишком поздно: сбор тестов импортирует модули раньше, чем
# фикстуры создаются.
#
# setdefault, а не присваивание: если DATA_PATH уже задан снаружи (например,
# в CI), уважается внешнее значение.
#
# Тесты, которым нужен конкретный путь или отсутствие переменной, продолжают
# управлять ею через monkeypatch.setenv/delenv — им это не мешает.
_DATA_DIR = tempfile.TemporaryDirectory(prefix="shp-test-data-")
os.environ.setdefault("DATA_PATH", _DATA_DIR.name)


# Import from core module directly (not smart_home package)


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy for asyncio tests."""
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    from unittest.mock import MagicMock

    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.exception = MagicMock()
    return logger


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for file-based tests."""
    return tmp_path


@pytest.fixture
def sample_manifest_data():
    """Sample manifest data for testing."""
    return {
        "instance": {
            "id": "test_house",
            "name": "Test House",
            "owner": "Test Owner",
            "created_at": "2024-01-01",
        },
        "version": 1,
        "devices": [
            {
                "type": "light_motion",
                "id": "light.kitchen",
                "name": "Kitchen Light",
                "room": "kitchen",
                "behaviors": [
                    {
                        "template": "lighting",
                        "priority": 10,
                        "params": {
                            "motion_sensor": "binary_sensor.kitchen_motion",
                            "motion_timeout_sec": 180,
                            "brightness": 255,
                        },
                    }
                ],
            }
        ],
        "automation_rules": {
            "global_manual_lockout_min": 60,
            "lighting": {
                "motion_enabled": True,
                "schedule_enabled": True,
                "manual_lockout_min": 60,
            },
        },
    }


@pytest.fixture(scope="session")
def browser_context_args():
    """Configure browser context arguments for Playwright."""
    return {
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720},
    }


# Фикстура `webui_server` удалена 2026-10-03 (BACKLOG B10).
#
# Она была `autouse=True`, то есть запускалась на каждой pytest-сессии, при этом:
#   - не была запрошена ни одним тестом;
#   - поднимала процесс на ASGI-цели `src.webui.app:app`, которой в модуле нет
#     (модульный `app` объявлен только в `src/main.py`), поэтому процесс всегда
#     падал с кодом 3;
#   - ждала готовности порта 15 секунд, игнорируя результат.
#
# Итог: ~15 секунд напрасного ожидания и мёртвый процесс на каждый прогон.
# Рабочий вариант для E2E — собственная фикстура `start_webui_server` в
# `tests/test_webui_playwright.py` на фабрике `tests.e2e_app:create_e2e_app`.

#: Путь файла → метка блока. Расставляется автоматически, чтобы блоковые метки
#: не приходилось проставлять в сотнях проверок вручную и чтобы они не
#: разъезжались с реальной структурой тестов.
_BLOCK_MARKERS: tuple[tuple[str, str], ...] = (
    ("/tests/unit/core/", "core"),
    ("/tests/unit/webui/", "webui"),
    ("/tests/contract/", "webui"),
    ("/tests/integration/", "core"),
)

#: Слово в имени проверки или модуля → метка блока.
_KEYWORD_MARKERS: tuple[tuple[str, str], ...] = (
    ("adapter", "adapter"),
    ("ha_", "adapter"),
    ("websocket", "adapter"),
    ("lighting", "lighting"),
    ("night_protection", "lighting"),
    ("humidity", "lighting"),
    ("ventilation", "lighting"),
    ("schedule", "lighting"),
    ("manifest", "manifest"),
    ("discovery", "manifest"),
    ("device_lifecycle", "manifest"),
    ("webui", "webui"),
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Разметить проверки метками блоков по пути файла и имени.

    Args:
        config: Конфигурация pytest (не используется).
        items: Собранные проверки.
    """
    del config  # метки выводятся из пути и имён, а не из настроек
    for item in items:
        path = str(getattr(item, "fspath", "")).replace("\\", "/")
        for fragment, marker in _BLOCK_MARKERS:
            if fragment in path:
                item.add_marker(marker)
        module = getattr(getattr(item, "module", None), "__name__", "")
        haystack = f"{item.name} {module}".lower()
        for keyword, marker in _KEYWORD_MARKERS:
            if keyword in haystack:
                item.add_marker(marker)

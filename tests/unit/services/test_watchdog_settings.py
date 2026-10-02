"""
Тесты чтения настроек сторожа (FR-019, FR-024, R-07).

Настройки приходят из переменных окружения по образцу работающего
``hot_reload_enabled()``. Некорректное значение не должно ронять старт
платформы: вместо него используется безопасное значение по умолчанию.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from services.watchdog import (
    DEFAULT_HA_LOSS_SEC,
    DEFAULT_INTERVAL_SEC,
    DEFAULT_STUCK_GRACE_SEC,
    watchdog_enabled,
    watchdog_ha_loss_sec,
    watchdog_interval_sec,
    watchdog_settings,
    watchdog_stuck_grace_sec,
)


WATCHDOG_ENV_VARS = (
    "WATCHDOG_ENABLED",
    "WATCHDOG_INTERVAL_SEC",
    "WATCHDOG_STUCK_GRACE_SEC",
    "WATCHDOG_HA_LOSS_SEC",
)


@contextmanager
def watchdog_env(**values: str) -> Iterator[None]:
    """Подменить переменные окружения сторожа, очистив остальные."""
    import os

    saved = {name: os.environ.pop(name, None) for name in WATCHDOG_ENV_VARS}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestWatchdogEnabled:
    """Проверки включения сторожа."""

    def test_should_be_enabled_by_default(self) -> None:
        """Сторож включается по умолчанию (FR-019)."""
        with watchdog_env():
            assert watchdog_enabled() is True

    @pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE"])
    def test_should_be_enabled_when_env_is_truthy(self, raw: str) -> None:
        """Истинное значение оставляет сторож включённым."""
        with watchdog_env(WATCHDOG_ENABLED=raw):
            assert watchdog_enabled() is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off"])
    def test_should_be_disabled_when_env_is_falsey(self, raw: str) -> None:
        """Явное выключение должно уважаться."""
        with watchdog_env(WATCHDOG_ENABLED=raw):
            assert watchdog_enabled() is False


class TestWatchdogInterval:
    """Проверки интервала проверок."""

    def test_should_return_default_when_env_absent(self) -> None:
        """Значение по умолчанию — 60 секунд."""
        with watchdog_env():
            assert watchdog_interval_sec() == DEFAULT_INTERVAL_SEC == 60

    def test_should_return_env_value_when_valid(self) -> None:
        """Корректное значение из окружения используется как есть."""
        with watchdog_env(WATCHDOG_INTERVAL_SEC="10"):
            assert watchdog_interval_sec() == 10.0

    @pytest.mark.parametrize("raw", ["0", "-5"])
    def test_should_fall_back_to_default_when_not_positive(self, raw: str) -> None:
        """Ноль и отрицательное значение дали бы бесконечный цикл."""
        with watchdog_env(WATCHDOG_INTERVAL_SEC=raw):
            assert watchdog_interval_sec() == DEFAULT_INTERVAL_SEC

    @pytest.mark.parametrize("raw", ["abc", "", "1.5.5"])
    def test_should_fall_back_to_default_when_not_a_number(self, raw: str) -> None:
        """Нечисловое значение не должно ронять старт платформы."""
        with watchdog_env(WATCHDOG_INTERVAL_SEC=raw):
            assert watchdog_interval_sec() == DEFAULT_INTERVAL_SEC


class TestWatchdogThresholds:
    """Проверки порогов зависания и потери связи."""

    def test_should_return_default_grace_when_env_absent(self) -> None:
        """Запас на зависание по умолчанию — 30 секунд."""
        with watchdog_env():
            assert watchdog_stuck_grace_sec() == DEFAULT_STUCK_GRACE_SEC == 30

    def test_should_return_default_ha_loss_when_env_absent(self) -> None:
        """Порог потери связи по умолчанию — 300 секунд."""
        with watchdog_env():
            assert watchdog_ha_loss_sec() == DEFAULT_HA_LOSS_SEC == 300

    def test_should_return_env_values_when_valid(self) -> None:
        """Корректные пороги из окружения используются как есть."""
        with watchdog_env(WATCHDOG_STUCK_GRACE_SEC="5", WATCHDOG_HA_LOSS_SEC="45"):
            assert watchdog_stuck_grace_sec() == 5.0
            assert watchdog_ha_loss_sec() == 45.0

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("0", DEFAULT_STUCK_GRACE_SEC), ("-1", DEFAULT_STUCK_GRACE_SEC), ("oops", 30)],
    )
    def test_should_fall_back_to_default_grace_when_invalid(
        self, raw: str, expected: float
    ) -> None:
        """Некорректный запас заменяется значением по умолчанию."""
        with watchdog_env(WATCHDOG_STUCK_GRACE_SEC=raw):
            assert watchdog_stuck_grace_sec() == expected

    @pytest.mark.parametrize("raw", ["0", "-10", "nope"])
    def test_should_fall_back_to_default_ha_loss_when_invalid(self, raw: str) -> None:
        """Некорректный порог потери связи заменяется значением по умолчанию."""
        with watchdog_env(WATCHDOG_HA_LOSS_SEC=raw):
            assert watchdog_ha_loss_sec() == DEFAULT_HA_LOSS_SEC


class TestWatchdogSettingsBundle:
    """Проверки агрегированного объекта настроек."""

    def test_should_bundle_all_settings_when_collected(self) -> None:
        """Объект настроек собирает все значения в одном месте."""
        with watchdog_env(WATCHDOG_INTERVAL_SEC="15", WATCHDOG_STUCK_GRACE_SEC="7"):
            settings = watchdog_settings()

        assert settings.interval_sec == 15.0
        assert settings.stuck_grace_sec == 7.0
        assert settings.ha_loss_sec == DEFAULT_HA_LOSS_SEC
        assert settings.enabled is True

    def should_use_defaults_when_environment_is_empty(self) -> None:
        """Без окружения настройки равны значениям по умолчанию."""
        with watchdog_env():
            settings = watchdog_settings()

        assert settings.interval_sec == DEFAULT_INTERVAL_SEC
        assert settings.stuck_grace_sec == DEFAULT_STUCK_GRACE_SEC
        assert settings.ha_loss_sec == DEFAULT_HA_LOSS_SEC
        assert settings.enabled is True

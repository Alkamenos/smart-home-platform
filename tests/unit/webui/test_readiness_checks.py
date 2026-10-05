"""Проверка свежести сторожа обязана отличать «работает» от «молчит».

Дополнение к K6. Проверка готовности читает `watchdog._last_snapshot`, поэтому
нужно доказать две вещи:

1. сторож действительно сохраняет снимок — иначе проверка всегда сообщала бы
   «ни одного снимка» и была бы такой же бесполезной, как прежний `/health`;
2. проверка честно различает свежий снимок, устаревший, неудачный и
   отсутствующий.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from services.watchdog import FsmSnapshot, WatchdogService, WatchdogSettings
from webui.routes import readiness


class _Engine:
    """Минимальный движок: один автомат в состоянии."""

    def get_all_states(self) -> dict[str, Any]:
        from core.fsm.state import State

        return {"light.test": State("ON", {})}

    def expected_timeout_sec(self, entity_id: str) -> float | None:
        return None

    def device_id_of(self, entity_id: str) -> str | None:
        return "light.test"

    def get_last_transition_time(self, entity_id: str) -> str | None:
        return None


class _Container:
    """Контейнер с подменяемым сторожем."""

    def __init__(self, watchdog: Any) -> None:
        self._watchdog = watchdog


def _watchdog() -> WatchdogService:
    return WatchdogService(
        fsm_engine=_Engine(),
        metrics=None,
        adapter=None,
        settings=WatchdogSettings(enabled=False),
        event_bus=None,
    )


def _snapshot(taken_at: datetime, *, failed: bool = False, problems: int = 0) -> FsmSnapshot:
    return FsmSnapshot(
        taken_at=taken_at.replace(tzinfo=None).isoformat(timespec="seconds"),
        entries=(),
        problem_count=problems,
        failed=failed,
    )


class TestWatchdogKeepsLastSnapshot:
    """Сторож обязан сохранять снимок, иначе проверять нечего."""

    def test_snapshot_is_kept_after_check(self) -> None:
        """После проверки снимок сохранён."""
        watchdog = _watchdog()

        assert watchdog._last_snapshot is None
        asyncio.run(watchdog.check_once())
        assert watchdog._last_snapshot is not None, (
            "сторож не сохранил снимок: проверка готовности не сможет судить о его свежести"
        )

    def test_snapshot_is_kept_even_when_check_fails(self) -> None:
        """Снимок сохраняется и при сбое проверки.

        Иначе сбой сторожа выглядел бы как «сторож ещё не работал», и отличить
        «не запускался» от «упал» было бы невозможно.
        """

        class Exploding(_Engine):
            def get_all_states(self) -> dict[str, Any]:
                raise RuntimeError("хранилище недоступно")

        watchdog = WatchdogService(
            fsm_engine=Exploding(),
            metrics=None,
            adapter=None,
            settings=WatchdogSettings(enabled=False),
            event_bus=None,
        )

        snapshot = asyncio.run(watchdog.check_once())

        assert snapshot.failed is True
        assert watchdog._last_snapshot is not None, (
            "неуспешный снимок не сохранён — сбой сторожа неотличим от простоя"
        )


class TestWatchdogFreshnessCheck:
    """Проверка свежести различает четыре состояния."""

    def test_fresh_snapshot_is_ok(self) -> None:
        """Свежий успешный снимок — готовность есть."""
        watchdog = _watchdog()
        watchdog._last_snapshot = _snapshot(datetime.now(UTC))

        result = readiness.check_watchdog(_Container(watchdog), stale_sec=180)

        assert result["ok"] is True, f"свежий снимок отвергнут: {result}"
        assert result["age_sec"] is not None and result["age_sec"] < 180

    def test_stale_snapshot_is_not_ok(self) -> None:
        """Устаревший снимок — отказ: сторож перестал работать."""
        watchdog = _watchdog()
        watchdog._last_snapshot = _snapshot(datetime.now(UTC) - timedelta(seconds=600))

        result = readiness.check_watchdog(_Container(watchdog), stale_sec=180)

        assert result["ok"] is False, f"снимок шестиминутной давности принят за свежий: {result}"
        assert "устарел" in result["detail"]

    def test_failed_check_is_not_ok(self) -> None:
        """Свежий, но неуспешный снимок — отказ.

        Формально снимок только что получен, но он не содержит достоверных
        состояний: считать такой сторож работающим нельзя.
        """
        watchdog = _watchdog()
        watchdog._last_snapshot = _snapshot(datetime.now(UTC), failed=True)

        result = readiness.check_watchdog(_Container(watchdog), stale_sec=180)

        assert result["ok"] is False, f"неуспешная проверка принята за успешную: {result}"

    def test_missing_snapshot_is_not_ok(self) -> None:
        """Снимка нет вовсе — отказ с понятной причиной."""
        watchdog = _watchdog()

        result = readiness.check_watchdog(_Container(watchdog), stale_sec=180)

        assert result["ok"] is False
        assert "ни одного снимка" in result["detail"]

    def test_absent_watchdog_is_not_ok(self) -> None:
        """Сторожа нет — отказ."""
        result = readiness.check_watchdog(_Container(None), stale_sec=180)

        assert result["ok"] is False
        assert "сторож" in result["detail"]

    def test_problem_count_is_reported(self) -> None:
        """Число зависаний попадает в отчёт.

        Оно не делает платформу «неготовой»: зависший автомат — это наблюдаемое
        состояние, а не отказ зависимости. Но оператор должен видеть число.
        """
        watchdog = _watchdog()
        watchdog._last_snapshot = _snapshot(datetime.now(UTC), problems=3)

        result = readiness.check_watchdog(_Container(watchdog), stale_sec=180)

        assert result["ok"] is True, f"зависания не должны ломать готовность: {result}"
        assert result["problems"] == 3, f"число зависаний не сообщено: {result}"


class TestHomeAssistantCheck:
    """Проверка связи не должна зависеть от наличия адаптера."""

    def test_absent_adapter_is_not_ok(self) -> None:
        """Адаптера нет — отказ, а не «связь есть»."""
        result = readiness.check_home_assistant(None)

        assert result["ok"] is False

    def test_connected_adapter_is_ok(self) -> None:
        class Adapter:
            is_connected = True

        assert readiness.check_home_assistant(Adapter())["ok"] is True

    def test_disconnected_adapter_is_not_ok(self) -> None:
        class Adapter:
            is_connected = False

        assert readiness.check_home_assistant(Adapter())["ok"] is False

    def test_adapter_raising_is_reported_not_crashed(self) -> None:
        """Ошибка при обращении к адаптеру попадает в отчёт.

        Проверка обязана быть устойчивой: исключение здесь означало бы 500 вместо
        диагностического ответа.
        """

        class Broken:
            @property
            def is_connected(self) -> bool:
                raise RuntimeError("соединение сброшено")

        result = readiness.check_home_assistant(Broken())

        assert result["ok"] is False
        assert "сброшено" in result["detail"], f"причина потеряна: {result}"


class TestChecksAreIndependent:
    """Отказ одной проверки не скрывает остальные."""

    def test_all_checks_present_even_when_some_fail(self) -> None:
        """Собираются все проверки, независимо от результатов."""
        from fastapi.testclient import TestClient

        from main import app

        response = TestClient(app).get("/ready")
        checks = response.json()["checks"]

        assert set(checks) == {
            "data_dir",
            "encryption_key",
            "home_assistant",
            "watchdog",
            "fsm_engine",
        }, f"набор проверок неполон: {list(checks)}"

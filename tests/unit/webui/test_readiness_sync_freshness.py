"""Возраст синхронизации источника — часть готовности, а не строчка в журнале.

Синхронизация запускается только вручную: `POST /api/v1/devices/sources/{id}/sync`.
Ничего по расписанию её не зовёт, поэтому дата последней синхронизации не растёт
сама и не выглядит поломкой — её просто никто не запускает. При этом `/ready`
о ней молчал: шесть проверок готовности не включали источники вовсе.

Чем это опасно
--------------

Оператор видит исправную систему: `/ready` отвечает `ready: true`, список
устройств наполнен, а данные в нём — на момент последнего ручного нажатия.
Устройство, появившееся или исчезнувшее за это время, платформа не знает, и
исправить это можно, только посмотрев в журнал. Ровно тот случай, который в
#77 закрывался для режима развёртывания: молчание выглядит как исправность.

Что проверяется
---------------

1. Источник, синхронизированный недавно, готов.
2. Источник старше порога — не готов, с именем и возрастом в ответе.
3. Источник, ни разу не синхронизированный, — не готов: данных нет вовсе, и
   «дата отсутствует» не то же самое, что «дата свежая».
4. Отсутствие источников — не отказ: синхронизировать нечего.
5. Каждый источник проверяется сам: один протухший не скрывает остальные.
6. Порог задаётся переменной окружения; испорченное значение не роняет
   проверку и не превращает её в вечно зелёную.
7. Проверка входит в сводку `/ready`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from webui.routes import readiness


class _Sources:
    """Хранилище источников с заданным списком."""

    def __init__(self, items: list[Any]) -> None:
        """Создать хранилище.

        Args:
            items: Источники, которые вернёт чтение.
        """
        self._items = items

    async def load_all_sources(self) -> list[Any]:
        """Вернуть заданные источники.

        Returns:
            Список источников.
        """
        return list(self._items)


class _Persistence:
    """Персистентность, у которой есть только хранилище источников."""

    def __init__(self, sources: Any) -> None:
        """Создать персистентность.

        Args:
            sources: Хранилище источников либо ``None``.
        """
        self.sources = sources


class _Source:
    """Источник Home Assistant с нужными для проверки полями."""

    def __init__(
        self,
        name: str = "Дом",
        last_sync: datetime | str | None = None,
        status: str = "connected",
    ) -> None:
        """Создать источник.

        Args:
            name: Имя источника.
            last_sync: Время последней успешной синхронизации.
            status: Канонический статус источника.
        """
        self.name = name
        self.last_sync = last_sync
        self.status = status


class _RequestWithSources:
    """Запрос с персистентностью в состоянии приложения."""

    def __init__(self, persistence: Any) -> None:
        """Создать запрос.

        Args:
            persistence: Персистентность платформы.
        """
        state = type("_State", (), {"container": None, "persistence": persistence})()
        self.app = type("_App", (), {"state": state})()


def _ago(seconds: float) -> datetime:
    """Время, отстоящее от now назад.

    Args:
        seconds: Сколько секунд назад.

    Returns:
        Наивное время UTC — так метку хранит модель источника.
    """
    return (datetime.now(UTC) - timedelta(seconds=seconds)).replace(tzinfo=None)


def _persistence(*items: Any) -> _Persistence:
    """Персистентность с указанными источниками.

    Args:
        *items: Источники.

    Returns:
        Персистентность с хранилищем источников.
    """
    return _Persistence(_Sources(list(items)))


class TestFreshSourceIsReady:
    """Недавно синхронизированный источник — готов."""

    @pytest.mark.asyncio
    async def test_recent_sync_is_ok(self) -> None:
        """Свежая синхронизация не мешает готовности."""
        result = await readiness.check_source_sync(_persistence(_Source(last_sync=_ago(60))))

        assert result["ok"] is True, f"свежая синхронизация объявлена проблемой: {result}"

    @pytest.mark.asyncio
    async def test_age_is_reported(self) -> None:
        """В ответе виден возраст данных, а не только признак.

        Оператору нужно знать, насколько устарело то, что он видит.
        """
        result = await readiness.check_source_sync(_persistence(_Source(last_sync=_ago(120))))

        assert result["oldest_age_sec"] is not None
        assert 100 < float(result["oldest_age_sec"]) <= 130, (
            f"возраст данных не назван или посчитан неверно: {result}"
        )

    @pytest.mark.asyncio
    async def test_no_sources_is_not_a_failure(self) -> None:
        """Нет источников — синхронизировать нечего, и это не отказ."""
        result = await readiness.check_source_sync(_persistence())

        assert result["ok"] is True, f"пустой список источников объявлен отказом: {result}"
        assert result["sources"] == 0


class TestStaleSourceIsNotReady:
    """Протухшая синхронизация должна быть видна."""

    @pytest.mark.asyncio
    async def test_old_sync_is_reported_as_stale(self) -> None:
        """Данные старше порога означают, что список устройств может врать."""
        result = await readiness.check_source_sync(
            _persistence(_Source(last_sync=_ago(readiness.SYNC_STALE_SEC + 600))),
            stale_sec=float(readiness.SYNC_STALE_SEC),
        )

        assert result["ok"] is False, (
            f"/ready сообщил готовность при протухших данных: {result}. Список "
            f"устройств показывает состояние на момент давнего нажатия, и "
            f"оператор об этом не узнаёт"
        )

    @pytest.mark.asyncio
    async def test_stale_source_is_named(self) -> None:
        """В ответе названы имя источника и возраст его данных."""
        result = await readiness.check_source_sync(
            _persistence(_Source(name="Дом", last_sync=_ago(90_000))),
            stale_sec=float(readiness.SYNC_STALE_SEC),
        )

        assert result["stale"], f"протухший источник не назван: {result}"
        entry = result["stale"][0]
        assert entry["name"] == "Дом", f"имя источника потеряно: {result}"
        assert float(entry["age_sec"]) > 89_000, f"возраст протухшего не назван: {result}"

    @pytest.mark.asyncio
    async def test_never_synced_is_not_ok(self) -> None:
        """Источник без единой синхронизации — данных нет вовсе."""
        result = await readiness.check_source_sync(_persistence(_Source(last_sync=None)))

        assert result["ok"] is False, (
            f"источник без синхронизации объявлен готовым: {result}. Отсутствие "
            f"даты — это не свежая дата, а отсутствие данных"
        )

    @pytest.mark.asyncio
    async def test_never_synced_is_distinguishable_from_old(self) -> None:
        """Причины протухания различаются в ответе.

        «Ни разу не синхронизирован» и «давно не синхронизирован» требуют
        разных действий оператора, и сливать их в одну фразу нельзя.
        """
        never = await readiness.check_source_sync(_persistence(_Source(last_sync=None)))
        old = await readiness.check_source_sync(
            _persistence(_Source(last_sync=_ago(90_000))),
            stale_sec=float(readiness.SYNC_STALE_SEC),
        )

        assert never["detail"] != old["detail"], (
            f"причины протухания неразличимы: {never['detail']!r} и {old['detail']!r}"
        )

    @pytest.mark.asyncio
    async def test_iso_string_last_sync_is_parsed(self) -> None:
        """Время, пришедшее строкой, тоже считается.

        Источник читается из JSON-хранилища, где метка может остаться строкой;
        молча счёл бы «нет даты» там, где дата есть.
        """
        result = await readiness.check_source_sync(
            _persistence(_Source(last_sync=_ago(90_000).isoformat())),
            stale_sec=float(readiness.SYNC_STALE_SEC),
        )

        assert result["oldest_age_sec"] is not None, (
            f"строка с датой не разобрана, источник объявлен не синхронизированным: {result}"
        )
        assert result["ok"] is False, f"протухшая строкаовая дата сочтена свежей: {result}"

    @pytest.mark.asyncio
    async def test_unparsable_date_is_reported_not_hidden(self) -> None:
        """Непонятная дата — это отказ с правдой, а не «свежо»."""
        result = await readiness.check_source_sync(_persistence(_Source(last_sync="не дата")))

        assert result["ok"] is False, f"нераспознанная дата сочтена свежей: {result}"
        assert "не разобрана" in result["detail"], f"причина не названа: {result}"


class TestEachSourceCheckedSeparately:
    """Один протухший источник не должен прятать состояние остальных."""

    @pytest.mark.asyncio
    async def test_one_stale_source_fails_but_others_are_named(self) -> None:
        """В ответе видно и то, что протухло, и что в порядке."""
        result = await readiness.check_source_sync(
            _persistence(
                _Source(name="Дом", last_sync=_ago(60)),
                _Source(name="Дом на даче", last_sync=_ago(90_000)),
            ),
            stale_sec=float(readiness.SYNC_STALE_SEC),
        )

        assert result["ok"] is False, f"протухший источник не помечен: {result}"
        assert [entry["name"] for entry in result["stale"]] == ["Дом на даче"], (
            f"в списке протухших лишние источники: {result}"
        )
        assert result["sources"] == 2, f"посчитаны не все источники: {result}"

    @pytest.mark.asyncio
    async def test_all_fresh_sources_are_ready(self) -> None:
        """Все свежие источники — готовность прежняя."""
        result = await readiness.check_source_sync(
            _persistence(
                _Source(name="Дом", last_sync=_ago(60)),
                _Source(name="Дом на даче", last_sync=_ago(120)),
            )
        )

        assert result["ok"] is True, f"свежие источники объявлены протухшими: {result}"

    @pytest.mark.asyncio
    async def test_disconnected_source_is_named_separately(self) -> None:
        """Отключённый источник виден, даже когда данные свежие.

        Связь с Home Assistant проверяется отдельно, но «последний раз данные
        пришли вовремя» и «источник сейчас отключён» — разные факты, и
        подменять один другим нельзя.
        """
        result = await readiness.check_source_sync(
            _persistence(_Source(last_sync=_ago(60), status="disconnected"))
        )

        assert result["not_connected"] == ["Дом"], f"отключённый источник не назван: {result}"


class TestThreshold:
    """Порог задаётся настройкой, а не зашит."""

    def test_env_var_changes_threshold(self, monkeypatch: Any) -> None:
        """Переменная окружения меняет порог."""
        monkeypatch.setenv("SYNC_STALE_SEC", "3600")

        assert readiness.sync_stale_sec() == 3600.0

    @pytest.mark.asyncio
    async def test_env_var_applies_to_check(self, monkeypatch: Any) -> None:
        """Порог из окружения действительно применяется к проверке."""
        monkeypatch.setenv("SYNC_STALE_SEC", "3600")

        result = await readiness.check_source_sync(_persistence(_Source(last_sync=_ago(7200))))

        assert result["stale_after_sec"] == 3600.0
        assert result["ok"] is False

    def test_broken_value_falls_back_to_default(self, monkeypatch: Any) -> None:
        """Испорченная настройка не превращает проверку в вечно зелёную."""
        monkeypatch.setenv("SYNC_STALE_SEC", "не число")

        assert readiness.sync_stale_sec() == float(readiness.SYNC_STALE_SEC), (
            "испорченное значение должно заменяться значением по умолчанию, "
            "иначе проверка молча перестаёт что-либо проверять"
        )

    def test_zero_is_rejected(self, monkeypatch: Any) -> None:
        """Нулевой порог означал бы «устарело всё, включая только что свежее»."""
        monkeypatch.setenv("SYNC_STALE_SEC", "0")

        assert readiness.sync_stale_sec() == float(readiness.SYNC_STALE_SEC)

    def test_default_threshold_used_without_env(self, monkeypatch: Any) -> None:
        """Без переменной окружения действует значение по умолчанию."""
        monkeypatch.delenv("SYNC_STALE_SEC", raising=False)

        assert readiness.sync_stale_sec() == float(readiness.SYNC_STALE_SEC)


class TestUnreadableStorage:
    """Отсутствие хранилища источников — это отказ, а не «всё хорошо»."""

    @pytest.mark.asyncio
    async def test_missing_persistence_is_reported(self) -> None:
        """Нет персистентности — нечего проверять, и это видно."""
        result = await readiness.check_source_sync(None)

        assert result["ok"] is False, f"отсутствие хранилища скрыто: {result}"

    @pytest.mark.asyncio
    async def test_storage_without_sources_is_reported(self) -> None:
        """Персистентность без хранилища источников — тоже отсутствие данных."""
        result = await readiness.check_source_sync(_Persistence(None))

        assert result["ok"] is False, (
            f"хранилище источников не найдено, а проверка молчит: {result}"
        )

    @pytest.mark.asyncio
    async def test_broken_storage_is_reported_not_raised(self) -> None:
        """Ошибка чтения попадает в отчёт, а не поднимается наружу.

        Иначе `/ready` отвечал бы 500 вместо диагностического ответа.
        """

        class Broken:
            @property
            def sources(self) -> Any:
                raise RuntimeError("файл источников повреждён")

        result = await readiness.check_source_sync(Broken())

        assert result["ok"] is False
        assert "повреждён" in result["detail"], f"причина потеряна: {result}"

    @pytest.mark.asyncio
    async def test_read_failure_is_reported_not_raised(self) -> None:
        """Ошибка чтения списка источников не поднимается наружу."""

        class BrokenSources:
            async def load_all_sources(self) -> list[Any]:
                raise RuntimeError("файл недоступен")

        result = await readiness.check_source_sync(_Persistence(BrokenSources()))

        assert result["ok"] is False
        assert "недоступен" in result["detail"], f"причина потеряна: {result}"


class TestSummaryIncludesTheCheck:
    """Проверка входит в сводку `/ready`."""

    @pytest.mark.asyncio
    async def test_collect_checks_contains_source_sync(self) -> None:
        """Проверка, которую никто не зовёт, не защищает ни от чего."""
        request = _RequestWithSources(_persistence(_Source(last_sync=_ago(60))))

        checks = await readiness.collect_checks(request)

        assert "source_sync" in checks, f"проверки источников нет в сводке: {sorted(checks)}"
        assert checks["source_sync"]["ok"] is True

    @pytest.mark.asyncio
    async def test_collect_checks_survives_request_without_persistence(self) -> None:
        """Запрос без персистентности не роняет сводку целиком.

        Сводка собирает все проверки сразу; одна из них, не имея данных, не должна
        мешать увидеть остальные.
        """
        request = _RequestWithSources(None)

        checks = await readiness.collect_checks(request)

        assert len(checks) >= 7, f"сводка потеряла проверки: {sorted(checks)}"
        assert "source_sync" in checks

"""Мусор в накопленном контексте: параметр, убранный из манифеста, не должен жить вечно.

Боевой дефект 2026-10-12: конвектор гостиной не включался никогда, при любой
уставке. Журнал и метрики показывали отказ ``managed_by_hardware`` — а в
манифесте этого параметра нет (владелец убрал его 2026-10-10, конвектор
перевели под общие правила обогрева).

Причина в том, как движок собирает контекст:

    merged_context = {**current_state.context}

Контекст **накопительный**: он переживает каждый переход, а параметры
поведения лишь дополняют его (``update``). Флаг, записанный в ``state.json``
старым манифестом, читался при каждом показании датчика и обрекал комнату на
отказ — убери параметр из манифеста, а в состоянии он останется навсегда.

Правило: параметры принадлежат манифесту, а не состоянию. Если ключ есть в
накопленном контексте, но отсутствует в параметрах поведения и входит в
известный набор параметров — он устарел и вычищается при следующем же
переходе. Чистка при чтении, а не правкой файла руками: иначе тот же мусор
появится при следующем горячем обновлении манифеста.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from core.fsm.engine import KNOWN_BEHAVIOR_PARAM_KEYS, FSMEngine, sanitise_stale_params


class TestStaleParamsAreCleaned:
    """Устаревший параметр уходит, оставшиеся — остаются."""

    def test_stale_param_is_removed(self) -> None:
        """Параметр из старого манифеста удаляется при мерже.

        Returns:
            Ничего.
        """
        context = {"managed_by_hardware": True, "hysteresis": 0.5, "run_minutes": 15}
        params = {"hysteresis": 0.5, "run_minutes": 15}

        cleaned = sanitise_stale_params(context, params)

        assert "managed_by_hardware" not in cleaned, (
            "параметр, убранный из манифеста, остался в контексте: конвектор "
            "гостиной отказывал по managed_by_hardware при любой уставке — "
            "боевой дефект 2026-10-12"
        )

    def test_params_of_this_behavior_survive(self) -> None:
        """Параметры текущего поведения не удаляются.

        Returns:
            Ничего.
        """
        context = {"hysteresis": 0.5, "run_minutes": 15}
        params = {"hysteresis": 0.5, "run_minutes": 15}

        cleaned = sanitise_stale_params(context, params)

        assert cleaned["hysteresis"] == 0.5
        assert cleaned["run_minutes"] == 15

    def test_event_values_are_kept(self) -> None:
        """Значения события — не параметры, им остааваться.

        Returns:
            Ничего.
        """
        context = {
            "climate_setpoint": 30.0,
            "daylight": True,
            "room": "gostinaia",
            "managed_by_hardware": True,
        }

        cleaned = sanitise_stale_params(context, {})

        assert cleaned["climate_setpoint"] == 30.0
        assert cleaned["daylight"] is True
        assert cleaned["room"] == "gostinaia"
        assert "managed_by_hardware" not in cleaned

    def test_unknown_new_keys_are_kept(self) -> None:
        """Чужих ключей не трогаем: чистить можно только известное.

        Контекст наполняют и события, и действия; белый список оператор —
        быстрый способ сломать чужое поведение.

        Returns:
            Ничего.
        """
        context = {"some_future_key": 1}

        cleaned = sanitise_stale_params(context, {})

        assert cleaned["some_future_key"] == 1

    def test_managed_by_hardware_is_in_known_set(self) -> None:
        """Ключ входит в известный набор — иначе чистка его не найдёт.

        Returns:
            Ничего.
        """
        assert "managed_by_hardware" in KNOWN_BEHAVIOR_PARAM_KEYS

    def test_engine_uses_sanitiser(self) -> None:
        """Движок вычищает устаревшее при сборке контекста перехода.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        # Прямая проверка интеграции: метод вычищает мусор перед мержем параметров.
        context = {"managed_by_hardware": True, "x": 1}
        cleaned = engine.sanitise_for_merge(context, {"x": 1})
        assert "managed_by_hardware" not in cleaned
        assert cleaned["x"] == 1


def test_known_set_covers_manifest_params() -> None:
    """Известный набор покрывает все параметры доступных манифестов.

    Если владелец добавит новый параметр и забудет внести его в набор, чистка
    не найдёт его же старую версию — проверка обязана падать на таком шаге,
    а не ловить в доме уже кривой откат.

    Проверяются все манифесты репозитория плюс боевой, если он есть на этой
    машине (боевой том в git не хранится). Раньше проверка требовала боевой том
    и падала у того, кто поднимал платформу впервые (переносимость, BACKLOG B78).

    Returns:
        Ничего.
    """
    import pathlib

    import yaml

    candidates = sorted(pathlib.Path("instances").glob("*/manifest.yaml"))
    live = pathlib.Path("deploy/docker/config/manifest.yaml")
    if live.exists():
        candidates.append(live)

    assert candidates, "не найдено ни одного манифеста для проверки"

    for manifest_path in candidates:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        for room in manifest.get("rooms", []):
            for device in room.get("devices", []):
                for behavior in device.get("behaviors", []):
                    for key in behavior.get("params", {}):
                        assert key in KNOWN_BEHAVIOR_PARAM_KEYS, (
                            f"параметр {key!r} из {manifest_path} есть в манифесте, "
                            "но нет в KNOWN_BEHAVIOR_PARAM_KEYS: его старая версия "
                            "не будет вычищена из состояния — тот же баг, что с гостиной"
                        )

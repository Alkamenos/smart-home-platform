"""Действия штор: открыть и закрыть (спека 015).

Данные команды пусты: ``cover.open_cover`` и ``cover.close_cover`` параметров не
принимают, а лишний ключ Home Assistant отвергает с 400 Bad Request — та же
дисциплина, что и у вентилятора (research.md D23). В контексте перехода при этом
могут лежать чужие поля (например, ``percentage`` от прежнего состояния шторы
или другой автоматики), и они не должны попасть в команду.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS


def _action(name: str) -> Any:
    """Взять действие по имени из реестра.

    Args:
        name: Имя действия.

    Returns:
        Функция ``(state, context) -> CommandIntent | None``.

    Raises:
        AssertionError: действия нет в реестре — шаблон его не найдёт.
    """
    assert name in ACTION_HANDLERS, (
        f"действие `{name}` не зарегистрировано: {sorted(ACTION_HANDLERS)}"
    )
    return ACTION_HANDLERS[name]


class TestCoverActions:
    """Команды штор: домен, услуга и пустые данные."""

    def test_open_cover_sends_open_service_without_data(self) -> None:
        """Открытие: домен ``cover``, услуга ``open_cover``, данных нет."""
        intent = _action("cover_open")(None, {"entity_id": "cover.shtora_v_spalne"})

        assert intent is not None
        assert (intent.domain, intent.service) == ("cover", "open_cover")
        assert intent.data == {}, f"в команду открытия ушло {intent.data!r}: лишний ключ → 400"

    def test_close_cover_sends_close_service_without_data(self) -> None:
        """Закрытие: домен ``cover``, услуга ``close_cover``, данных нет."""
        intent = _action("cover_close")(None, {"entity_id": "cover.shtora_v_spalne"})

        assert intent is not None
        assert (intent.domain, intent.service) == ("cover", "close_cover")
        assert intent.data == {}

    def test_commands_ignore_stale_context_fields(self) -> None:
        """Чужие поля контекста в команду не попадают.

        Контекст перехода накопительный: в нём могут лежать ``percentage`` и
        ``preset_mode`` от другой автоматики. Их место только у вентилятора.
        """
        stale = {
            "entity_id": "cover.shtora_v_gostinnoi_pravaia",
            "percentage": 100,
            "preset_mode": "Приток MAX",
        }

        assert _action("cover_open")(None, dict(stale)).data == {}
        assert _action("cover_close")(None, dict(stale)).data == {}

    def test_actions_without_entity_are_silent(self) -> None:
        """Нет устройства — команды нет, но и выдумки нет."""
        assert _action("cover_open")(None, {}) is None
        assert _action("cover_close")(None, {}) is None

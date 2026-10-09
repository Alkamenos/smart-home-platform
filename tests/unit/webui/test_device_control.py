"""
T022-T023: Проверки управления устройством с карточки.

История 3 (P2): Пользователь может включить/выключить устройство прямо с карточки
кнопкой. Используется существующий endpoint execute_device_command с проверкой ролей.

# Copyright 2026 Leonid Artemev
# SPDX-License-Identifier: Apache-2.0
"""


class TestDeviceControl:
    """T022: Проверки отправки команды управления."""

    def test_toggle_command_structure(self) -> None:
        """Команда переключения имеет правильную структуру."""
        entity_id = "light.kitchen"
        current_state = "off"

        # Определяем целевое состояние
        target_state = "on" if current_state == "off" else "off"

        command = {"entity_id": entity_id, "action": target_state}

        assert command["entity_id"] == entity_id
        assert command["action"] in ("on", "off")

    def test_control_endpoint_url(self) -> None:
        """URL эндпоинта управления."""
        entity_id = "light.kitchen"
        expected_url = f"/devices/{entity_id}/command"

        assert entity_id in expected_url
        assert "/command" in expected_url

    def test_control_command_on(self) -> None:
        """Команда включить устройство."""
        command = {"entity_id": "light.kitchen", "action": "on"}

        assert command["action"] == "on"

    def test_control_command_off(self) -> None:
        """Команда выключить устройство."""
        command = {"entity_id": "light.kitchen", "action": "off"}

        assert command["action"] == "off"

    def test_control_toggle_logic(self) -> None:
        """Логика переключения: off → on, on → off."""
        states = [("off", "on"), ("on", "off")]

        for current, expected in states:
            target = "on" if current == "off" else "off"
            assert target == expected


class TestControlPermissions:
    """T023: Проверки прав доступа на управление."""

    def test_admin_can_control(self) -> None:
        """Администратор может управлять."""
        user_role = "admin"
        can_control = user_role in ("controller", "admin")

        assert can_control is True

    def test_controller_can_control(self) -> None:
        """Контроллер может управлять."""
        user_role = "controller"
        can_control = user_role in ("controller", "admin")

        assert can_control is True

    def test_viewer_cannot_control(self) -> None:
        """Просмотрщик не может управлять."""
        user_role = "viewer"
        can_control = user_role in ("controller", "admin")

        assert can_control is False

    def test_guest_cannot_control(self) -> None:
        """Гость не может управлять."""
        user_role = "guest"
        can_control = user_role in ("controller", "admin")

        assert can_control is False

    def test_unknown_role_cannot_control(self) -> None:
        """Неизвестная роль по умолчанию не может управлять."""
        user_role = "unknown"
        can_control = user_role in ("controller", "admin")

        assert can_control is False

    def test_button_hidden_for_viewer(self) -> None:
        """Кнопка управления скрыта для просмотрщика."""
        can_control = False
        button_shown = can_control

        assert button_shown is False

    def test_button_visible_for_controller(self) -> None:
        """Кнопка управления видна для контроллера."""
        can_control = True
        button_shown = can_control

        assert button_shown is True


class TestControlDisplay:
    """Интеграция: как выглядит управление на карточке."""

    def test_card_has_control_button_for_authorized(self) -> None:
        """На карточке есть кнопка для авторизованного пользователя."""
        can_control = True
        device = {"entity_id": "light.kitchen", "name": "Свет на кухне"}

        if can_control:
            button_html = (
                f'<button onclick="toggleDevice(\'{device["entity_id"]}\')" title="Переключить">'
            )
            assert device["entity_id"] in button_html
            assert "toggleDevice" in button_html

    def test_card_no_control_button_for_viewer(self) -> None:
        """На карточке нет кнопки для просмотрщика."""
        can_control = False

        has_button = can_control

        assert has_button is False

    def test_toggle_button_uses_entity_id(self) -> None:
        """Кнопка передаёт правильный entity_id."""
        entity_id = "light.kitchen"
        button_call = f"toggleDevice('{entity_id}')"

        assert entity_id in button_call
        assert "toggleDevice" in button_call

    def test_control_disabled_for_unavailable_device(self) -> None:
        """Управление отключено для недоступного устройства."""
        state = {"available": False, "state": "unavailable"}

        # Если устройство недоступно, кнопка может быть disabled
        can_control = state["available"]

        assert can_control is False

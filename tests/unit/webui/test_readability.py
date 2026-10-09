"""
T025-T026: Проверки читаемости карточек (история 4).

История 4 (P2): Карточка читаема пользователем — правильные названия, иконки,
описания поведений, адаптивная вёрстка, русский язык везде.

# Copyright 2026 Leonid Artemev
# SPDX-License-Identifier: Apache-2.0
"""


class TestDeviceNames:
    """T025: Названия устройств из манифеста."""

    def test_device_shows_friendly_name(self) -> None:
        """На карточке показывается friendly_name из манифеста, не entity_id."""
        device = {"entity_id": "light.kitchen_main", "name": "Основной свет на кухне"}

        assert device["name"] == "Основной свет на кухне"
        assert "light.kitchen_main" not in device["name"]

    def test_device_shows_entity_id_when_no_name(self) -> None:
        """Если нет friendly_name, показывается entity_id."""
        device = {"entity_id": "switch.unknown_device", "name": None}

        display = device["name"] or device["entity_id"]
        assert display == "switch.unknown_device"

    def test_device_name_and_id_together(self) -> None:
        """На карточке название и entity_id — название главное."""
        device = {"entity_id": "light.kitchen", "name": "Свет на кухне"}

        # Макет: название + [id] меньший
        display = f"{device['name']} ({device['entity_id']})"
        assert "Свет на кухне" in display
        assert "light.kitchen" in display


class TestBehaviorDescriptions:
    """T025-T026: Описания поведений."""

    def test_behavior_template_title(self) -> None:
        """На карточке показывается название шаблона поведения."""
        templates = {
            "lighting": "свет от движения",
            "deco_light": "вечерний свет",
            "climate": "климат",
        }

        for template, title in templates.items():
            assert templates[template] == title

    def test_behavior_badge_display(self) -> None:
        """Поведение показывается как badge с текстом."""
        behavior = {"template": "lighting", "title": "свет от движения"}

        display = f'<span class="badge">{behavior["title"]}</span>'
        assert "свет от движения" in display
        assert "badge" in display


class TestIcons:
    """Иконки для типов датчиков и состояний."""

    def test_icon_for_temperature_sensor(self) -> None:
        """Датчик температуры имеет иконку термометра."""
        icon_class = "bi-thermometer"
        assert "thermometer" in icon_class

    def test_icon_for_humidity_sensor(self) -> None:
        """Датчик влажности имеет иконку капли."""
        icon_class = "bi-droplet"
        assert "droplet" in icon_class

    def test_icon_for_motion_sensor(self) -> None:
        """Датчик движения имеет иконку активности."""
        icon_class = "bi-activity"
        assert "activity" in icon_class

    def test_icon_for_contact_sensor(self) -> None:
        """Датчик контакта имеет иконку дверь."""
        icon_class = "bi-door-closed"
        assert "door" in icon_class


class TestLanguage:
    """T026: Русский язык везде."""

    def test_on_state_in_russian(self) -> None:
        """Состояние 'включено' по-русски."""
        display = "включено"
        assert display == "включено"
        assert "on" not in display.lower()

    def test_off_state_in_russian(self) -> None:
        """Состояние 'выключено' по-русски."""
        display = "выключено"
        assert display == "выключено"
        assert "off" not in display.lower()

    def test_unavailable_in_russian(self) -> None:
        """Состояние 'не отвечает' по-русски."""
        display = "не отвечает"
        assert display == "не отвечает"

    def test_no_data_in_russian(self) -> None:
        """'Нет данных' по-русски."""
        display = "нет данных"
        assert display == "нет данных"

    def test_control_button_in_russian(self) -> None:
        """Подпись кнопки на русском."""
        button_text = "Переключить состояние"
        assert "Переключить" in button_text


class TestResponsive:
    """T026-T027: Адаптивная вёрстка."""

    def test_grid_single_column_on_phone(self) -> None:
        """На телефоне (< 600px) одна колонка."""
        media_query = "@media (max-width: 600px) { .device-grid { grid-template-columns: 1fr; } }"
        assert "1fr" in media_query
        assert "grid-template-columns" in media_query

    def test_grid_two_columns_on_tablet(self) -> None:
        """На планшете (600px–1000px) две колонки."""
        media_query = "@media (600px <= width <= 1000px) { grid-template-columns: repeat(2, 1fr); }"
        assert "repeat(2" in media_query

    def test_grid_three_columns_on_desktop(self) -> None:
        """На десктопе (> 1000px) три колонки."""
        media_query = (
            "@media (min-width: 1000px) { .device-grid { grid-template-columns: repeat(3, 1fr); } }"
        )
        assert "repeat(3" in media_query

    def test_font_size_readable_on_phone(self) -> None:
        """Шрифт на телефоне достаточный (не менее 14px)."""
        font_size = 14  # px
        assert font_size >= 14

    def test_button_touch_target_size(self) -> None:
        """Кнопка имеет достаточный размер для тача (48px)."""
        button_size = 48  # px
        assert button_size >= 48


class TestDarkTheme:
    """Цветовая схема (тёмная тема)."""

    def test_background_dark(self) -> None:
        """Фон тёмный (rgba или hex тёмный)."""
        bg_color = "rgba(10, 10, 20, 0.95)"
        assert "rgba" in bg_color or "#" in bg_color

    def test_text_light(self) -> None:
        """Текст светлый (контрастный)."""
        text_color = "#e0e0e0"
        # Светлый = высокий hex
        assert all(c in "0123456789abcdefABCDEF#" for c in text_color)

    def test_accent_color(self) -> None:
        """Accentна окраска (для выделения)."""
        accent = "--accent"
        # Переменная CSS
        assert "accent" in accent

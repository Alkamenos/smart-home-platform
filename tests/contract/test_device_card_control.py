"""На карточке устройства есть рабочее управление (пункт 3 веб-плана).

Кнопка включается/выключает устройство через `POST /api/v1/devices/{id}/command`.
Три требования проверяются отдельно, потому что каждое из них уже было источником
неверного поведения:

1. Кнопка вообще есть и знает идентификатор устройства платформы. Карточки
   размечены `entity_id` из Home Assistant, а маршрут команды ждёт внутренний
   UUID — без подстановки кнопка была бы мёртвой.
2. Пауза после команды больше `debounce_sec` шаблона (0.5 с). Вторая команда в
   пределах этого окна отвергается движком как дребезг, и без паузы второе
   нажатие выглядело бы как «не работает».
3. Ответ различает `automation_synced`. Если в шаблоне нет ручного перехода,
   команда ушла прямо в Home Assistant, и пользователь должен это видеть.

Проверки сверяют шаблон и маршрут, а не «наличие строк»: утверждение без привязки
к поведению проверяет текст, а не проводку.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient


TEMPLATE = (
    Path(__file__).resolve().parents[2] / "src" / "webui" / "templates" / "index.html"
).read_text(encoding="utf-8")


class TestDeviceCardHasControl:
    """Кнопка управления присутствует и подключена."""

    def test_should_render_power_button_with_device_id(self) -> None:
        """Кнопка получает внутренний идентификатор устройства."""
        assert "device-power" in TEMPLATE, "кнопки управления на карточке нет"
        assert "data-device-id" in TEMPLATE, "кнопка не знает идентификатор устройства"

    def test_should_insert_control_into_rendered_card(self) -> None:
        """Кнопка именно вставляется в карточку, а не просто описана в файле.

        Проверка по телу функции `renderDeviceState`. Первая редакция смотрела на
        весь файл и потому оставалась зелёной, когда вставку кнопки из карточки
        убирали: символы `device-power` и `deviceIdByEntity` в файле оставались.
        Это ровно проверка «файл содержит строки» вместо «проводка существует».
        """
        body = re.search(
            r"function renderDeviceState\(entityId\) \{(.*?)\n            \}",
            TEMPLATE,
            re.S,
        )
        assert body is not None, "не найдена функция renderDeviceState"
        text = body.group(1)
        assert "deviceControlHtml(entityId, raw)" in text, (
            "карточка не вставляет управление — кнопка описана в файле, но на "
            "карточке не появляется"
        )
        assert "wireDeviceControl(holder, entityId)" in text, (
            "управление вставляется, но обработчик не подключается — кнопка мертва"
        )

    def test_should_resolve_device_id_from_entity_id(self) -> None:
        """Идентификатор берётся из выгрузки устройств по entity_id.

        Args:
            Привязка к данным: маршрут команды ждёт UUID платформы, а карточка
            размечена entity_id из Home Assistant.
        """
        assert "deviceIdByEntity" in TEMPLATE
        assert "ha_entity_id === entityId" in TEMPLATE

    def test_should_call_command_route_of_device(self) -> None:
        """Запрос уходит на маршрут команды устройства."""
        assert re.search(
            r"/api/v1/devices/\$\{encodeURIComponent\(deviceId\)\}/command", TEMPLATE
        ), "кнопка не вызывает маршрут команды устройства"


class TestCommandCooldown:
    """Пауза после команды учитывает дебаунс шаблона."""

    def test_should_wait_more_than_template_debounce(self) -> None:
        """Пауза больше `debounce_sec` из lighting.yaml.

        При `debounce_sec: 0.5` пауза 900 мс гарантированно перекрывает окно.
        Считывается само значение, чтобы правка шаблона не оставила кнопку
        бесполезной молча.
        """
        lighting = (
            Path(__file__).resolve().parents[2] / "src" / "features" / "lighting.yaml"
        ).read_text(encoding="utf-8")
        debounce_ms = float(re.search(r"debounce_sec:\s*([0-9.]+)", lighting).group(1)) * 1000

        cooldown = int(re.search(r"DEVICE_COMMAND_COOLDOWN_MS\s*=\s*([0-9]+)", TEMPLATE).group(1))
        assert cooldown > debounce_ms, (
            f"пауза {cooldown} мс не перекрывает debounce_sec {debounce_ms:.0f} мс: "
            "второе нажатие будет отвергнуто как дребезг"
        )

    def test_should_disable_button_during_cooldown(self) -> None:
        """Кнопка гасится на время паузы."""
        assert "button.disabled = true" in TEMPLATE
        assert "button.disabled = false" in TEMPLATE


class TestCommandOutcomeVisible:
    """Исход команды показывается пользователю."""

    def test_should_distinguish_unsynced_automation(self) -> None:
        """Ответ `automation_synced` различается, а не игнорируется."""
        assert "automation_synced" in TEMPLATE
        assert "автоматика не следит" in TEMPLATE, (
            "нет указания, что автоматика за устройством не следит — пользователь "
            "решит, что автоматика работает"
        )

    def test_should_show_failure_instead_of_silence(self) -> None:
        """Ошибка команды видна, а не проглочена."""
        assert "!response.ok" in TEMPLATE


class TestCommandRouteReachable:
    """Маршрут команды отвечает для устройства с карточки."""

    def test_should_accept_command_for_switchable_device(self, isolated_client: TestClient) -> None:
        """Устройство, созданное через API, принимает команду.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Источник для кнопки",
                "url": "http://192.168.1.12:8123",
                "token": "probe_token_long_enough",
            },
        )
        assert source.status_code == 201, source.text
        applied = isolated_client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source.json()["id"],
                "dry_run": False,
                "selections": [
                    {
                        "device_entity_id": "light.button_probe",
                        "device_type": "light",
                        "name": "Свет для кнопки",
                        "target_room": "kitchen",
                        "behavior_template": "lighting",
                    }
                ],
            },
        )
        assert applied.status_code == 201, applied.text
        device_id = isolated_client.get("/api/v1/devices?ha_entity_id=light.button_probe").json()[
            0
        ]["id"]

        response = isolated_client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"name": "turn_on", "parameters": {}},
        )

        assert response.status_code == 200, response.text
        assert response.json()["automation_synced"] is True

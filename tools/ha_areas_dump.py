"""Выгрузка областей Home Assistant вместе со светильниками.

Зачем: REST Home Assistant области не отдаёт (`GET /api/areas` → 404), из-за чего
комнату каждого светильника приходилось подбирать руками — и молчаливый выбор
«первой комнаты» однажды посадил двадцать чужих светильников в кухню
(Known Issue #88). Через WebSocket те же данные отдаются штатно:
`config/area_registry/list` (комнаты), `config/device_registry/list` (устройства)
и `config/entity_registry/list` (сущности) — сущность знает своё устройство,
устройство — свою область.

Запуск:

    python tools/ha_areas_dump.py                     # токен из HA_TOKEN
    HA_TOKEN=... python tools/ha_areas_dump.py

Токен берётся из переменной окружения, а если её нет — из `deploy/docker/.env`
(того же файла, которым настроен боевой контейнер). Сам токен в вывод не
попадает: печатаются только комнаты, сущности и их состояние.

Вывод — две таблицы. Первая: светильники с областью (их раскладывать по
комнатам манифеста можно сразу). Вторая: светильники без области — в доме их
меньшинство, и для них комната назначается вручную в манифесте, потому что
угадывать её нельзя (та же причина, что и у Known Issue #88).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import websockets


ENV_PATH = Path("deploy/docker/.env")
WS_URL_ENV = "HA_WS_URL"
DEFAULT_WS_URL = "ws://192.168.2.10:8123/api/websocket"


def read_token() -> str:
    """Достать токен Home Assistant из окружения или из файла боевого контейнера.

    Returns:
        Токен доступа.

    Raises:
        SystemExit: токен не найден ни в окружении, ни в `deploy/docker/.env`.
    """
    token = os.environ.get("HA_TOKEN", "").strip()
    if token:
        return token
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("HA_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise SystemExit(
        f"Токен не найден: задайте HA_TOKEN или добавьте его в {ENV_PATH}. "
        "Без токена области не прочитать — в этом и был весь смысл инструмента."
    )


class HomeAssistant:
    """Минимальный клиент WebSocket Home Assistant для чтения реестров.

    Область (`area_registry`), устройства (`device_registry`) и сущности
    (`entity_registry`) читаются тремя командами по порядку: сущность знает
    устройство, устройство — область, и только так получается полная картина.

    Args:
        url: Адрес WebSocket API.
        token: Токен доступа.
    """

    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self._next_id = 1

    async def _call(self, websocket: Any, command: str) -> list[dict[str, Any]]:
        """Выполнить команду и дождаться ответа с её идентификатором.

        Args:
            websocket: Открытое соединение WebSocket.
            command: Команда вроде `config/area_registry/list`.

        Returns:
            Результат команды — список словарей. При ошибке Home Assistant
            возвращается пустой список, а причина печатается: молчаливый пустой
            список выглядел бы как «в доме нет областей» и увёл бы в сторону.

        Raises:
            SystemExit: Home Assistant отверг команду.
        """
        request_id = self._next_id
        self._next_id += 1
        await websocket.send(json.dumps({"id": request_id, "type": command}))
        while True:
            message = json.loads(await websocket.recv())
            if message.get("id") != request_id:
                continue
            if not message.get("success"):
                raise SystemExit(f"Home Assistant отверг {command}: {message.get('error')}")
            return message.get("result", [])

    async def collect(self) -> list[tuple[str, str, str]]:
        """Прочитать области и вернуть строки «комната, сущность, состояние».

        Returns:
            Список кортежей. Комната — пустая строка, если область не назначена.
        """
        url = self.url
        async with websockets.connect(url, max_size=None) as websocket:
            await websocket.recv()  # auth_required
            await websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
            answer = json.loads(await websocket.recv())
            if answer.get("type") != "auth_ok":
                raise SystemExit(f"Home Assistant не пустил: {answer}")

            areas = await self._call(websocket, "config/area_registry/list")
            devices = await self._call(websocket, "config/device_registry/list")
            entities = await self._call(websocket, "config/entity_registry/list")

        area_names = {area["area_id"]: area.get("name") or area["area_id"] for area in areas}
        device_by_id = {device["id"]: device for device in devices}

        states = await read_states(url.replace("api/websocket", "api/states"), self.token)

        rows: list[tuple[str, str, str]] = []
        for entity in sorted(entities, key=lambda item: item["entity_id"]):
            entity_id = entity["entity_id"]
            if not entity_id.startswith("light."):
                continue
            device = device_by_id.get(entity.get("device_id"), {})
            room = area_names.get(device.get("area_id"), "")
            state = states.get(entity_id, "неизвестно")
            rows.append((room, entity_id, state))
        return rows


async def read_states(rest_url: str, token: str) -> dict[str, str]:
    """Прочитать текущие состояния сущностей, чтобы показать и `unavailable`.

    Args:
        rest_url: Адрес REST API (получен из адреса WebSocket).
        token: Токен доступа.

    Returns:
        Словарь `entity_id` → состояние. Пустой при ошибке: недоступность REST
        не должна мешать выгрузке областей, ради которой инструмент написан.
    """
    import aiohttp  # noqa: PLC0415 — локальный импорт: без него выгрузка областей не падает

    headers = {"Authorization": f"Bearer {token}"}
    async with (
        aiohttp.ClientSession(headers=headers) as session,
        session.get(rest_url, timeout=aiohttp.ClientTimeout(total=10)) as response,
    ):
        if response.status != 200:
            return {}
        payload = await response.json(content_type=None)
    return {item["entity_id"]: str(item.get("state", "")) for item in payload}


def main() -> None:
    """Напечатать светильники по областям и отдельно — без области.

    Returns:
        Ничего.
    """
    rows = asyncio.run(
        HomeAssistant(os.environ.get(WS_URL_ENV, DEFAULT_WS_URL), read_token()).collect()
    )
    assigned = [row for row in rows if row[0]]
    unassigned = [row for row in rows if not row[0]]

    print(f"Всего светильников: {len(rows)}, с областью: {len(assigned)}\n")
    print("=== С областью — раскладывать по манифесту ===")
    for room, entity_id, state in assigned:
        flag = "  [не отвечает]" if state == "unavailable" else ""
        print(f"{room:<22} {entity_id:<46} {state}{flag}")

    print("\n=== Без области — комната назначается в манифесте вручную ===")
    for _, entity_id, state in unassigned:
        flag = "  [не отвечает]" if state == "unavailable" else ""
        print(f"{'—':<22} {entity_id:<46} {state}{flag}")


if __name__ == "__main__":
    main()

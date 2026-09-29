# Примеры использования API интеграции устройств

**Версия**: 1.0
**Дата**: 2026-09-29
**Язык**: Русский

Этот документ содержит практические примеры для всех основных сценариев работы с API интеграции устройств из Home Assistant. Каждый пример включает описание, код (curl или Python), ожидаемый результат и объяснение ключевых полей.

---

## 1. Добавление источника Home Assistant

**Описание сценария**

Это первый шаг интеграции — добавление нового источника Home Assistant в систему. Источник представляет собой подключение к экземпляру HA, из которого будут загружаться устройства. Требуется передать URL сервера HA и long-lived access token для аутентификации.

**Curl команда**

```bash
curl -X POST http://localhost:8000/api/v1/devices/sources \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Home Assistant Test",
    "url": "http://192.168.1.100:8123",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

**Python код**

```python
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"
PLATFORM_TOKEN = "your-platform-token"

headers = {"Authorization": f"Bearer {PLATFORM_TOKEN}", "Content-Type": "application/json"}

payload = {
    "name": "Home Assistant Test",
    "url": "http://192.168.1.100:8123",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
}

response = requests.post(f"{BASE_URL}/devices/sources", headers=headers, json=payload)

if response.status_code == 201:
    source = response.json()
    print(f"Source created: {source['id']}")
    print(f"Status: {source['status']}")
else:
    print(f"Error: {response.status_code} - {response.text}")
```

**Ожидаемый результат**

```json
{
  "id": "9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
  "name": "Home Assistant Test",
  "url": "http://192.168.1.100:8123",
  "status": "connecting",
  "device_count": 0,
  "created_at": "2026-09-29T10:00:00Z",
  "last_sync": null
}
```

**Объяснение ключевых полей**

- **id** — уникальный идентификатор источника. Используется для последующих операций синхронизации и проверки статуса
- **status** — текущий статус подключения. Может быть: `connecting` (подключается), `connected` (успешно подключено), `error` (ошибка соединения)
- **device_count** — количество устройств, загруженных из этого источника. Изначально 0, будет обновлено после синхронизации
- **last_sync** — время последней успешной синхронизации. Null, если синхронизация еще не проводилась

---

## 2. Синхронизация устройств

**Описание сценария**

После добавления источника необходимо запустить синхронизацию для загрузки всех устройств из Home Assistant. Синхронизация выполняется асинхронно и может занять от нескольких секунд до нескольких минут в зависимости от количества устройств.

**Curl команда**

```bash
# Получить статус источника (убедиться, что статус = "connected")
curl http://localhost:8000/api/v1/devices/sources/9f1f5c3d-4e2b-11eb-ae93-0242ac120002 \
  -H "Authorization: Bearer your-platform-token"

# Запустить синхронизацию
curl -X POST http://localhost:8000/api/v1/devices/sources/9f1f5c3d-4e2b-11eb-ae93-0242ac120002/sync \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

**Python код**

```python
import requests
import time

BASE_URL = "http://localhost:8000/api/v1"
PLATFORM_TOKEN = "your-platform-token"
SOURCE_ID = "9f1f5c3d-4e2b-11eb-ae93-0242ac120002"

headers = {"Authorization": f"Bearer {PLATFORM_TOKEN}", "Content-Type": "application/json"}

# Проверить статус источника
status_response = requests.get(f"{BASE_URL}/devices/sources/{SOURCE_ID}", headers=headers)

source_status = status_response.json()
print(f"Source status: {source_status['status']}")

if source_status["status"] == "connected":
    # Запустить синхронизацию
    sync_response = requests.post(
        f"{BASE_URL}/devices/sources/{SOURCE_ID}/sync", headers=headers, json={"force": False}
    )

    if sync_response.status_code == 202:
        sync_data = sync_response.json()
        print(f"Sync started: {sync_data['sync_id']}")

        # Дождаться завершения синхронизации
        while True:
            time.sleep(5)
            devices_response = requests.get(f"{BASE_URL}/devices", headers=headers)
            devices = devices_response.json()
            print(f"Devices loaded: {devices['total']}")
            if devices["total"] > 0:
                break
```

**Ожидаемый результат**

```json
{
  "sync_id": "sync-9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
  "source_id": "9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
  "status": "started",
  "started_at": "2026-09-29T10:00:05Z",
  "devices_found": null,
  "devices_added": null,
  "devices_updated": null
}
```

**Объяснение ключевых полей**

- **sync_id** — уникальный идентификатор операции синхронизации
- **status** — статус процесса синхронизации: `started` (начата), `in_progress` (в процессе), `completed` (завершена), `failed` (ошибка)
- **started_at** — время начала синхронизации
- **devices_found** — общее количество найденных устройств в HA
- **devices_added** — количество новых добавленных устройств
- **devices_updated** — количество обновленных устройств

---

## 3. Получение списка устройств

**Описание сценария**

После успешной синхронизации можно получить список всех загруженных устройств. API поддерживает фильтрацию, сортировку и пагинацию для удобного просмотра больших наборов данных.

**Curl команда**

```bash
# Получить первую страницу всех устройств
curl "http://localhost:8000/api/v1/devices?page=1&page_size=25" \
  -H "Authorization: Bearer your-platform-token"

# Получить только устройства типа "light"
curl "http://localhost:8000/api/v1/devices?device_type=light&page=1&page_size=25" \
  -H "Authorization: Bearer your-platform-token"

# Получить только доступные устройства
curl "http://localhost:8000/api/v1/devices?status=available&page=1&page_size=25" \
  -H "Authorization: Bearer your-platform-token"
```

**Python код**

```python
import requests
from typing import List, Dict

BASE_URL = "http://localhost:8000/api/v1"
PLATFORM_TOKEN = "your-platform-token"

headers = {"Authorization": f"Bearer {PLATFORM_TOKEN}"}


def get_devices(
    device_type: str = None, status: str = None, page: int = 1, page_size: int = 25
) -> Dict:
    """
    Получить список устройств с фильтрацией и пагинацией

    Args:
        device_type: Тип устройства для фильтрации (light, switch, sensor и т.д.)
        status: Статус для фильтрации (available, unavailable, error)
        page: Номер страницы
        page_size: Размер страницы

    Returns:
        Словарь с данными страницы и списком устройств
    """
    params = {"page": page, "page_size": page_size}

    if device_type:
        params["device_type"] = device_type
    if status:
        params["status"] = status

    response = requests.get(f"{BASE_URL}/devices", headers=headers, params=params)

    return response.json()


# Получить все огни
lights = get_devices(device_type="light")
print(f"Total lights: {lights['total']}")

for device in lights["items"]:
    print(f"  - {device['name']} ({device['ha_entity_id']})")

# Получить только доступные устройства
available = get_devices(status="available")
print(f"Available devices: {available['total']}")
```

**Ожидаемый результат**

```json
{
  "total": 47,
  "page": 1,
  "page_size": 25,
  "items": [
    {
      "id": "device-uuid-1",
      "ha_entity_id": "light.kitchen_light",
      "name": "Kitchen Light",
      "device_type": "light",
      "status": "available",
      "source_id": "9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
      "created_at": "2026-09-29T10:00:10Z",
      "state": {
        "state": "on",
        "brightness": 200
      }
    },
    {
      "id": "device-uuid-2",
      "ha_entity_id": "switch.kitchen_outlet",
      "name": "Kitchen Outlet",
      "device_type": "switch",
      "status": "available",
      "source_id": "9f1f5c3d-4e2b-11eb-ae93-0242ac120002",
      "created_at": "2026-09-29T10:00:10Z",
      "state": {
        "state": "off"
      }
    }
  ]
}
```

**Объяснение ключевых полей**

- **id** — уникальный идентификатор устройства в системе
- **ha_entity_id** — идентификатор сущности в Home Assistant (используется для команд и синхронизации состояния)
- **device_type** — тип устройства: `light` (лампа), `switch` (выключатель), `sensor` (датчик), `binary_sensor` (двоичный датчик), `climate` (климат), `fan` (вентилятор) и др.
- **status** — статус доступности: `available` (доступно), `unavailable` (недоступно), `error` (ошибка)
- **state** — текущее состояние устройства (структура зависит от типа)
- **total** — общее количество устройств (с учетом фильтров)
- **page**, **page_size** — информация о пагинации

---

## 4. Обновление конфигурации устройства

**Описание сценария**

Каждое устройство имеет конфигурацию, которая может быть отредактирована. Конфигурация включает отображаемое имя, описание, локацию, теги и статус включения. Эти параметры используются для метаданных и управления доступом.

**Curl команда**

```bash
# Получить текущую конфигурацию
curl http://localhost:8000/api/v1/devices/device-uuid-1 \
  -H "Authorization: Bearer your-platform-token"

# Обновить конфигурацию
curl -X PUT http://localhost:8000/api/v1/devices/device-uuid-1/config \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "Kitchen Main Light",
    "description": "Primary light for general kitchen lighting",
    "location": "kitchen",
    "tags": ["lights", "automatable", "main"],
    "enabled": true
  }'
```

**Python код**

```python
import requests

BASE_URL = "http://localhost:8000/api/v1"
PLATFORM_TOKEN = "your-platform-token"
DEVICE_ID = "device-uuid-1"

headers = {"Authorization": f"Bearer {PLATFORM_TOKEN}", "Content-Type": "application/json"}

# Получить текущую конфигурацию
get_response = requests.get(f"{BASE_URL}/devices/{DEVICE_ID}", headers=headers)

current_config = get_response.json()
print(f"Current config: {current_config['config']}")

# Обновить конфигурацию
new_config = {
    "display_name": "Kitchen Main Light",
    "description": "Primary light for general kitchen lighting",
    "location": "kitchen",
    "tags": ["lights", "automatable", "main"],
    "enabled": True,
}

update_response = requests.put(
    f"{BASE_URL}/devices/{DEVICE_ID}/config", headers=headers, json=new_config
)

if update_response.status_code == 200:
    updated = update_response.json()
    print(f"Config updated: {updated['config']}")
    print(f"Updated at: {updated['updated_at']}")
else:
    print(f"Error: {update_response.status_code} - {update_response.text}")
```

**Ожидаемый результат**

```json
{
  "id": "device-uuid-1",
  "ha_entity_id": "light.kitchen_light",
  "name": "Kitchen Light",
  "config": {
    "display_name": "Kitchen Main Light",
    "description": "Primary light for general kitchen lighting",
    "location": "kitchen",
    "tags": ["lights", "automatable", "main"],
    "enabled": true
  },
  "updated_at": "2026-09-29T10:05:00Z"
}
```

**Объяснение ключевых полей**

- **display_name** — пользовательское отображаемое имя устройства (может отличаться от имени в HA)
- **description** — подробное описание назначения или функционала устройства
- **location** — локация устройства для группировки и организации (например, "kitchen", "bedroom", "living_room")
- **tags** — массив меток для удобной категоризации и фильтрации устройств
- **enabled** — флаг, указывающий, включено ли устройство (может использоваться для отключения без удаления)
- **updated_at** — время последнего обновления конфигурации

---

## 5. Отправка команды на устройство

**Описание сценария**

Это позволяет отправлять команды управления на устройства в Home Assistant. Каждое устройство имеет определенный набор доступных команд в зависимости от его типа. Команды выполняются асинхронно и может быть проверен их статус.

**Curl команда**

```bash
# Получить доступные команды для устройства
curl http://localhost:8000/api/v1/devices/device-uuid-1 \
  -H "Authorization: Bearer your-platform-token"

# Отправить команду "включить свет"
curl -X POST http://localhost:8000/api/v1/devices/device-uuid-1/command \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "turn_on",
    "parameters": {}
  }'

# Отправить команду "установить яркость"
curl -X POST http://localhost:8000/api/v1/devices/device-uuid-1/command \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "set_brightness",
    "parameters": {"brightness": 200}
  }'
```

**Python код**

```python
import requests
import time

BASE_URL = "http://localhost:8000/api/v1"
PLATFORM_TOKEN = "your-platform-token"
DEVICE_ID = "device-uuid-1"

headers = {"Authorization": f"Bearer {PLATFORM_TOKEN}", "Content-Type": "application/json"}


def get_device_commands(device_id: str) -> list:
    """Получить список доступных команд для устройства"""
    response = requests.get(f"{BASE_URL}/devices/{device_id}", headers=headers)
    device = response.json()
    return device.get("commands", [])


def send_command(device_id: str, command: str, parameters: dict = None) -> str:
    """
    Отправить команду на устройство

    Args:
        device_id: ID устройства
        command: Имя команды
        parameters: Параметры команды

    Returns:
        command_id для проверки статуса
    """
    payload = {"command": command, "parameters": parameters or {}}

    response = requests.post(
        f"{BASE_URL}/devices/{device_id}/command", headers=headers, json=payload
    )

    if response.status_code == 202:
        return response.json()["command_id"]
    else:
        raise Exception(f"Failed to send command: {response.text}")


def get_command_status(device_id: str, command_id: str) -> dict:
    """Получить статус выполнения команды"""
    response = requests.get(f"{BASE_URL}/devices/{device_id}/command/{command_id}", headers=headers)
    return response.json()


# Пример использования
try:
    # Получить доступные команды
    commands = get_device_commands(DEVICE_ID)
    print(f"Available commands: {[c['name'] for c in commands]}")

    # Отправить команду
    command_id = send_command(DEVICE_ID, "set_brightness", {"brightness": 200})
    print(f"Command sent: {command_id}")

    # Проверить статус
    for i in range(10):
        time.sleep(0.5)
        status = get_command_status(DEVICE_ID, command_id)
        print(f"Status: {status['status']}")
        if status["status"] in ["success", "failed"]:
            break

except Exception as e:
    print(f"Error: {e}")
```

**Ожидаемый результат**

Получение команд:
```json
{
  "commands": [
    {
      "id": "cmd-uuid-1",
      "name": "turn_on",
      "ha_service": "light.turn_on",
      "description": "Turn light on",
      "parameters": {},
      "is_safe": true
    },
    {
      "id": "cmd-uuid-2",
      "name": "set_brightness",
      "ha_service": "light.turn_on",
      "description": "Set brightness level",
      "parameters": {
        "brightness": {
          "type": "integer",
          "min": 0,
          "max": 255,
          "required": true
        }
      },
      "is_safe": true
    }
  ]
}
```

Отправка команды (ответ):
```json
{
  "command_id": "cmd-exec-uuid",
  "device_id": "device-uuid-1",
  "command": "set_brightness",
  "status": "pending",
  "parameters": {"brightness": 200},
  "sent_at": "2026-09-29T10:15:00Z"
}
```

Проверка статуса:
```json
{
  "command_id": "cmd-exec-uuid",
  "device_id": "device-uuid-1",
  "command": "set_brightness",
  "status": "success",
  "executed_at": "2026-09-29T10:15:02Z",
  "duration_ms": 125
}
```

**Объяснение ключевых полей**

- **command** — имя команды для отправки на устройство
- **parameters** — параметры команды (зависит от команды, может быть пустым)
- **command_id** — уникальный идентификатор выполнения команды для отслеживания
- **status** — статус выполнения: `pending` (в ожидании), `executing` (выполняется), `success` (успешно), `failed` (ошибка)
- **duration_ms** — время выполнения команды в миллисекундах
- **is_safe** — флаг, указывающий, является ли команда безопасной для выполнения

---

## 6. WebSocket подписка на события состояния

**Описание сценария**

WebSocket обеспечивает real-time синхронизацию состояния устройств. Клиент может подписаться на события изменения состояния и получать их в режиме реального времени без необходимости частого опроса API.

**Curl команда (используя websocat или аналогичный инструмент)**

```bash
# Установка websocat (если еще не установлен)
# brew install websocat (macOS)
# или apt-get install websocat (Linux)

# Подключиться к WebSocket
websocat "ws://localhost:8000/api/v1/ws/devices?token=your-platform-token"

# Отправить команду подписки (в WebSocket сессии)
{
  "action": "subscribe",
  "device_ids": ["device-uuid-1", "device-uuid-2"],
  "event_types": ["state_changed"]
}

# Отправить команду для получения статуса
{
  "action": "status"
}

# Отписаться от устройств
{
  "action": "unsubscribe",
  "device_ids": ["device-uuid-1"]
}
```

**Python код**

```python
import asyncio
import json
import websockets
from typing import Callable, List


class DeviceStateWebSocketClient:
    def __init__(self, base_url: str, token: str):
        """
        Инициализировать WebSocket клиент

        Args:
            base_url: URL вебсокета (например, ws://localhost:8000)
            token: Authorization token
        """
        self.url = f"{base_url}/api/v1/ws/devices?token={token}"
        self.websocket = None
        self.handlers = {}

    async def connect(self):
        """Подключиться к WebSocket"""
        self.websocket = await websockets.connect(self.url)
        print("Connected to WebSocket")

    async def subscribe(self, device_ids: List[str], event_types: List[str] = None):
        """
        Подписаться на события устройств

        Args:
            device_ids: Список ID устройств для подписки
            event_types: Типы событий (по умолчанию ['state_changed'])
        """
        if event_types is None:
            event_types = ["state_changed"]

        message = {"action": "subscribe", "device_ids": device_ids, "event_types": event_types}

        await self.websocket.send(json.dumps(message))
        response = await self.websocket.recv()
        print(f"Subscription response: {response}")

    async def unsubscribe(self, device_ids: List[str]):
        """Отписаться от устройств"""
        message = {"action": "unsubscribe", "device_ids": device_ids}

        await self.websocket.send(json.dumps(message))

    def on_state_changed(self, callback: Callable):
        """Зарегистрировать обработчик события изменения состояния"""
        self.handlers["state_changed"] = callback

    async def listen(self):
        """Слушать события из WebSocket"""
        try:
            async for message in self.websocket:
                data = json.loads(message)

                if data.get("type") == "device_state_changed":
                    if "state_changed" in self.handlers:
                        await self.handlers["state_changed"](data)
                    else:
                        print(f"State changed: {data}")

        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed")

    async def close(self):
        """Закрыть соединение"""
        if self.websocket:
            await self.websocket.close()


# Пример использования
async def main():
    client = DeviceStateWebSocketClient("ws://localhost:8000", "your-platform-token")

    # Обработчик события
    async def handle_state_change(event):
        print(f"\nDevice {event['device_id']} changed state:")
        print(f"  Old: {event['old_state']}")
        print(f"  New: {event['new_state']}")
        print(f"  Time: {event['timestamp']}")

    client.on_state_changed(handle_state_change)

    try:
        await client.connect()
        await client.subscribe(["device-uuid-1", "device-uuid-2"])

        # Слушать события
        print("Listening for state changes... (press Ctrl+C to stop)")
        await client.listen()

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Ожидаемый результат**

При подключении:
```json
{
  "type": "connection_established",
  "timestamp": "2026-09-29T10:20:00Z"
}
```

При подписке:
```json
{
  "status": "subscribed",
  "subscribed_devices": 2,
  "subscribed_events": ["state_changed"]
}
```

При изменении состояния устройства:
```json
{
  "type": "device_state_changed",
  "device_id": "device-uuid-1",
  "ha_entity_id": "light.kitchen_light",
  "old_state": {
    "state": "off"
  },
  "new_state": {
    "state": "on",
    "brightness": 150
  },
  "timestamp": "2026-09-29T10:20:05Z"
}
```

**Объяснение ключевых полей**

- **action** — тип действия в WebSocket: `subscribe` (подписаться), `unsubscribe` (отписаться), `status` (получить статус)
- **device_ids** — массив ID устройств для подписки/отписки
- **event_types** — типы событий для отслеживания (например, `state_changed`, `config_changed`)
- **device_id** — ID устройства, у которого изменилось состояние
- **old_state** — предыдущее состояние устройства
- **new_state** — новое состояние устройства
- **timestamp** — время события в ISO 8601 формате
- **subscribed_devices** — количество устройств, на которые подписан клиент

---

## 7. Получение истории операций

**Описание сценария**

История операций содержит логирование всех событий, связанных с устройством: изменения конфигурации, изменения состояния, выполненные команды, ошибки. Это полезно для аудита и отладки.

**Curl команда**

```bash
# Получить все события за последний день
curl "http://localhost:8000/api/v1/devices/device-uuid-1/events?days=1&limit=50" \
  -H "Authorization: Bearer your-platform-token"

# Получить события определенного типа
curl "http://localhost:8000/api/v1/devices/device-uuid-1/events?event_type=command_executed&limit=25" \
  -H "Authorization: Bearer your-platform-token"

# Получить события с пагинацией
curl "http://localhost:8000/api/v1/devices/device-uuid-1/events?page=1&page_size=10" \
  -H "Authorization: Bearer your-platform-token"
```

**Python код**

```python
import requests
from datetime import datetime, timedelta
from typing import List, Dict

BASE_URL = "http://localhost:8000/api/v1"
PLATFORM_TOKEN = "your-platform-token"
DEVICE_ID = "device-uuid-1"

headers = {"Authorization": f"Bearer {PLATFORM_TOKEN}"}


def get_device_events(
    device_id: str,
    days: int = None,
    event_type: str = None,
    status: str = None,
    limit: int = 50,
    page: int = 1,
) -> Dict:
    """
    Получить историю событий устройства

    Args:
        device_id: ID устройства
        days: Количество дней для фильтрации (от текущего момента)
        event_type: Тип события (config_changed, state_changed, command_executed, error)
        status: Статус события (success, failed, pending)
        limit: Максимальное количество событий
        page: Номер страницы

    Returns:
        Словарь с данными о событиях
    """
    params = {"limit": limit, "page": page}

    if days:
        params["days"] = days
    if event_type:
        params["event_type"] = event_type
    if status:
        params["status"] = status

    response = requests.get(
        f"{BASE_URL}/devices/{device_id}/events", headers=headers, params=params
    )

    return response.json()


def print_events(events_data: Dict):
    """Красиво вывести события"""
    print(f"Total events: {events_data['total']}\n")

    for event in events_data["items"]:
        print(f"[{event['timestamp']}] {event['event_type']}")
        print(f"  Status: {event['status']}")

        if "user_id" in event:
            print(f"  User: {event['user_id']}")

        if "details" in event:
            details = event["details"]
            for key, value in details.items():
                print(f"  {key}: {value}")

        print()


# Пример использования
try:
    # Получить все события за последний день
    print("=== Events from last 24 hours ===")
    recent_events = get_device_events(DEVICE_ID, days=1)
    print_events(recent_events)

    # Получить только команды
    print("\n=== Executed commands ===")
    command_events = get_device_events(DEVICE_ID, event_type="command_executed")
    print_events(command_events)

    # Получить только изменения конфигурации
    print("\n=== Configuration changes ===")
    config_events = get_device_events(DEVICE_ID, event_type="config_changed")
    print_events(config_events)

    # Получить только ошибки
    print("\n=== Errors ===")
    error_events = get_device_events(DEVICE_ID, event_type="error")
    print_events(error_events)

except Exception as e:
    print(f"Error: {e}")
```

**Ожидаемый результат**

```json
{
  "total": 15,
  "page": 1,
  "page_size": 50,
  "items": [
    {
      "id": "event-uuid-1",
      "device_id": "device-uuid-1",
      "event_type": "config_changed",
      "status": "success",
      "details": {
        "changed_fields": ["display_name", "tags"],
        "old_value": {
          "display_name": "Kitchen Light",
          "tags": []
        },
        "new_value": {
          "display_name": "Kitchen Main Light",
          "tags": ["lights", "automatable", "main"]
        }
      },
      "user_id": "user-uuid-1",
      "timestamp": "2026-09-29T10:05:00Z"
    },
    {
      "id": "event-uuid-2",
      "device_id": "device-uuid-1",
      "event_type": "command_executed",
      "status": "success",
      "details": {
        "command": "set_brightness",
        "parameters": {"brightness": 200},
        "duration_ms": 125
      },
      "user_id": "user-uuid-2",
      "timestamp": "2026-09-29T10:10:00Z"
    },
    {
      "id": "event-uuid-3",
      "device_id": "device-uuid-1",
      "event_type": "state_changed",
      "status": "success",
      "details": {
        "old_state": {"state": "off"},
        "new_state": {"state": "on", "brightness": 200}
      },
      "timestamp": "2026-09-29T10:10:02Z"
    },
    {
      "id": "event-uuid-4",
      "device_id": "device-uuid-1",
      "event_type": "error",
      "status": "failed",
      "details": {
        "error_type": "timeout",
        "message": "Device did not respond within 5 seconds",
        "attempted_at": "2026-09-29T10:15:00Z"
      },
      "timestamp": "2026-09-29T10:15:05Z"
    }
  ]
}
```

**Объяснение ключевых полей**

- **event_type** — тип события: `state_changed` (изменение состояния), `config_changed` (изменение конфигурации), `command_executed` (команда выполнена), `error` (ошибка), `sync_completed` (синхронизация завершена)
- **status** — результат события: `success` (успешно), `failed` (ошибка), `pending` (в ожидании)
- **details** — детали события (структура зависит от типа события)
- **user_id** — ID пользователя, инициировавшего событие (отсутствует для система-инициированных событий)
- **timestamp** — время события в ISO 8601 формате
- **changed_fields** — для config_changed: массив полей, которые были изменены

---

## 8. Управление доступом к устройствам

**Описание сценария**

Система поддерживает управление доступом к устройствам на уровне пользователей и групп. Можно предоставить или отозвать доступ к отдельным устройствам или их группам, а также установить разрешения (read-only, control, admin).

**Curl команда**

```bash
# Получить текущие разрешения на устройство
curl http://localhost:8000/api/v1/devices/device-uuid-1/permissions \
  -H "Authorization: Bearer your-platform-token"

# Предоставить пользователю доступ на чтение
curl -X POST http://localhost:8000/api/v1/devices/device-uuid-1/permissions \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-uuid-2",
    "permission": "read"
  }'

# Предоставить пользователю контроль над устройством
curl -X POST http://localhost:8000/api/v1/devices/device-uuid-1/permissions \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-uuid-2",
    "permission": "control"
  }'

# Предоставить группе доступ к нескольким устройствам
curl -X POST http://localhost:8000/api/v1/devices/permissions/bulk \
  -H "Authorization: Bearer your-platform-token" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": "group-uuid-1",
    "device_ids": ["device-uuid-1", "device-uuid-2", "device-uuid-3"],
    "permission": "control"
  }'

# Отозвать доступ
curl -X DELETE http://localhost:8000/api/v1/devices/device-uuid-1/permissions/user-uuid-2 \
  -H "Authorization: Bearer your-platform-token"
```

**Python код**

```python
import requests
from typing import List, Dict, Literal

BASE_URL = "http://localhost:8000/api/v1"
PLATFORM_TOKEN = "your-platform-token"

headers = {"Authorization": f"Bearer {PLATFORM_TOKEN}", "Content-Type": "application/json"}


class DeviceAccessManager:
    """Управление доступом к устройствам"""

    @staticmethod
    def get_device_permissions(device_id: str) -> Dict:
        """Получить все разрешения на устройство"""
        response = requests.get(f"{BASE_URL}/devices/{device_id}/permissions", headers=headers)
        return response.json()

    @staticmethod
    def grant_user_permission(
        device_id: str, user_id: str, permission: Literal["read", "control", "admin"]
    ) -> Dict:
        """
        Предоставить пользователю разрешение на устройство

        Args:
            device_id: ID устройства
            user_id: ID пользователя
            permission: Уровень разрешения:
              - read: только просмотр состояния
              - control: просмотр и управление (отправка команд)
              - admin: полный доступ (управление доступом)
        """
        payload = {"user_id": user_id, "permission": permission}

        response = requests.post(
            f"{BASE_URL}/devices/{device_id}/permissions", headers=headers, json=payload
        )

        return response.json()

    @staticmethod
    def grant_group_permissions(
        device_ids: List[str], group_id: str, permission: Literal["read", "control", "admin"]
    ) -> Dict:
        """
        Предоставить группе разрешение на несколько устройств

        Args:
            device_ids: Список ID устройств
            group_id: ID группы
            permission: Уровень разрешения
        """
        payload = {"group_id": group_id, "device_ids": device_ids, "permission": permission}

        response = requests.post(
            f"{BASE_URL}/devices/permissions/bulk", headers=headers, json=payload
        )

        return response.json()

    @staticmethod
    def revoke_permission(device_id: str, user_id: str) -> bool:
        """Отозвать разрешение пользователя на устройство"""
        response = requests.delete(
            f"{BASE_URL}/devices/{device_id}/permissions/{user_id}", headers=headers
        )

        return response.status_code == 204

    @staticmethod
    def get_user_accessible_devices(user_id: str) -> Dict:
        """Получить все устройства, доступные для пользователя"""
        response = requests.get(f"{BASE_URL}/users/{user_id}/devices", headers=headers)

        return response.json()


# Пример использования
def example_access_management():
    manager = DeviceAccessManager()

    # Получить текущие разрешения
    print("=== Current permissions ===")
    perms = manager.get_device_permissions("device-uuid-1")
    print(f"Device: {perms['device_id']}")
    print(f"Total users with access: {perms['total']}")

    for perm in perms["permissions"]:
        print(f"  - {perm['user_id']}: {perm['permission']}")

    # Предоставить доступ на чтение
    print("\n=== Grant read permission ===")
    result = manager.grant_user_permission("device-uuid-1", "user-uuid-2", "read")
    print(f"Permission granted: {result['permission']}")

    # Предоставить контроль
    print("\n=== Grant control permission ===")
    result = manager.grant_user_permission("device-uuid-1", "user-uuid-2", "control")
    print(f"Permission upgraded: {result['permission']}")

    # Предоставить группе доступ к нескольким устройствам
    print("\n=== Grant permissions to group ===")
    result = manager.grant_group_permissions(
        ["device-uuid-1", "device-uuid-2", "device-uuid-3"], "group-uuid-1", "control"
    )
    print(f"Permissions granted to {result['devices_count']} devices")

    # Получить устройства, доступные для пользователя
    print("\n=== User accessible devices ===")
    devices = manager.get_user_accessible_devices("user-uuid-2")
    print(f"Total devices: {devices['total']}")

    for device in devices["items"]:
        print(f"  - {device['name']}: {device['permission']}")

    # Отозвать доступ
    print("\n=== Revoke permission ===")
    success = manager.revoke_permission("device-uuid-1", "user-uuid-2")
    print(f"Permission revoked: {success}")


if __name__ == "__main__":
    example_access_management()
```

**Ожидаемый результат**

Получение разрешений:
```json
{
  "device_id": "device-uuid-1",
  "total": 3,
  "permissions": [
    {
      "user_id": "user-uuid-1",
      "permission": "admin",
      "granted_at": "2026-09-29T09:00:00Z"
    },
    {
      "user_id": "user-uuid-2",
      "permission": "control",
      "granted_at": "2026-09-29T10:05:00Z"
    },
    {
      "group_id": "group-uuid-1",
      "permission": "read",
      "granted_at": "2026-09-29T10:10:00Z"
    }
  ]
}
```

Предоставление разрешения:
```json
{
  "device_id": "device-uuid-1",
  "user_id": "user-uuid-2",
  "permission": "control",
  "granted_at": "2026-09-29T10:05:00Z"
}
```

Массовое предоставление разрешений:
```json
{
  "group_id": "group-uuid-1",
  "devices_count": 3,
  "permission": "control",
  "granted_devices": ["device-uuid-1", "device-uuid-2", "device-uuid-3"],
  "timestamp": "2026-09-29T10:15:00Z"
}
```

Доступные устройства для пользователя:
```json
{
  "user_id": "user-uuid-2",
  "total": 5,
  "items": [
    {
      "id": "device-uuid-1",
      "name": "Kitchen Light",
      "device_type": "light",
      "permission": "control",
      "accessible": true
    },
    {
      "id": "device-uuid-2",
      "name": "Living Room Light",
      "device_type": "light",
      "permission": "read",
      "accessible": true
    }
  ]
}
```

**Объяснение ключевых полей**

- **permission** — уровень доступа:
  - `read` — только просмотр состояния и истории, без возможности управления
  - `control` — просмотр и управление (отправка команд), но без изменения конфигурации
  - `admin` — полный доступ, включая управление разрешениями других пользователей
- **user_id** — ID пользователя, которому предоставляется доступ
- **group_id** — ID группы для массового предоставления доступа
- **granted_at** — время предоставления разрешения
- **accessible** — флаг, указывающий, доступно ли устройство для пользователя в данный момент

---

## Дополнительная информация

### Обработка ошибок

Все API endpoints возвращают следующие HTTP статус-коды:
- `200` — Успешный запрос (GET, PUT)
- `201` — Успешное создание ресурса (POST)
- `202` — Асинхронная операция принята (синхронизация, команды)
- `204` — Успешное удаление (DELETE)
- `400` — Ошибка валидации параметров
- `401` — Ошибка аутентификации (неверный или отсутствующий token)
- `403` — Ошибка авторизации (нет доступа к устройству/действию)
- `404` — Ресурс не найден
- `500` — Ошибка сервера

### Аутентификация

Все запросы требуют заголовок Authorization:
```
Authorization: Bearer {your-platform-token}
```

Token можно получить через UI приложения или API endpoint `/auth/tokens`.

### Rate Limiting

API применяет rate limiting:
- 100 запросов в минуту для неанонимного пользователя
- 10 запросов в минуту для анонимного пользователя

При превышении лимита возвращается `429 Too Many Requests`.

### Версионирование API

Все примеры используют API v1 (`/api/v1/`). При выпуске новых версий старые версии будут продолжать работать с уведомлениями об устаревании.

---

**Версия документа**: 1.0
**Последнее обновление**: 2026-09-29
**Статус**: Руководство завершено

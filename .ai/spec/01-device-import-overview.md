# Спецификация: Добавление устройств из Home Assistant в манифест

## 1. Обзор фичи

### 1.1. Цель
Позволить пользователю подключить платформу к экземпляру **Home Assistant**, получить список устройств и сущностей, выбрать нужные устройства и добавить их в **манифест** платформы умного дома.

### 1.2. Бизнес-ценность
- **Быстрый онбординг**: не нужно вручную описывать каждое устройство
- **Единый манифест дома** как источник истины для платформы
- **Основа для коммерческого использования**: клиент подключает свой HA и получает управляемый умный дом
- **Хороший контекст для LLM/AI**: устройства, комнаты, возможности, имена, зоны

### 1.3. Основные пользовательские сценарии

#### Сценарий 1: Первый импорт устройств
1. Пользователь открывает раздел «Устройства» в Web UI
2. Нажимает «Подключить Home Assistant»
3. Вводит адрес HA и токен
4. Проверяет подключение
5. Запускает обнаружение устройств
6. Видит список устройств, сгруппированных по комнатам/доменам
7. Выбирает нужные устройства
8. Нажимает «Добавить в манифест»
9. Видит результат: сколько устройств добавлено, сколько пропущено, какие были конфликты

#### Сценарий 2: Повторный импорт (идемпотентность)
При повторном импорте система:
- Не создаёт дубли
- Обновляет метаданные существующих устройств
- Показывает статусы: `new`, `updated`, `skipped`, `conflict`, `error`

#### Сценарий 3: Сухой прогон (dry-run)
- Система показывает, что будет добавлено/обновлено
- Манифест не изменяется

#### Сценарий 4: Частичный импорт
Пользователь выбирает только:
- Свет, выключатели, климат, шторы, замки
- Датчики движения/температуры
- Не импортирует технические сущности типа `sensor.cpu_temperature`

---

## 2. Границы фичи

### 2.1. Входит в фичу (MVP)
1. ✅ Подключение к экземпляру Home Assistant (WebSocket)
2. ✅ Проверка соединения
3. ✅ Получение списка areas, devices, entities
4. ✅ Преобразование данных HA в модель манифеста
5. ✅ Выбор устройств пользователем (Web UI)
6. ✅ Добавление устройств в манифест
7. ✅ Идемпотентный повторный импорт
8. ✅ Отображение результата импорта
9. ✅ Поддержка `dry-run`
10. ✅ Логирование, аудит и обработка ошибок

### 2.2. Не входит в первую версию
1. ❌ Полная двусторонняя синхронизация
2. ❌ Автоматическое удаление устройств из манифеста при удалении из HA
3. ❌ Импорт автоматизаций
4. ❌ Импорт сцен
5. ❌ Импорт скриптов
6. ❌ Импорт энергопотребления и истории
7. ❌ Редактирование устройств в HA через платформу
8. ❌ Enterprise UI для управления секретами

**Но архитектура должна учитывать будущую синхронизацию.**

---

## 3. Текущее состояние проекта

### 3.1. Реализовано
- ✅ Service обнаружения устройств с фильтрацией и пагинацией (`DeviceDiscoveryService`)
- ✅ Классификация устройств (`DeviceClassifier`)
- ✅ Web UI `/discovery` endpoint
- ✅ Bulk apply с dry-run режимом
- ✅ Auto-apply для света/климата/вентиляции
- ✅ Hot reload и backup манифеста
- ✅ WebSocket подключение к HA (`HAAdapter`)

### 3.2. Отличия от целевой спецификации
| Компонент | Текущее состояние | Целевое состояние |
|-----------|------------------|-------------------|
| **Модель данных** | Упрощённая (rooms, devices, sensors) | Расширенная (origin, external_ids, capabilities, sync_info) |
| **Идемпотентность** | Отсутствует | Через `externalIds.homeAssistantDeviceId` |
| **HA Gateway интерфейс** | Отсутствует | `HomeAssistantGateway` с методами `get_areas()`, `get_devices()`, `get_entities()` |
| **Менеджер подключений** | Отсутствует | Хранение подключений с credentialRef |
| **Статусы импорта** | Отсутствуют | `new`, `updated`, `skipped`, `conflict`, `error` |
| **Маппинг domain → capabilities** | Упрощённый | Расширенный с supports metadata |

---

## 4. Архитектурные решения (ADR)

### ADR-1: Использовать Home Assistant API как адаптер

**Решение**: Создать порт `HomeAssistantGateway` с реализацией `HttpHomeAssistantGateway`.

```python
class HomeAssistantGateway(Protocol):
    async def ping(self) -> HAConnectionStatus: ...
    async def get_areas(self) -> list[HAArea]: ...
    async def get_devices(self) -> list[HADevice]: ...
    async def get_entities(self) -> list[HAEntity]: ...
```

**Преимущества**:
- Подмена HA моками в тестах
- Возможность замены способа подключения
- Будущее расширение (cloud connector, локальный агент)

**Статус**: ⏳ Требуется реализация

---

### ADR-2: Импорт должен быть идемпотентным

**Решение**: Устройство в манифесте должно иметь стабильный внешний идентификатор:

```yaml
devices:
  - id: device_ha_a1b2c3
    origin: home_assistant
    externalIds:
      homeAssistantDeviceId: a1b2c3
    sync:
      lastImportedAt: "2026-01-15T10:30:00Z"
      status: ok
```

**Правила**:
- Если устройство с таким `homeAssistantDeviceId` уже есть — обновляем метаданные
- Если нет — создаём
- Никогда не создаём дубль

**Статус**: ⏳ Требуется расширение модели Manifest

---

### ADR-3: Секреты не должны попадать в манифест

**Решение**:
- Манифест не содержит токены, пароли, приватные ключи
- Хранится только ссылка на подключение: `integrationRef: ha_main`
- Секреты хранятся отдельно:
  - В `.env` для локальной разработки
  - В secret manager / vault для продакшена
  - В зашифрованном виде в БД (если подключение через UI)

**Текущее состояние**: Токены передаются в `HAAdapter` напрямую, но не сохраняются в манифесте ✅

**Статус**: ⚠️ Требуется менеджер подключений для enterprise-версии

---

### ADR-4: Импорт является операцией над манифестом, а не прямой синхронизацией

**Решение**:
- Первая версия: добавляет устройства, обновляет метаданные, не удаляет автоматически
- Если устройство удалено из HA, оно помечается как `syncStatus: missing_in_source`
- Удаление из манифеста — только отдельное пользовательское действие

**Статус**: ⏳ Требуется реализация статусов синхронизации

---

### ADR-5: Для файловых манифестов использовать генерируемые и пользовательские секции

**Решение**: Разделить файлы на:
```text
manifest/
  manifest.yaml              # Основная конфигурация (ручное редактирование)
  generated/
    home-assistant-main.devices.yaml  # Автогенерируемые устройства
  overrides/
    home-assistant-main.devices.yaml  # Пользовательские переопределения
```

**Альтернатива**: Использовать маркеры в YAML:
```yaml
# >>> AUTO-GENERATED: home-assistant ha_main >>>
devices:
  ...
# <<< AUTO-GENERATED: home-assistant ha_main <<<
```

**Статус**: ⏳ Требуется обсуждение архитектуры

---

## 5. Доменная модель

### 5.1. Подключение к Home Assistant

```python
class HomeAssistantConnection(BaseModel):
    id: str  # e.g., "ha_main"
    name: str  # e.g., "Мой дом"
    base_url: str  # e.g., "http://192.168.1.10:8123"
    verify_ssl: bool = True
    credential_ref: str  # e.g., "secret://ha_main_token"
    created_at: datetime
    updated_at: datetime
    status: Literal["unknown", "ok", "error"] = "unknown"
```

---

### 5.2. Зоны / комнаты из HA

```python
class HAArea(BaseModel):
    area_id: str
    name: str
    aliases: list[str] = []
```

---

### 5.3. Устройства из HA

```python
class HADevice(BaseModel):
    id: str
    config_entries: list[str] = []
    identifiers: list[tuple[str, str]] = []
    manufacturer: str | None = None
    model: str | None = None
    name: str | None = None
    name_by_user: str | None = None
    area_id: str | None = None
    sw_version: str | None = None
    hw_version: str | None = None
    serial_number: str | None = None
    disabled_by: str | None = None
```

---

### 5.4. Сущности из HA

```python
class HAEntity(BaseModel):
    entity_id: str
    unique_id: str | None = None
    device_id: str | None = None
    platform: str | None = None
    domain: str
    name: str | None = None
    original_name: str | None = None
    friendly_name: str | None = None
    entity_category: Literal["config", "diagnostic"] | None = None
    disabled_by: str | None = None
    hidden_by: str | None = None
    area_id: str | None = None
    device_class: str | None = None
    unit_of_measurement: str | None = None
    supported_features: int | None = None
    capabilities: dict[str, Any] = {}
```

---

### 5.5. Устройство в манифесте (расширенное)

```python
class ManifestDevice(BaseModel):
    id: str
    name: str
    area_id: str | None = None
    origin: Literal["home_assistant", "manual", "imported"]
    source_connection_id: str | None = None
    external_ids: dict[str, str] = {}  # {"homeAssistantDeviceId": "a1b2c3"}
    manufacturer: str | None = None
    model: str | None = None
    software_version: str | None = None
    capabilities: list[ManifestCapability] = []
    ai: dict[str, Any] = {}  # description, aliases, visibility, controllability
    sync: dict[str, Any] = {}  # lastImportedAt, status
```

---

### 5.6. Возможность устройства

```python
class ManifestCapability(BaseModel):
    id: str
    type: Literal[
        "light",
        "switch",
        "climate",
        "cover",
        "lock",
        "fan",
        "sensor",
        "binary_sensor",
        "media_player",
        "vacuum",
        "button",
        "scene",
        "generic",
    ]
    entity_ids: list[str]
    home_assistant_domain: str | None = None
    device_class: str | None = None
    supports: dict[str, bool | str | number] = {}
    metadata: dict[str, Any] = {}
```

---

## 6. Маппинг Home Assistant → манифест

### 6.1. Комнаты

**Из HA**:
```json
{"area_id": "living_room", "name": "Гостиная"}
```

**В манифест**:
```yaml
areas:
  - id: living_room
    name: Гостиная
    origin: home_assistant
    externalIds:
      homeAssistantAreaId: living_room
```

**Правила**:
- Если комната с таким `homeAssistantAreaId` уже есть — не дублируем
- Если имя изменилось — обновляем имя (если пользователь не переопределил вручную)
- Если комната без устройств — по умолчанию не импортируем (но можно сохранить для полноты)

---

### 6.2. Устройства

**Из HA**:
```json
{
  "id": "a1b2c3",
  "name_by_user": "Люстра",
  "name": "IKEA Tradfri bulb",
  "area_id": "living_room",
  "manufacturer": "IKEA",
  "model": "LED1624G9"
}
```

**В манифест**:
```yaml
devices:
  - id: device_ha_a1b2c3
    name: Люстра
    area: living_room
    origin: home_assistant
    manufacturer: IKEA
    model: LED1624G9
    externalIds:
      homeAssistantDeviceId: a1b2c3
```

**Приоритет имени устройства**:
1. `name_by_user`
2. `name`
3. Имя первой основной сущности
4. Сгенерированное имя из `device_id`

---

### 6.3. Сущности → возможности

| Домен HA | Тип в манифесте | Комментарий |
|----------|-----------------|-------------|
| `light` | `light` | Управление светом |
| `switch` | `switch` | Розетки, реле |
| `climate` | `climate` | Термостаты, обогреватели, кондиционеры |
| `cover` | `cover` | Шторы, ворота, жалюзи |
| `lock` | `lock` | Замки |
| `fan` | `fan` | Вентиляторы |
| `sensor` | `sensor` | Измерительные датчики |
| `binary_sensor` | `binary_sensor` | Бинарные датчики |
| `media_player` | `media_player` | Медиа |
| `vacuum` | `vacuum` | Пылесосы |
| `button` | `button` | Кнопки действий |
| `scene` | `scene` | Сцены (если решим поддерживать) |
| остальное | `generic` | Технический режим |

---

### 6.4. Пример маппинга света

**Данные из HA**:
```json
{
  "entity_id": "light.living_room",
  "domain": "light",
  "friendly_name": "Люстра",
  "supported_features": 44,
  "device_class": "light"
}
```

**Манифест**:
```yaml
capabilities:
  - id: capability_light_living_room
    type: light
    entityIds:
      - light.living_room
    homeAssistantDomain: light
    supports:
      onOff: true
      brightness: true
      colorTemperature: true
      color: false
      effect: false
```

---

## 7. Требования к идентификации и стабильности

### 7.1. Идентификатор устройства

Для устройств из HA используем:
```yaml
externalIds:
  homeAssistantDeviceId: abc123
```

Внутренний `id` устройства должен быть стабильным.

**Рекомендуемый формат**:
```
device_ha_{homeAssistantDeviceId}
```

Или глобально уникальный:
```
urn:smart-home:ha:{connectionId}:{deviceId}
```

Пример:
```
urn:smart-home:ha:ha_main:a1b2c3
```

---

### 7.2. Идентификатор сущности

Для сущностей используем:
1. `unique_id` из entity registry (если доступен)
2. `entity_id` как fallback
3. Пару `device_id + entity_id` как дополнительный контекст

**Важно**: `entity_id` может изменяться пользователем в HA, поэтому при наличии `unique_id` используем его для идемпотентности.

---

## 8. UX требования

### 8.1. Экран подключения к Home Assistant

**Поля**:
- Название подключения (например, `Мой дом`)
- URL Home Assistant (например, `http://192.168.1.10:8123`)
- Токен доступа
- Опция «Проверять SSL»
- Опция «Использовать только для чтения»

**Кнопки**:
- `Проверить подключение`
- `Сохранить`
- `Отмена`

**Валидация**:
- Корректный URL
- Токен не пустой
- Соединение доступно
- Токен валиден
- Пользователь имеет права на чтение

**Ошибки**:
- «Не удалось подключиться к Home Assistant. Проверьте URL и доступность сети.»
- «Токен недействителен или отозван.»
- «Сертификат не может быть проверен. Если вы используете самоподписанный сертификат, разрешите это явно в настройках подключения.»

---

### 8.2. Экран обнаружения устройств

После подключения пользователь нажимает:
> «Найти устройства»

Система показывает прогресс:
1. Подключение…
2. Получение списка комнат…
3. Получение списка устройств…
4. Получение списка сущностей…
5. Формирование списка устройств…

---

### 8.3. Экран выбора устройств

Отображается список устройств:
- Чекбокс
- Название
- Комната
- Тип
- Производитель
- Модель
- Количество сущностей
- Статус: новое / уже в манифесте / изменено / конфликт

**Фильтры**:
- По комнате
- По типу: свет, выключатель, климат, датчик, замок, шторы и т.д.
- По статусу: новые / существующие / конфликтные
- Текстовый поиск

**Действия**:
- Выбрать всё
- Выбрать все в комнате
- Снять всё
- Выбрать только новые
- Выбрать только свет
- Выбрать только датчики

---

### 8.4. Предпросмотр импорта

Перед импортом пользователь видит:
```text
Будет добавлено: 12 устройств
Будет обновлено: 3 устройства
Будет пропущено: 5 устройств
Ошибок: 0
```

Для каждого устройства:
- Имя
- Действие
- Причина пропуска
- Изменения

---

### 8.5. Результат импорта

После импорта:
```text
Импорт завершён успешно.
Добавлено: 12
Обновлено: 3
Пропущено: 5
```

И кнопки:
- `Открыть манифест`
- `Открыть список устройств`
- `Импортировать ещё`

---

## 9. План реализации

### Фаза 1: Расширение модели данных (неделя 1)
1. ✅ Расширить `Manifest` модель в `/workspace/src/core/models/manifest.py`:
   - Добавить поле `origin` в `DeviceConfig`
   - Добавить поле `external_ids` в `DeviceConfig`
   - Добавить поле `sync_info` в `DeviceConfig`
   - Опционально: добавить `areas` как отдельную секцию

2. ✅ Обновить `ManifestModel` в `/workspace/src/webui/models.py` для соответствия

---

### Фаза 2: Home Assistant Gateway (неделя 1-2)
1. ⏳ Создать интерфейс `HomeAssistantGateway` в `/workspace/src/adapters/ha_gateway.py`
2. ⏳ Реализовать методы:
   - `ping()`
   - `get_areas()`
   - `get_devices()`
   - `get_entities()`
3. ⏳ Интегрировать с текущим `HAAdapter`

---

### Фаза 3: Менеджер подключений (неделя 2)
1. ⏳ Создать `ConnectionManager` для хранения подключений
2. ⏳ Реализовать хранение секретов (credentialRef)
3. ⏳ Добавить API для CRUD операций над подключениями

---

### Фаза 4: Импорт устройств (неделя 2-3)
1. ⏳ Создать `DeviceImporter` сервис
2. ⏳ Реализовать логику идемпотентности через externalIds
3. ⏳ Реализовать маппинг domain → capabilities
4. ⏳ Реализовать статусы импорта (new, updated, skipped, conflict, error)
5. ⏳ Добавить dry-run режим

---

### Фаза 5: Web UI (неделя 3-4)
1. ⏳ Расширить `/discovery` endpoint для поддержки импорта
2. ⏳ Добавить экран подключения к HA
3. ⏳ Добавить экран выбора устройств
4. ⏳ Добавить предпросмотр и результат импорта

---

### Фаза 6: CLI (неделя 4)
1. ⏳ Добавить команду `smart-home import-devices`
2. ⏳ Поддержка dry-run режима
3. ⏳ Поддержка фильтров и селекторов

---

### Фаза 7: Тестирование и документация (неделя 4-5)
1. ⏳ Написать unit-тесты для `DeviceImporter`
2. ⏳ Написать integration-тесты с моками HA
3. ⏳ Обновить документацию
4. ⏳ Провести code review

---

## 10. Риски и проблемы

### 10.1. Потенциальные конфликты идентификаторов
**Риск**: Устройства из разных HA могут иметь одинаковые ID
**Решение**: Использовать составной ключ `{connectionId}:{deviceId}`

---

### 10.2. Отсутствие версионирования манифеста
**Риск**: При обновлении схемы манифеста старые файлы станут несовместимы
**Решение**: Добавить поле `version` и миграции

---

### 10.3. Сложный UX для массового импорта (200+ устройств)
**Риск**: Пользователь не сможет эффективно выбрать устройства
**Решение**:
- Пагинация (уже реализовано)
- Фильтры (уже реализовано)
- Автовыбор по категориям (уже реализовано)
- Групповые операции

---

### 10.4. Опция отключения SSL verification
**Риск**: Пользователи могут отключить проверку SSL, что небезопасно
**Решение**:
- Явно предупреждать о рисках
- Требовать подтверждения
- Логировать использование

---

## 11. Метрики успеха

### 11.1. Технические метрики
- Время импорта 100 устройств: < 5 секунд
- Время импорта 500 устройств: < 30 секунд
- Идемпотентность: 100% повторных импортов не создают дубли
- Ошибки импорта: < 1% от общего числа устройств

---

### 11.2. Пользовательские метрики
- Время от подключения до импорта: < 5 минут
- Успешность первого импорта: > 90%
- NPS фичи: > 8/10

---

## 12. Ссылки

- Исходный spec: `.ai/enhancements/28-add-devices.md`
- Текущая реализация discovery: `/workspace/src/core/discovery/`
- Web UI routes: `/workspace/src/webui/routes_discovery.py`
- HA Adapter: `/workspace/src/adapters/ha_adapter.py`
- Manifest models: `/workspace/src/core/models/manifest.py`

---

## 13. Следующие шаги

1. **Создать детальные спецификации для каждой фазы** (отдельные файлы в `.ai/spec/`)
2. **Начать с Фазы 1**: Расширение модели данных
3. **Параллельно**: Обсудить архитектуру менеджера подключений

---

*Документ создан: 2026-01-15*
*Версия: 1.0*
*Статус: Черновик*

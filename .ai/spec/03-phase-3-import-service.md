# Фаза 3: Сервис импорта устройств из Home Assistant

## Цель
Реализовать сервис для импорта устройств из Home Assistant в манифест платформы с поддержкой идемпотентности, маппинга доменов и статусов импорта.

## Область применения
- Сервис `DeviceImportService` для бизнес-логики импорта
- Маппинг доменов HA → capabilities устройств платформы
- CLI команда `smart-home import-devices`
- Интеграция с Web UI через `/api/import` endpoint

## Доменная модель

### DeviceImportResult
```python
@dataclass
class DeviceImportResult:
    """Результат импорта одного устройства."""

    device_id: str
    device_name: str
    status: Literal["new", "updated", "skipped", "error"]
    message: str | None = None
    external_ids: dict[str, str] | None = None
    capabilities: list[str] | None = None
```

### ImportSummary
```python
@dataclass
class ImportSummary:
    """Сводка импорта."""

    total: int
    new: int
    updated: int
    skipped: int
    errors: int
    devices: list[DeviceImportResult]
    dry_run: bool
    timestamp: datetime
```

## Интерфейс сервиса

```python
class DeviceImportService:
    """Сервис импорта устройств из Home Assistant."""
    
    def __init__(
        self,
        ha_adapter: HAAdapter,
        manifest_manager: ManifestManager,
        domain_mapper: DomainMapper | None = None,
    ):
        self.ha_adapter = ha_adapter
        self.manifest_manager = manifest_manager
        self.domain_mapper = domain_mapper or DomainMapper()
    
    async def import_devices(
        self,
        instance_id: str,
        area_id: str | None = None,
        dry_run: bool = False,
        include_technical: bool = False,
    ) -> ImportSummary:
        """
        Импортировать устройства из HA в манифест.
        
        Args:
            instance_id: ID экземпляра HA в манифесте
            area_id: Опционально, импорт только из конкретной области
            dry_run: Если True, не сохранять изменения
            include_technical: Включать технические сущности (сенсоры, binary_sensor)
        
        Returns:
            ImportSummary с результатами импорта
        """
```

## Маппинг доменов

### DomainMapper
```python
class DomainMapper:
    """Маппинг доменов Home Assistant в capabilities платформы."""
    
    # Базовые домены для импорта
    PRIMARY_DOMAINS = {
        "light": ["light"],
        "switch": ["switch"],
        "cover": ["cover"],
        "climate": ["climate"],
        "fan": ["fan"],
        "lock": ["lock"],
        "siren": ["siren"],
        "scene": ["scene"],
        "button": ["button"],
        "input_boolean": ["switch"],
        "input_button": ["button"],
        "input_select": ["select"],
    }
    
    # Технические домены (импортируются только если include_technical=True)
    TECHNICAL_DOMAINS = {
        "sensor": ["sensor"],
        "binary_sensor": ["binary_sensor"],
        "number": ["number"],
        "select": ["select"],
        "text": ["text"],
        "date": ["date"],
        "datetime": ["datetime"],
        "time": ["time"],
    }
    
    # Исключаемые домены
    EXCLUDED_DOMAINS = {
        "automation",
        "script",
        "zone",
        "person",
        "device_tracker",
        "geo_location",
        "sun",
        "weather",
        "map",
        "camera",
        "image",
        "media_player",  # Требует специального handling
        "remote",
        "stt",
        "tts",
        "notify",
    }
    
    def get_capabilities(self, entity_domain: str) -> list[str]:
        """
        Получить capabilities для домена сущности.
        
        Args:
            entity_domain: Домен сущности HA (e.g., 'light', 'switch')
        
        Returns:
            Список capabilities платформы
        """
    
    def should_import_entity(
        self,
        entity_domain: str,
        include_technical: bool = False,
    ) -> bool:
        """
        Проверить, следует ли импортировать сущность данного домена.
        
        Args:
            entity_domain: Домен сущности
            include_technical: Включать ли технические домены
        
        Returns:
            True если сущность должна быть импортирована
        """
    
    def is_primary_device(self, entity_domain: str) -> bool:
        """
        Проверить, является ли домен основным устройством.
        
        Основные устройства создаются как отдельные devices в манифесте.
        Технические сущности добавляются как capabilities к существующим устройствам.
        """
```

## Алгоритм импорта

### Пошаговый процесс

1. **Получение данных из HA**
   ```python
   areas = await ha_adapter.get_areas()
   devices = await ha_adapter.get_devices(area_id=area_id)
   entities = await ha_adapter.get_entities()
   entity_states = await ha_adapter.get_entity_states()
   ```

2. **Группировка сущностей по устройствам**
   ```python
   device_entities = defaultdict(list)
   for entity in entities:
       if entity.device_id:
           device_entities[entity.device_id].append(entity)
   ```

3. **Обработка каждого устройства**
   ```python
   for ha_device in devices:
       # Проверка на существование через external_ids
       existing = manifest.find_device_by_external_id(
           origin="home_assistant", external_id=ha_device.id
       )

       if existing:
           status = "updated" if has_changes else "skipped"
       else:
           status = "new"

       # Маппинг доменов в capabilities
       capabilities = []
       for entity in device_entities[ha_device.id]:
           if domain_mapper.should_import_entity(entity.domain, include_technical):
               caps = domain_mapper.get_capabilities(entity.domain)
               capabilities.extend(caps)

       # Создание/обновление устройства в манифесте
       device_config = DeviceConfig(
           id=generate_device_id(ha_device),
           name=ha_device.name or ha_device.area_name,
           room=ha_device.area_name,
           origin=DeviceOrigin(
               source="home_assistant",
               instance_id=instance_id,
           ),
           external_ids={
               "home_assistant": ha_device.id,
           },
           capabilities=capabilities,
       )
   ```

4. **Приоритет имен**
   - Если у устройства есть `name` → использовать его
   - Иначе если есть сущности → использовать имя первой сущности
   - Иначе использовать `area_name` + тип устройства

5. **Идемпотентность**
   - Поиск устройства по `external_ids.home_assistant`
   - Если найдено → обновить только изменившиеся поля
   - Если не найдено → создать новое устройство

## CLI команда

### Команда import-devices

```bash
smart-home import-devices [OPTIONS] INSTANCE_ID

Args:
    INSTANCE_ID: ID экземпляра Home Assistant в манифесте

Options:
    --area, -a AREA_ID      Импортировать только из конкретной области
    --dry-run, -n           Показать что будет импортировано без сохранения
    --include-technical     Включать технические сущности (сенсоры)
    --output, -o FILE       Сохранить результат в файл
    --verbose, -v           Подробный вывод
```

### Примеры использования

```bash
# Dry-run импорт всех устройств
smart-home import-devices home-main --dry-run

# Импорт только из гостиной
smart-home import-devices home-main --area living_room

# Импорт с техническими сенсорами
smart-home import-devices home-main --include-technical

# Сохранение отчета
smart-home import-devices home-main --dry-run --output import-report.json
```

## Web UI Integration

### API Endpoint

```python
@router.post("/api/import/devices")
async def import_devices(
    instance_id: str,
    area_id: str | None = None,
    dry_run: bool = False,
    include_technical: bool = False,
) -> ImportSummary:
    """Импортировать устройства из Home Assistant."""
```

### UI Компоненты

1. **Кнопка импорта** на странице /discovery
2. **Модальное окно** с настройками импорта:
   - Выбор области (dropdown)
   - Checkbox "Dry run"
   - Checkbox "Include technical entities"
3. **Таблица результатов** после импорта:
   - Статусы (new/updated/skipped/error)
   - Имена устройств
   - Capabilities
4. **Прогресс бар** для длительных операций

## Обработка ошибок

### Типы ошибок

1. **ConnectionError**: Нет соединения с HA
   - Решение: Повторить подключение, вернуть ошибку пользователю

2. **ManifestNotFoundError**: Манифест не найден
   - Решение: Создать новый манифест или вернуть ошибку

3. **DuplicateDeviceError**: Устройство с таким external_id уже существует
   - Решение: Обновить существующее устройство

4. **MappingError**: Неизвестный домен HA
   - Решение: Логировать предупреждение, пропустить сущность

### Логирование

```python
logger.info(f"Import started for instance {instance_id}")
logger.debug(f"Found {len(devices)} devices in HA")
logger.info(f"Import complete: {summary.new} new, {summary.updated} updated")
logger.error(f"Failed to import device {device_id}: {error}")
```

## Тестирование

### Unit тесты

1. **DomainMapper тесты**
   - Маппинг основных доменов
   - Маппинг технических доменов
   - Исключение доменов
   - Проверка should_import_entity()

2. **DeviceImportService тесты**
   - Импорт новых устройств
   - Обновление существующих устройств
   - Skip неизмененных устройств
   - Dry run режим
   - Обработка ошибок

3. **CLI тесты**
   - Парсинг аргументов
   - Вывод результатов
   - Сохранение в файл

### Integration тесты

1. Импорт из реального HA (требует тестового инстанса)
2. Идемпотентность (двойной импорт)
3. Конфликты имен устройств

## Критерии приемки

- [ ] Сервис импортирует устройства из HA в манифест
- [ ] Поддержка dry-run режима
- [ ] Идемпотентность через external_ids
- [ ] Маппинг доменов HA → capabilities
- [ ] Фильтрация технических сущностей
- [ ] CLI команда с полным набором опций
- [ ] Web UI integration (endpoint + компоненты)
- [ ] Обработка ошибок и логирование
- [ ] Все тесты проходят (unit + integration)
- [ ] Документация обновлена

## Зависимости

- Фаза 1: Расширенная модель манифеста ✅
- Фаза 2: Методы HA Adapter ✅
- Веб-сервер для API endpoint
- ManifestManager для работы с манифестом

## Следующие шаги

После реализации Фазы 3:
- Фаза 4: Менеджер подключений
- Фаза 5: Улучшенный маппинг capabilities
- Фаза 6: Двусторонняя синхронизация (опционально)
- Фаза 7: Импорт автоматизаций (опционально)

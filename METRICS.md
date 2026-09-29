# Метрики Prometheus для системы интеграции устройств

## Обзор

Система мониторинга интеграции устройств сбора метрик Prometheus для отслеживания производительности, надежности и здоровья системы управления устройствами Home Assistant.

Все метрики экспортируются на HTTP endpoint `/metrics` и доступны для сбора Prometheus сервером.

## Архитектура

### MetricsCollector

Основной класс `MetricsCollector` находится в `/src/core/metrics.py` и:
- Инициализирует все метрики при запуске приложения
- Предоставляет методы для записи метрик
- Обрабатывает случаи, когда `prometheus_client` не установлен (graceful degradation)

### Интеграция с DeviceService

Класс `DeviceService` (`/src/services/device_service.py`) автоматически:
- Получает глобальный экземпляр `MetricsCollector`
- Записывает метрики при выполнении операций
- Обновляет gauge метрики при изменениях состояния

### HTTP Endpoint

`MetricsServer` (`/src/services/metrics_server.py`) предоставляет:
- **GET /metrics** - экспорт всех метрик в формате Prometheus
- **GET /health** - проверка статуса сервера метрик

## Метрики

Все метрики используют namespace `device_integration_` для четкой организации.

### 1. Метрики времени синхронизации (Histogram)

#### `device_integration_device_sync_duration_seconds`
**Описание:** Время синхронизации отдельного устройства в секундах.

**Тип:** Histogram

**Labels:**
- `source_id` - Идентификатор источника (UUID устройства)
- `device_type` - Тип устройства (light, switch, sensor и т.д.)

**Buckets:** 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0 сек

**Пример использования:**
```python
metrics.record_device_sync_duration(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    device_type="light",
    duration_seconds=0.45
)
```

**PromQL примеры:**
```promql
# Среднее время синхронизации устройства
rate(device_integration_device_sync_duration_seconds_sum[5m]) / 
rate(device_integration_device_sync_duration_seconds_count[5m])

# P95 время синхронизации
histogram_quantile(0.95, device_integration_device_sync_duration_seconds_bucket)
```

---

#### `device_integration_source_sync_total_seconds`
**Описание:** Общее время синхронизации для всех устройств источника в секундах.

**Тип:** Histogram

**Labels:**
- `source_id` - Идентификатор источника

**Buckets:** 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0 сек

**Пример использования:**
```python
metrics.record_source_sync_duration(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    total_duration_seconds=2.35
)
```

---

### 2. Метрики команд (Counter)

#### `device_integration_device_commands_total`
**Описание:** Общее количество отправленных команд на устройства.

**Тип:** Counter (возрастающий)

**Labels:**
- `source_id` - ID источника
- `device_type` - Тип устройства
- `command_type` - Тип команды (turn_on, turn_off и т.д.)

**Пример использования:**
```python
metrics.record_command_sent(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    device_type="light",
    command_type="turn_on"
)
```

---

#### `device_integration_device_commands_success`
**Описание:** Количество успешно выполненных команд.

**Тип:** Counter

**Labels:** То же самое, что у `device_commands_total`

**Пример использования:**
```python
metrics.record_command_success(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    device_type="light",
    command_type="turn_on"
)
```

---

#### `device_integration_device_commands_failed`
**Описание:** Количество неудачных команд с указанием типа ошибки.

**Тип:** Counter

**Labels:**
- `source_id` - ID источника
- `device_type` - Тип устройства
- `command_type` - Тип команды
- `error_type` - Тип ошибки (timeout, ConnectionError и т.д.)

**Пример использования:**
```python
metrics.record_command_failed(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    device_type="light",
    command_type="turn_on",
    error_type="timeout"
)
```

**PromQL примеры:**
```promql
# Процент ошибок команд
rate(device_integration_device_commands_failed[5m]) /
rate(device_integration_device_commands_total[5m])

# Частые ошибки
topk(10, sum by (error_type) 
    (rate(device_integration_device_commands_failed[5m])))
```

---

### 3. Метрики ошибок (Counter)

#### `device_integration_device_connection_errors_total`
**Описание:** Общее количество ошибок соединения с источниками.

**Тип:** Counter

**Labels:**
- `source_id` - ID источника
- `error_type` - Тип ошибки (timeout, refused, dns_failed и т.д.)

**Пример использования:**
```python
metrics.record_connection_error(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    error_type="timeout"
)
```

---

#### `device_integration_device_sync_errors_total`
**Описание:** Общее количество ошибок при синхронизации.

**Тип:** Counter

**Labels:**
- `source_id` - ID источника
- `error_type` - Тип ошибки (invalid_response, parse_error и т.д.)

**Пример использования:**
```python
metrics.record_sync_error(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    error_type="invalid_response"
)
```

**PromQL примеры:**
```promql
# Частота ошибок синхронизации
rate(device_integration_device_sync_errors_total[5m])

# Частые причины ошибок
topk(5, sum by (error_type) 
    (rate(device_integration_device_sync_errors_total[5m])))
```

---

### 4. Метрики состояния устройств (Gauge)

#### `device_integration_devices_available`
**Описание:** Текущее количество доступных устройств.

**Тип:** Gauge (может возрастать или убывать)

**Labels:**
- `source_id` - ID источника
- `device_type` - Тип устройства

**Пример использования:**
```python
metrics.set_devices_available(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    device_type="light",
    count=5
)
```

---

#### `device_integration_devices_unavailable`
**Описание:** Текущее количество недоступных устройств.

**Тип:** Gauge

**Labels:** То же самое, что у `devices_available`

**Пример использования:**
```python
metrics.set_devices_unavailable(
    source_id="550e8400-e29b-41d4-a716-446655440000",
    device_type="light",
    count=2
)
```

**PromQL примеры:**
```promql
# Процент доступных устройств
device_integration_devices_available /
(device_integration_devices_available + device_integration_devices_unavailable)

# Суммарное количество устройств по типам
sum by (device_type) (device_integration_devices_available)
```

---

#### `device_integration_sources_connected`
**Описание:** Текущее количество подключенных источников.

**Тип:** Gauge

**Labels:** Нет

**Пример использования:**
```python
metrics.set_sources_connected_count(count=3)
```

---

### 5. Метрики кэша (Gauge и Counter)

#### `device_integration_cache_size`
**Описание:** Текущий размер кэша в байтах.

**Тип:** Gauge

**Labels:** Нет

**Пример использования:**
```python
metrics.set_cache_size(size_bytes=1048576)  # 1 МБ
```

---

#### `device_integration_cache_hits`
**Описание:** Количество успешных обращений к кэшу.

**Тип:** Counter

**Labels:**
- `cache_type` - Тип кэша (device, config и т.д.)

**Пример использования:**
```python
metrics.record_cache_hit(cache_type="device")
```

---

#### `device_integration_cache_misses`
**Описание:** Количество неудачных обращений к кэшу.

**Тип:** Counter

**Labels:**
- `cache_type` - Тип кэша

**Пример использования:**
```python
metrics.record_cache_miss(cache_type="device")
```

**PromQL примеры:**
```promql
# Hit rate кэша
rate(device_integration_cache_hits[5m]) /
(rate(device_integration_cache_hits[5m]) + 
 rate(device_integration_cache_misses[5m]))

# Размер кэша в МБ
device_integration_cache_size / 1048576
```

---

## Использование в DeviceService

### Автоматическая запись метрик

DeviceService автоматически записывает метрики в следующих местах:

#### 1. Синхронизация устройств
```python
async def sync_devices_from_source(self, source_id: UUID):
    sync_start_time = time.time()
    try:
        # ... код синхронизации ...
        sync_duration = time.time() - sync_start_time
        self._metrics.record_source_sync_duration(str(source_id), sync_duration)
    except Exception as e:
        self._metrics.record_sync_error(str(source_id), type(e).__name__)
```

#### 2. Выполнение команд
```python
async def execute_command(self, device_id, command_name, ...):
    device = await self.get_device(device_id)
    source_id_str = str(device.source_id)
    device_type = device.device_type
    
    # Запись отправки команды
    self._metrics.record_command_sent(source_id_str, device_type, command_name)
    
    try:
        # ... выполнение команды ...
        # Запись успеха
        self._metrics.record_command_success(source_id_str, device_type, command_name)
    except TimeoutError:
        # Запись ошибки timeout
        self._metrics.record_command_failed(source_id_str, device_type, command_name, "timeout")
```

#### 3. Обновление состояния устройств
```python
async def update_device_state(self, device_id, new_state):
    # ... обновление состояния ...
    # Обновление метрик доступности
    self._update_device_availability_metrics()
```

#### 4. Управление кэшем
```python
# Запись попадания в кэш
device_service.record_cache_hit("device")

# Запись промаха кэша
device_service.record_cache_miss("device")

# Обновление размера кэша
device_service.update_cache_metrics(cache_size_bytes)
```

#### 5. Обновление источников
```python
# Обновление количества подключенных источников
device_service.update_sources_connected_count(count=3)
```

---

## Примеры Prometheus запросов (PromQL)

### Мониторинг производительности

```promql
# Среднее время синхронизации устройства за последние 5 минут
avg(rate(device_integration_device_sync_duration_seconds_sum[5m])) /
avg(rate(device_integration_device_sync_duration_seconds_count[5m]))

# 99-перцентиль времени синхронизации
histogram_quantile(0.99, device_integration_device_sync_duration_seconds_bucket)

# Количество команд в секунду
rate(device_integration_device_commands_total[1m])
```

### Мониторинг надежности

```promql
# Процент успешных команд
rate(device_integration_device_commands_success[5m]) /
rate(device_integration_device_commands_total[5m]) * 100

# Частота ошибок соединения
rate(device_integration_device_connection_errors_total[5m])

# Частота ошибок синхронизации
rate(device_integration_device_sync_errors_total[5m])
```

### Мониторинг состояния

```promql
# Общее количество устройств
device_integration_devices_available + device_integration_devices_unavailable

# Доступность устройств по источникам
sum by (source_id) (device_integration_devices_available) /
(sum by (source_id) (device_integration_devices_available) +
 sum by (source_id) (device_integration_devices_unavailable)) * 100

# Статус подключения источников
device_integration_sources_connected
```

### Мониторинг кэша

```promql
# Эффективность кэша
rate(device_integration_cache_hits[5m]) /
(rate(device_integration_cache_hits[5m]) +
 rate(device_integration_cache_misses[5m]))

# Размер кэша в МБ
device_integration_cache_size / 1048576

# Темп роста кэша
rate(device_integration_cache_size[5m])
```

---

## Интеграция с Prometheus

### Конфигурация scrape job

Добавить в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'smart-home-device-integration'
    static_configs:
      - targets: ['localhost:9090']
    scrape_interval: 15s
    scrape_timeout: 10s
```

### Конфигурация алертов

Пример rules файла `device_integration_alerts.yml`:

```yaml
groups:
  - name: device_integration
    interval: 30s
    rules:
      # Высокая частота ошибок команд
      - alert: HighCommandFailureRate
        expr: |
          (rate(device_integration_device_commands_failed[5m]) /
           rate(device_integration_device_commands_total[5m])) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High command failure rate (>10%)"

      # Много недоступных устройств
      - alert: ManyUnavailableDevices
        expr: |
          (device_integration_devices_unavailable /
           (device_integration_devices_available +
            device_integration_devices_unavailable)) > 0.2
        for: 10m
        labels:
          severity: warning

      # Ошибки соединения
      - alert: ConnectionErrorsDetected
        expr: |
          rate(device_integration_device_connection_errors_total[5m]) > 0
        for: 5m
        labels:
          severity: critical

      # Медленная синхронизация
      - alert: SlowDeviceSync
        expr: |
          histogram_quantile(0.95, device_integration_device_sync_duration_seconds_bucket) > 5
        for: 5m
        labels:
          severity: warning
```

---

## Граф-диаграмма обзор метрик

```
┌─────────────────────────────────────────────────────────┐
│         Device Integration Metrics System                │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ DeviceService                                    │  │
│  │ - execute_command()     ────┐                    │  │
│  │ - sync_devices()        ────┼─→ MetricsCollector│  │
│  │ - update_device_state() ────┤                    │  │
│  │ - handle_state_change() ────┘                    │  │
│  └──────────────────────────────────────────────────┘  │
│                        │                                 │
│                        ↓                                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │ MetricsCollector (get_metrics_collector())        │  │
│  │ - record_device_sync_duration()                  │  │
│  │ - record_source_sync_duration()                  │  │
│  │ - record_command_sent/success/failed()           │  │
│  │ - record_connection/sync_error()                 │  │
│  │ - set_devices_available/unavailable()            │  │
│  │ - set_sources_connected_count()                  │  │
│  │ - set_cache_size()                              │  │
│  │ - record_cache_hit/miss()                        │  │
│  └──────────────────────────────────────────────────┘  │
│                        │                                 │
│                        ↓                                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Prometheus Client Library                        │  │
│  │ (Counters, Histograms, Gauges)                  │  │
│  └──────────────────────────────────────────────────┘  │
│                        │                                 │
│                        ↓                                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │ MetricsServer (/src/services/metrics_server.py) │  │
│  │ GET /metrics  ─→ prometheus_client.generate     │  │
│  │ GET /health                                     │  │
│  └──────────────────────────────────────────────────┘  │
│                        │                                 │
│                        ↓                                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Prometheus Server (9090)                         │  │
│  │ - Scrapes /metrics every 15s                    │  │
│  │ - Stores time-series data                       │  │
│  └──────────────────────────────────────────────────┘  │
│                        │                                 │
│                        ↓                                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Grafana / Alertmanager                          │  │
│  │ - Visualize metrics                             │  │
│  │ - Create alerts                                 │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Лучшие практики

### 1. Инициализация метрик
```python
from src.core.metrics import get_metrics_collector

# При старте приложения
metrics = get_metrics_collector()
metrics.initialize()
```

### 2. Обработка исключений
```python
try:
    metrics.record_command_success(...)
except Exception as e:
    logger.error(f"Error recording metric: {e}")
    # Не прерывать основную логику при ошибке метрик
```

### 3. Выбор правильного типа метрики
- **Counter** - для подсчета событий (команды, ошибки)
- **Histogram** - для времени выполнения (синхронизация)
- **Gauge** - для текущего состояния (доступные устройства)

### 4. Выбор labels
- Не использовать high cardinality labels (например, device_id)
- Использовать source_id и device_type для группировки
- Избегать эффекта "label explosion"

### 5. Документирование метрик
- Описывать назначение каждой метрики
- Указывать unit измерения
- Приводить примеры использования

---

## Troubleshooting

### Метрики не экспортируются

```bash
# Проверить доступность endpoint
curl http://localhost:9090/metrics

# Проверить логи приложения
grep "Initialized metrics" app.log

# Убедиться что prometheus_client установлен
pip list | grep prometheus
```

### Высокие значения cardinality

```promql
# Найти метрики с большим количеством label combinations
count({__name__=~"device_integration_.*"}) by (__name__)
```

### Пропущенные метрики

- Проверить что MetricsCollector.initialize() вызвана
- Убедиться что prometheus_client установлен
- Проверить логи на ошибки инициализации метрик

---

## Версия

**Версия документации:** 1.0
**Дата создания:** 2026-09-29
**Совместимость:** Smart Home Platform v1.0+

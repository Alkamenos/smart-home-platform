# Примеры использования Prometheus метрик

## 1. Инициализация метрик при запуске приложения

### При старте Flask/aiohttp приложения

```python
# main.py или bootstrap.py
from src.core.metrics import get_metrics_collector
from src.services.metrics_server import start_metrics_server

async def main():
    # Инициализируем метрики
    metrics = get_metrics_collector()
    metrics.initialize()
    
    # Запускаем HTTP сервер метрик (порт 9090)
    metrics_server = await start_metrics_server(
        host="0.0.0.0",
        port=9090,
        metrics_collector=metrics
    )
    
    # ... запуск остального приложения ...
    
    # При остановке приложения
    await metrics_server.stop()
```

## 2. Использование метрик в DeviceService

### Автоматическая запись при операциях

```python
from src.services.device_service import DeviceService

# DeviceService автоматически записывает метрики
device_service = DeviceService(
    event_bus=event_bus,
    persistence_module=persistence,
    ha_adapter=ha_adapter
)

# При выполнении команды (метрики записываются автоматически)
response = await device_service.execute_command(
    device_id=device_uuid,
    command_name="turn_on",
    parameters={"brightness": 100}
    # Автоматически записывает:
    # - device_integration_device_commands_total
    # - device_integration_device_commands_success (или _failed)
)

# При синхронизации (метрики записываются автоматически)
devices = await device_service.sync_devices_from_source(source_id)
# Автоматически записывает:
# - device_integration_source_sync_total_seconds
# - device_integration_device_sync_errors_total (при ошибке)
```

## 3. Ручная запись метрик

### Синхронизация устройств с временем

```python
import time
from src.core.metrics import get_metrics_collector

metrics = get_metrics_collector()

# Отслеживаем время синхронизации отдельного устройства
start_time = time.time()
device_data = await fetch_device_data(device_id)
duration = time.time() - start_time

metrics.record_device_sync_duration(
    source_id=str(source_id),
    device_type="light",
    duration_seconds=duration
)
```

### Запись ошибок

```python
from src.core.metrics import get_metrics_collector

metrics = get_metrics_collector()

try:
    result = await connect_to_source(source_id)
except TimeoutError as e:
    metrics.record_connection_error(
        source_id=str(source_id),
        error_type="timeout"
    )
except ConnectionRefusedError as e:
    metrics.record_connection_error(
        source_id=str(source_id),
        error_type="refused"
    )
```

### Обновление состояния устройств

```python
device_service = DeviceService(...)

# После обновления статуса устройства
await device_service.update_device_state(device_id, new_state)

# Обновляем метрики доступности (вызывается автоматически)
device_service._update_device_availability_metrics()

# Или обновляем вручную
device_service.set_devices_available(
    source_id=str(source_id),
    device_type="light",
    count=5  # доступных
)
device_service.set_devices_unavailable(
    source_id=str(source_id),
    device_type="light",
    count=1  # недоступных
)
```

### Работа с кэшем

```python
device_service = DeviceService(...)

# Попадание в кэш при получении устройства
device = device_service._cache.get(device_id)
if device:
    device_service.record_cache_hit("device")
else:
    device_service.record_cache_miss("device")
    # Загружаем из БД
    device = await persistence.load_device(device_id)
    device_service._cache.set(device_id, device)

# Обновляем размер кэша
cache_size = device_service._cache.get_size()
device_service.update_cache_metrics(cache_size)
```

### Обновление источников

```python
device_service = DeviceService(...)

# После получения списка активных источников
connected_sources = await persistence.get_connected_sources()
device_service.update_sources_connected_count(len(connected_sources))
```

## 4. Мониторинг в Prometheus/Grafana

### Запрос: Успешность команд

```promql
# Процент успешных команд по типам устройств
sum(rate(device_integration_device_commands_success[5m])) by (device_type) /
sum(rate(device_integration_device_commands_total[5m])) by (device_type)
```

### Запрос: Скорость синхронизации

```promql
# Гистограмма времени синхронизации (в процентилях)
histogram_quantile(0.95,
  sum(rate(device_integration_device_sync_duration_seconds_bucket[5m])) 
  by (le, source_id)
)
```

### Запрос: Доступность устройств

```promql
# Процент доступных устройств
sum(device_integration_devices_available) by (source_id) /
(sum(device_integration_devices_available) by (source_id) +
 sum(device_integration_devices_unavailable) by (source_id))
```

### Запрос: Анализ ошибок

```promql
# Топ ошибок синхронизации
topk(5,
  sum(rate(device_integration_device_sync_errors_total[5m])) by (error_type)
)
```

## 5. Примеры Grafana дашбордов

### Панель 1: Успешность команд

```json
{
  "title": "Command Success Rate",
  "targets": [
    {
      "expr": "sum(rate(device_integration_device_commands_success[5m])) by (device_type) / sum(rate(device_integration_device_commands_total[5m])) by (device_type)",
      "legendFormat": "{{ device_type }}"
    }
  ],
  "type": "graph",
  "yaxes": [
    {
      "format": "percentunit",
      "label": "Success Rate"
    }
  ]
}
```

### Панель 2: Время синхронизации

```json
{
  "title": "Device Sync Duration (P95)",
  "targets": [
    {
      "expr": "histogram_quantile(0.95, sum(rate(device_integration_device_sync_duration_seconds_bucket[5m])) by (le, source_id))",
      "legendFormat": "{{ source_id }}"
    }
  ],
  "type": "graph",
  "yaxes": [
    {
      "format": "s",
      "label": "Duration"
    }
  ]
}
```

### Панель 3: Доступность устройств

```json
{
  "title": "Device Availability by Source",
  "targets": [
    {
      "expr": "sum(device_integration_devices_available) by (source_id)",
      "legendFormat": "Available - {{ source_id }}"
    },
    {
      "expr": "sum(device_integration_devices_unavailable) by (source_id)",
      "legendFormat": "Unavailable - {{ source_id }}"
    }
  ],
  "type": "graph"
}
```

### Панель 4: Частота ошибок

```json
{
  "title": "Error Rate by Type",
  "targets": [
    {
      "expr": "rate(device_integration_device_sync_errors_total[5m])",
      "legendFormat": "Sync Errors - {{ error_type }}"
    },
    {
      "expr": "rate(device_integration_device_connection_errors_total[5m])",
      "legendFormat": "Connection Errors - {{ error_type }}"
    }
  ],
  "type": "graph"
}
```

## 6. Примеры алертов (Alertmanager)

### Алерт 1: Высокая частота ошибок команд

```yaml
- alert: HighCommandFailureRate
  expr: |
    (sum(rate(device_integration_device_commands_failed[5m])) by (device_type) /
     sum(rate(device_integration_device_commands_total[5m])) by (device_type)) > 0.1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High command failure rate for {{ $labels.device_type }}"
    description: "{{ $labels.device_type }} has {{ $value | humanizePercentage }} failure rate"
```

### Алерт 2: Медленная синхронизация

```yaml
- alert: SlowDeviceSync
  expr: |
    histogram_quantile(0.95,
      sum(rate(device_integration_device_sync_duration_seconds_bucket[5m])) 
      by (le, source_id)
    ) > 5
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Slow device sync detected for {{ $labels.source_id }}"
    description: "P95 sync duration: {{ $value }}s"
```

### Алерт 3: Много недоступных устройств

```yaml
- alert: ManyUnavailableDevices
  expr: |
    (sum(device_integration_devices_unavailable) by (source_id) /
     (sum(device_integration_devices_available) by (source_id) +
      sum(device_integration_devices_unavailable) by (source_id))) > 0.2
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Many devices unavailable for {{ $labels.source_id }}"
    description: "{{ $value | humanizePercentage }} of devices unavailable"
```

### Алерт 4: Ошибки соединения

```yaml
- alert: ConnectionErrorsDetected
  expr: |
    rate(device_integration_device_connection_errors_total[5m]) > 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Connection errors detected for {{ $labels.source_id }}"
    description: "Error type: {{ $labels.error_type }}"
```

## 7. Интеграция с системой мониторинга

### Конфигурация Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'smart-home-device-integration'
    static_configs:
      - targets: ['localhost:9090']
    scrape_interval: 15s
    scrape_timeout: 10s
```

### Конфигурация Grafana Data Source

```json
{
  "type": "prometheus",
  "name": "Smart Home Metrics",
  "url": "http://localhost:9090",
  "access": "proxy",
  "isDefault": true
}
```

## 8. Полный пример: Интеграция в приложение

```python
# app.py
import asyncio
from aiohttp import web
from src.core.metrics import get_metrics_collector
from src.services.metrics_server import start_metrics_server
from src.services.device_service import DeviceService
from src.core.events.event_bus import EventBus

async def init_app():
    """Инициализация приложения с метриками."""
    
    # 1. Инициализируем метрики
    metrics = get_metrics_collector()
    metrics.initialize()
    
    # 2. Запускаем HTTP сервер метрик
    metrics_server = await start_metrics_server(
        host="0.0.0.0",
        port=9090,
        metrics_collector=metrics
    )
    
    # 3. Создаем зависимости
    event_bus = EventBus()
    
    # 4. Создаем DeviceService (автоматически получает метрики)
    device_service = DeviceService(
        event_bus=event_bus,
        persistence_module=persistence,
        ha_adapter=ha_adapter
    )
    
    # 5. Создаем основное приложение
    app = web.Application()
    
    # Маршруты синхронизации
    app.router.add_post('/api/sync/{source_id}', 
                       sync_devices_handler(device_service))
    
    # Маршруты команд
    app.router.add_post('/api/command/{device_id}',
                       execute_command_handler(device_service))
    
    # Сохраняем сервис в app для использования в обработчиках
    app['device_service'] = device_service
    app['metrics_server'] = metrics_server
    
    return app

async def sync_devices_handler(device_service):
    async def handler(request):
        source_id = request.match_info['source_id']
        try:
            devices = await device_service.sync_devices_from_source(source_id)
            return web.json_response({'status': 'ok', 'devices': len(devices)})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    return handler

async def execute_command_handler(device_service):
    async def handler(request):
        device_id = request.match_info['device_id']
        data = await request.json()
        try:
            response = await device_service.execute_command(
                device_id=device_id,
                command_name=data['command'],
                parameters=data.get('parameters', {})
            )
            return web.json_response({'status': 'ok', 'response': response})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
    return handler

if __name__ == '__main__':
    app = asyncio.run(init_app())
    web.run_app(app, host='0.0.0.0', port=8080)
```

## Заключение

Система метрик Prometheus предоставляет:
- **Полный контроль** над производительностью системы
- **Раннее обнаружение** проблем через алерты
- **Визуализацию** данных в Grafana
- **Анализ тренда** использования и нагрузки

Начните с базовых метрик (команды и ошибки), а затем расширьте мониторинг на другие аспекты системы.

# Watchdog Service - Мониторинг состояний FSM

## Назначение
Сервис `pyscript.fsm_watchdog` периодически логирует текущие состояния всех автоматов в JSON формате для упрощения дебага в production.

## Реализация

### 1. Метод в HAAdapter для получения снимка состояний

```python
# adapters/ha_adapter.py

async def get_fsm_states_snapshot(self, fsm_engine, registry) -> dict:
    """
    Получить снимок состояний всех FSM для watchdog
    
    Returns:
        dict: {
            "timestamp": "2024-01-15T10:30:00",
            "fsm_count": 5,
            "states": {
                "light.living_room": {
                    "current": "ON_SCHEDULE",
                    "entered_at": 1705312200.0,
                    "entered_by": "schedule_on",
                    "entered_why": "Schedule activated",
                    "duration_sec": 1800
                },
                ...
            }
        }
    """
    import time
    from datetime import datetime
    
    all_states = fsm_engine.get_all_states()
    
    states_dict = {}
    for entity_id, state in all_states.items():
        now = time.time()
        duration = now - state.entered_at if state.entered_at else 0
        
        states_dict[entity_id] = {
            "current": state.current,
            "entered_at": state.entered_at,
            "entered_by": state.entered_by,
            "entered_why": state.entered_why,
            "duration_sec": int(duration)
        }
    
    return {
        "timestamp": datetime.now().isoformat(),
        "fsm_count": len(states_dict),
        "states": states_dict
    }
```

### 2. Watchdog сервис в init.py

```python
# platform_v3_init.py

class WatchdogService:
    """
    Сервис периодического мониторинга состояний FSM
    
    Usage:
        watchdog = WatchdogService(fsm_engine, registry, ha_adapter, logger)
        await watchdog.start(interval_sec=60)
        # ...
        await watchdog.stop()
    """
    
    def __init__(self, fsm_engine, registry, ha_adapter, logger, interval_sec=60):
        self._fsm_engine = fsm_engine
        self._registry = registry
        self._ha_adapter = ha_adapter
        self._logger = logger
        self._interval_sec = interval_sec
        self._task = None
    
    async def _log_snapshot(self):
        """Логировать снимок состояний"""
        try:
            snapshot = await self._ha_adapter.get_fsm_states_snapshot(
                self._fsm_engine, 
                self._registry
            )
            
            # Логируем в JSON формате для удобного парсинга
            import json
            self._logger.info(
                f"FSM_WATCHDOG: {json.dumps(snapshot)}",
                **snapshot
            )
            
        except Exception as e:
            self._logger.error(f"Watchdog snapshot failed: {e}")
    
    async def _run_loop(self):
        """Основной цикл watchdog"""
        self._logger.info(f"Watchdog started with interval={self._interval_sec}s")
        
        while True:
            await asyncio.sleep(self._interval_sec)
            await self._log_snapshot()
    
    async def start(self):
        """Запустить watchdog"""
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())
    
    async def stop(self):
        """Остановить watchdog"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


# В main init функции:
watchdog = WatchdogService(
    fsm_engine=fsm,
    registry=registry,
    ha_adapter=ha_adapter,
    logger=logger,
    interval_sec=60  # Раз в минуту
)
await watchdog.start()
```

### 3. Пример вывода в логах

```
2024-01-15 10:30:00 INFO (MainThread) [platform_v3] FSM_WATCHDOG: {"timestamp":"2024-01-15T10:30:00","fsm_count":3,"states":{"light.living_room":{"current":"ON_SCHEDULE","entered_at":1705312200.0,"entered_by":"schedule_on","entered_why":"Schedule activated","duration_sec":1800},"light.hallway":{"current":"OFF","entered_at":1705310400.0,"entered_by":"motion_cleared","entered_why":"Motion cleared","duration_sec":3600},"climate.bedroom":{"current":"AUTO","entered_at":1705311000.0,"entered_by":"mode_change","entered_why":"User changed mode","duration_sec":3000}}}
```

### 4. Парсинг логов watchdog

```bash
# Фильтрация watchdog логов
grep "FSM_WATCHDOG" home-assistant.log | tail -10

# Извлечение JSON и форматирование
grep "FSM_WATCHDOG" home-assistant.log | tail -1 | \
  sed 's/.*FSM_WATCHDOG: //' | \
  python -m json.tool

# Мониторинг в реальном времени
tail -f home-assistant.log | grep "FSM_WATCHDOG"
```

### 5. Интеграция с Home Assistant Service Call

Для вызова watchdog по требованию (не только по таймеру):

```python
# В platform_v3_init.py

@service
def fsm_watchdog_now():
    """
    Принудительно сделать снимок состояний FSM
    
    Usage:
      service: pyscript.fsm_watchdog_now
    """
    import asyncio
    import json
    
    # Создаём event loop если нет
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Запускаем асинхронную функцию
    coroutine = watchdog._log_snapshot()
    
    if loop.is_running():
        # Если loop уже запущен (в рамках HA)
        task = loop.create_task(coroutine)
    else:
        # Иначе запускаем синхронно
        loop.run_until_complete(coroutine)
```

## Преимущества

1. **Отладка в проде**: Можно видеть состояние всех автоматов в любой момент времени
2. **Анализ проблем**: При зависаниях видно какой автомат в каком состоянии застрял
3. **Мониторинг**: Легко отследить аномалии (например, слишком долгое пребывание в состоянии)
4. **JSON формат**: Удобно парсить внешними системами (Grafana, Prometheus, etc.)
5. **По требованию**: Можно вызвать сервисом при подозрении на проблему

## Рекомендации

- **Интервал**: 60 секунд оптимален для большинства случаев
- **Хранение**: Настроить ротацию логов чтобы watchdog не заполнял диск
- **Alerting**: Можно настроить алерты на аномалии (например, FSM в одном состоянии > 1 часа)

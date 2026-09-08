"""
Mock Adapter - Мок-адаптер для локального тестирования без Home Assistant.

Возможности:
- Хранит состояния устройств в памяти
- Имитирует вызов сервисов Home Assistant
- Эмулирует приход событий из HA (motion_detected, manual_override)
- Логирует все действия через loguru
- Поддерживает сброс состояния между тестами
"""

from __future__ import annotations

from typing import Any

from loguru import logger


class MockAdapter:
    """
    Mock-адаптер для имитации поведения Home Assistant при локальном тестировании.
    
    Хранит состояния устройств в памяти и позволяет эмулировать события из HA.
    
    Attributes:
        _states: Словарь состояний устройств {entity_id: state}.
        _fsm_engine: Ссылка на FSMEngine для передачи событий.
        _service_calls: Лог вызовов сервисов для проверки в тестах.
    
    Usage:
        adapter = MockAdapter()
        await adapter.simulate_event("light.kitchen", "motion_detected")
        state = await adapter.get_state("light.kitchen")
        await adapter.call_service("light", "turn_on", "light.kitchen", {})
    """
    
    def __init__(self) -> None:
        """Инициализировать MockAdapter с пустым состоянием."""
        self._states: dict[str, Any] = {}
        self._fsm_engine: Any = None
        self._service_calls: list[dict[str, Any]] = []
        
    def set_fsm_engine(self, fsm_engine: Any) -> None:
        """
        Установить ссылку на FSMEngine для передачи событий.
        
        Args:
            fsm_engine: Экземпляр FSMEngine для обработки событий.
        """
        self._fsm_engine = fsm_engine
        logger.debug(f"MockAdapter linked to FSMEngine: {fsm_engine}")
    
    async def get_state(self, entity_id: str) -> Any:
        """
        Получить текущее состояние устройства.
        
        Args:
            entity_id: ID устройства (например, "light.kitchen").
            
        Returns:
            Текущее состояние устройства или None если не найдено.
        """
        state = self._states.get(entity_id)
        logger.debug(f"MockAdapter: get_state({entity_id}) -> {state}")
        return state
    
    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None
    ) -> None:
        """
        Имитировать вызов сервиса Home Assistant.
        
        Обновляет состояние устройства в памяти и логирует действие.
        
        Args:
            domain: Домен сервиса (например, "light").
            service: Имя сервиса (например, "turn_on", "turn_off").
            entity_id: ID целевого устройства.
            data: Дополнительные данные сервиса.
        """
        data = data or {}
        
        # Логируем вызов сервиса
        log_entry = {
            "domain": domain,
            "service": service,
            "entity_id": entity_id,
            "data": data
        }
        self._service_calls.append(log_entry)
        
        logger.info(
            f"MockAdapter: call_service({domain}.{service}, {entity_id}, {data})"
        )
        
        # Обновляем состояние в зависимости от сервиса
        if domain == "light":
            if service == "turn_on":
                self._states[entity_id] = "on"
                logger.debug(f"MockAdapter: {entity_id} turned ON")
            elif service == "turn_off":
                self._states[entity_id] = "off"
                logger.debug(f"MockAdapter: {entity_id} turned OFF")
            elif service == "toggle":
                current_state = self._states.get(entity_id, "off")
                self._states[entity_id] = "off" if current_state == "on" else "on"
                logger.debug(f"MockAdapter: {entity_id} toggled to {self._states[entity_id]}")
    
    async def simulate_event(
        self,
        entity_id: str,
        trigger: str,
        context: dict[str, Any] | None = None
    ) -> bool:
        """
        Эмулировать приход события из Home Assistant.
        
        Передает событие в FSMEngine для обработки.
        
        Args:
            entity_id: ID устройства, от которого пришло событие.
            trigger: Тип события (например, "motion_detected", "manual_override").
            context: Дополнительный контекст события.
            
        Returns:
            True если событие было успешно обработано, False иначе.
        """
        if self._fsm_engine is None:
            logger.warning(
                f"MockAdapter: No FSMEngine attached, cannot process event "
                f"'{trigger}' for {entity_id}"
            )
            return False
        
        context = context or {}
        logger.info(
            f"MockAdapter: simulate_event({entity_id}, {trigger}, {context})"
        )
        
        try:
            result = await self._fsm_engine.trigger(entity_id, trigger, context)
            logger.debug(
                f"MockAdapter: Event '{trigger}' for {entity_id} processed, "
                f"result={result}"
            )
            return result
        except Exception as e:
            logger.error(
                f"MockAdapter: Failed to process event '{trigger}' for {entity_id}: {e}"
            )
            return False
    
    def clear(self) -> None:
        """
        Сбросить состояние адаптера между тестами.
        
        Очищает:
        - Все состояния устройств
        - Лог вызовов сервисов
        - Все запланированные таймеры в FSMEngine (если доступен)
        """
        self._states.clear()
        self._service_calls.clear()
        
        # Отменяем все таймеры в планировщике если FSMEngine доступен
        if self._fsm_engine is not None and hasattr(self._fsm_engine, 'scheduler'):
            self._fsm_engine.scheduler.cancel_all()
        
        logger.debug("MockAdapter: State cleared")
    
    def get_service_calls(self) -> list[dict[str, Any]]:
        """
        Получить лог вызовов сервисов.
        
        Returns:
            Список записей о вызовах сервисов.
        """
        return list(self._service_calls)
    
    def count_service_calls(
        self,
        domain: str | None = None,
        service: str | None = None,
        entity_id: str | None = None
    ) -> int:
        """
        Подсчитать количество вызовов сервисов с фильтрацией.
        
        Args:
            domain: Фильтр по домену (опционально).
            service: Фильтр по имени сервиса (опционально).
            entity_id: Фильтр по ID устройства (опционально).
            
        Returns:
            Количество вызовов, соответствующих фильтрам.
        """
        count = 0
        for call in self._service_calls:
            if domain is not None and call.get("domain") != domain:
                continue
            if service is not None and call.get("service") != service:
                continue
            if entity_id is not None and call.get("entity_id") != entity_id:
                continue
            count += 1
        return count

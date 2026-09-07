"""
Dashboard Integration - создание entities в Home Assistant

Создает:
- Sensors для мониторинга состояний автоматов
- Binary sensors для статусов
- Automations для интеграции с HA UI
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..core.event_bus import EventBus
from ..core.registry import Registry
from ..adapters.ha_adapter import HomeAssistantAdapter, HAEntity

logger = logging.getLogger(__name__)


class DashboardIntegration:
    """
    Интеграция с Dashboard Home Assistant
    
    Создает entities для отображения состояний автоматов
    """
    
    def __init__(self, ha_adapter: HomeAssistantAdapter, event_bus: EventBus):
        self.ha = ha_adapter
        self.event_bus = event_bus
        self._created_entities: Dict[str, str] = {}
        
        # Подписываемся на события для обновления dashboard
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        """Настроить обработчики событий"""
        self.event_bus.subscribe('fsm.state.changed', self._on_state_changed)
        self.event_bus.subscribe('ha.connected', self._on_ha_connected)
    
    async def _on_state_changed(self, event_data: Dict[str, Any]):
        """Обработчик изменения состояния FSM"""
        fsm_id = event_data.get('fsm_id')
        new_state = event_data.get('new_state')
        
        if fsm_id and new_state:
            # Обновляем sensor в HA
            await self._update_fsm_sensor(fsm_id, new_state, event_data)
    
    async def _on_ha_connected(self, event_data: Dict[str, Any]):
        """Обработчик подключения к HA"""
        logger.info("HA connected, recreating dashboard entities")
        await self._recreate_all_entities()
    
    async def create_fsm_sensor(
        self,
        fsm_id: str,
        name: str,
        feature_type: str
    ) -> bool:
        """
        Создать sensor для мониторинга FSM
        
        Args:
            fsm_id: ID автомата
            name: Отображаемое имя
            feature_type: Тип фичи (lighting, climate, etc.)
            
        Returns:
            bool: True если успешно создано
        """
        entity_id = f"sensor.fsm_{fsm_id}"
        
        # Создаем sensor через REST API
        success = await self.ha.call_service(
            domain='homeassistant',
            service='set_config',
            data={
                'entity_id': entity_id,
                'name': name,
                'icon': self._get_icon_for_feature(feature_type),
                'device_class': 'enum',
                'options': self._get_state_options(feature_type)
            }
        )
        
        if success:
            self._created_entities[fsm_id] = entity_id
            logger.debug(f"Created sensor {entity_id} for FSM {fsm_id}")
        
        return success
    
    async def _update_fsm_sensor(
        self,
        fsm_id: str,
        state: str,
        event_data: Dict[str, Any]
    ):
        """Обновить состояние sensor FSM"""
        entity_id = self._created_entities.get(fsm_id)
        if not entity_id or not self.ha.is_connected:
            return
        
        # Формируем атрибуты
        attributes = {
            'last_transition': event_data.get('timestamp', datetime.now().isoformat()),
            'previous_state': event_data.get('old_state'),
            'trigger_event': event_data.get('event'),
            'feature_type': event_data.get('feature_type', 'unknown')
        }
        
        # Обновляем состояние
        await self.ha.set_entity_state(
            entity_id=entity_id,
            state=state,
            attributes=attributes
        )
    
    async def create_status_binary_sensor(
        self,
        fsm_id: str,
        name: str
    ) -> bool:
        """
        Создать binary sensor для статуса автомата (active/inactive)
        
        Args:
            fsm_id: ID автомата
            name: Отображаемое имя
            
        Returns:
            bool: True если успешно
        """
        entity_id = f"binary_sensor.fsm_{fsm_id}_status"
        
        # Регистрируем в created_entities
        self._created_entities[f"{fsm_id}_status"] = entity_id
        
        # Устанавливаем начальное состояние
        await self.ha.set_entity_state(
            entity_id=entity_id,
            state='on',  # active
            attributes={
                'friendly_name': f"{name} Status",
                'device_class': 'running',
                'icon': 'mdi:check-circle'
            }
        )
        
        return True
    
    async def _recreate_all_entities(self):
        """Пересоздать все entities после переподключения к HA"""
        for fsm_id, entity_id in self._created_entities.items():
            logger.debug(f"Recreating entity {entity_id}")
            # Здесь должна быть логика восстановления
            # Пока просто логируем
    
    def _get_icon_for_feature(self, feature_type: str) -> str:
        """Получить иконку для типа фичи"""
        icons = {
            'lighting': 'mdi:lightbulb',
            'climate': 'mdi:thermometer',
            'ventilation': 'mdi:fan',
            'security': 'mdi:shield',
            'default': 'mdi:cog'
        }
        return icons.get(feature_type, icons['default'])
    
    def _get_state_options(self, feature_type: str) -> List[str]:
        """Получить список возможных состояний для фичи"""
        options = {
            'lighting': ['off', 'on', 'auto', 'night', 'away'],
            'climate': ['off', 'heat', 'cool', 'auto', 'eco'],
            'ventilation': ['off', 'low', 'medium', 'high', 'auto'],
            'security': ['disarmed', 'armed_home', 'armed_away', 'triggered']
        }
        return options.get(feature_type, ['unknown'])
    
    async def create_dashboard_view(
        self,
        title: str = "Smart Home Automation",
        url_path: str = "smart-automation"
    ) -> bool:
        """
        Создать dashboard view в HA
        
        Args:
            title: Заголовок dashboard
            url_path: Путь для доступа
            
        Returns:
            bool: True если успешно
        """
        if not self.ha.is_connected:
            logger.warning("Cannot create dashboard: HA not connected")
            return False
        
        # Формируем конфигурацию dashboard
        dashboard_config = {
            'title': title,
            'views': [{
                'title': 'Automation Status',
                'cards': self._generate_dashboard_cards()
            }]
        }
        
        # Сохраняем через API (требует дополнительной настройки HA)
        logger.info(f"Dashboard config prepared: {url_path}")
        logger.debug(f"Config: {dashboard_config}")
        
        return True
    
    def _generate_dashboard_cards(self) -> List[Dict[str, Any]]:
        """Сгенерировать карточки для dashboard"""
        cards = []
        
        for fsm_id, entity_id in self._created_entities.items():
            if entity_id.startswith('sensor.'):
                # Entity card для sensor
                cards.append({
                    'type': 'entity',
                    'entity': entity_id,
                    'name': f"FSM {fsm_id}"
                })
        
        return cards
    
    def get_created_entities(self) -> Dict[str, str]:
        """Получить список созданных entities"""
        return self._created_entities.copy()

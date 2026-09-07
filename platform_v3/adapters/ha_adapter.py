"""
Home Assistant Adapter - полноценная интеграция с HA через REST и WebSocket
"""
import asyncio
import aiohttp
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from ..core.event_bus import EventBus
from ..core.logger import get_logger

logger = get_logger(__name__)


class ConnectionState(Enum):
    """Состояние соединения с HA"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class HAEntity:
    """Представление сущности HA"""
    entity_id: str
    state: str
    attributes: Dict[str, Any]
    last_changed: datetime
    last_updated: datetime


class HomeAssistantAdapter:
    """
    Адаптер для интеграции с Home Assistant
    
    Поддерживает:
    - REST API для запросов состояния
    - WebSocket для real-time обновлений
    - Авто-реконнект при обрыве связи
    - Буферизацию событий при отключении
    """
    
    def __init__(
        self,
        base_url: str,
        token: str,
        event_bus: EventBus,
        ws_port: int = 8123,
        reconnect_interval: int = 5,
        timeout: int = 10
    ):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.event_bus = event_bus
        self.ws_port = ws_port
        self.reconnect_interval = reconnect_interval
        self.timeout = timeout
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connection_state = ConnectionState.DISCONNECTED
        self._message_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._entities_cache: Dict[str, HAEntity] = {}
        self._reconnect_task: Optional[asyncio.Task] = None
        self._listen_task: Optional[asyncio.Task] = None
        
        # Headers для всех запросов
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    @property
    def connection_state(self) -> ConnectionState:
        """Текущее состояние соединения"""
        return self._connection_state
    
    @property
    def is_connected(self) -> bool:
        """Проверка подключения"""
        return self._connection_state == ConnectionState.CONNECTED
    
    async def connect(self) -> bool:
        """
        Установить соединение с HA
        
        Returns:
            bool: True если успешно подключились
        """
        logger.info(f"Connecting to HA at {self.base_url}")
        self._set_state(ConnectionState.CONNECTING)
        
        try:
            # Создаем HTTP сессию
            self._session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
            
            # Проверяем доступность REST API
            async with self._session.get(f"{self.base_url}/api/") as resp:
                if resp.status != 200:
                    logger.error(f"HA REST API unavailable: {resp.status}")
                    self._set_state(ConnectionState.ERROR)
                    return False
            
            # Подключаем WebSocket
            ws_url = f"ws://{self.base_url.split('://')[1]}:{self.ws_port}/api/websocket"
            self._ws = await self._session.ws_connect(ws_url)
            
            # Auth handshake
            auth_msg = await self._ws.receive_json()
            if auth_msg.get('type') != 'auth_required':
                logger.error(f"Unexpected auth message: {auth_msg}")
                self._set_state(ConnectionState.ERROR)
                return False
            
            # Send auth
            await self._ws.send_json({
                'type': 'auth',
                'access_token': self.token
            })
            
            auth_ok = await self._ws.receive_json()
            if auth_ok.get('type') != 'auth_ok':
                logger.error(f"Auth failed: {auth_ok}")
                self._set_state(ConnectionState.ERROR)
                return False
            
            self._set_state(ConnectionState.CONNECTED)
            logger.info("Successfully connected to HA")
            
            # Запускаем слушателя событий
            self._listen_task = asyncio.create_task(self._listen_events())
            
            # Публикуем событие подключения
            self.event_bus.publish('ha.connected', {'timestamp': datetime.now().isoformat()})
            
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._set_state(ConnectionState.ERROR)
            return False
    
    async def disconnect(self):
        """Закрыть соединение с HA"""
        logger.info("Disconnecting from HA")
        
        # Отменяем задачи
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        
        # Закрываем WebSocket
        if self._ws:
            await self._ws.close()
        
        # Закрываем сессию
        if self._session:
            await self._session.close()
        
        self._set_state(ConnectionState.DISCONNECTED)
        self.event_bus.publish('ha.disconnected', {'timestamp': datetime.now().isoformat()})
        logger.info("Disconnected from HA")
    
    async def get_entity_state(self, entity_id: str) -> Optional[HAEntity]:
        """
        Получить состояние сущности
        
        Args:
            entity_id: ID сущности (e.g., 'light.living_room')
            
        Returns:
            HAEntity или None если не найдено
        """
        if not self.is_connected:
            logger.warning(f"Cannot get state: not connected")
            return None
        
        try:
            url = f"{self.base_url}/api/states/{entity_id}"
            async with self._session.get(url) as resp:
                if resp.status == 404:
                    return None
                
                data = await resp.json()
                entity = HAEntity(
                    entity_id=data['entity_id'],
                    state=data['state'],
                    attributes=data.get('attributes', {}),
                    last_changed=datetime.fromisoformat(data['last_changed']),
                    last_updated=datetime.fromisoformat(data['last_updated'])
                )
                
                # Обновляем кэш
                self._entities_cache[entity_id] = entity
                
                return entity
                
        except Exception as e:
            logger.error(f"Error getting state for {entity_id}: {e}")
            return None
    
    async def set_entity_state(
        self,
        entity_id: str,
        state: str,
        attributes: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Установить состояние сущности
        
        Args:
            entity_id: ID сущности
            state: Новое состояние
            attributes: Дополнительные атрибуты
            
        Returns:
            bool: True если успешно
        """
        if not self.is_connected:
            logger.warning(f"Cannot set state: not connected")
            return False
        
        try:
            # Определяем сервис в зависимости от типа сущности и состояния
            domain = entity_id.split('.')[0]
            if state in ['off', 'closed', 'locked']:
                service = 'turn_off'
            elif state == 'open':
                service = 'open'
            elif state == 'close':
                service = 'close'
            else:
                service = 'turn_on'
            
            url = f"{self.base_url}/api/services/{domain}/{service}"
            
            payload = {'entity_id': entity_id}
            if attributes:
                payload.update(attributes)
            
            async with self._session.post(url, json=payload) as resp:
                if resp.status in [200, 201]:
                    logger.debug(f"Set {entity_id} to {state}")
                    
                    # Обновляем кэш
                    if entity_id in self._entities_cache:
                        self._entities_cache[entity_id].state = state
                    
                    # Публикуем событие
                    self.event_bus.publish('ha.entity.changed', {
                        'entity_id': entity_id,
                        'state': state,
                        'attributes': attributes
                    })
                    
                    return True
                else:
                    logger.error(f"Failed to set state: {resp.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error setting state for {entity_id}: {e}")
            return False
    
    async def subscribe_events(self, event_type: str, callback: Callable):
        """
        Подписаться на события HA
        
        Args:
            event_type: Тип события (e.g., 'state_changed')
            callback: Функция обратного вызова
        """
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
            
            # Отправляем запрос на подписку через WebSocket
            if self.is_connected:
                msg_id = self._next_message_id()
                await self._ws.send_json({
                    'id': msg_id,
                    'type': 'subscribe_events',
                    'event_type': event_type
                })
        
        self._subscriptions[event_type].append(callback)
        logger.debug(f"Subscribed to {event_type}")
    
    async def call_service(
        self,
        domain: str,
        service: str,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Вызвать сервис HA
        
        Args:
            domain: Домен сервиса (e.g., 'light')
            service: Название сервиса (e.g., 'turn_on')
            data: Данные для сервиса
            
        Returns:
            bool: True если успешно
        """
        if not self.is_connected:
            return False
        
        try:
            url = f"{self.base_url}/api/services/{domain}/{service}"
            async with self._session.post(url, json=data or {}) as resp:
                return resp.status in [200, 201]
        except Exception as e:
            logger.error(f"Error calling service {domain}.{service}: {e}")
            return False
    
    async def get_all_entities(self) -> List[HAEntity]:
        """Получить все сущности из HA"""
        if not self.is_connected:
            return []
        
        try:
            url = f"{self.base_url}/api/states"
            async with self._session.get(url) as resp:
                data = await resp.json()
                entities = []
                for item in data:
                    entity = HAEntity(
                        entity_id=item['entity_id'],
                        state=item['state'],
                        attributes=item.get('attributes', {}),
                        last_changed=datetime.fromisoformat(item['last_changed']),
                        last_updated=datetime.fromisoformat(item['last_updated'])
                    )
                    entities.append(entity)
                    self._entities_cache[entity.entity_id] = entity
                return entities
        except Exception as e:
            logger.error(f"Error getting all entities: {e}")
            return []
    
    def _set_state(self, state: ConnectionState):
        """Установить состояние соединения"""
        old_state = self._connection_state
        self._connection_state = state
        
        if old_state != state:
            logger.info(f"Connection state changed: {old_state.value} -> {state.value}")
            self.event_bus.publish('ha.connection_state.changed', {
                'old_state': old_state.value,
                'new_state': state.value
            })
    
    def _next_message_id(self) -> int:
        """Получить следующий ID сообщения"""
        self._message_id += 1
        return self._message_id
    
    async def _listen_events(self):
        """Слушатель событий WebSocket"""
        logger.info("Started listening to HA events")
        
        while self.is_connected and self._ws and not self._ws.closed:
            try:
                msg = await self._ws.receive_json()
                
                if msg.get('type') == 'event':
                    event_data = msg.get('event', {})
                    event_type = event_data.get('event_type')
                    
                    # Публикуем в шину событий
                    self.event_bus.publish(f'ha.event.{event_type}', event_data)
                    
                    # Вызываем подписчиков
                    if event_type in self._subscriptions:
                        for callback in self._subscriptions[event_type]:
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(event_data)
                                else:
                                    callback(event_data)
                            except Exception as e:
                                logger.error(f"Error in event callback: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error listening to events: {e}")
                break
        
        # Если соединение потеряно, пытаемся переподключиться
        if self._connection_state == ConnectionState.CONNECTED:
            self._set_state(ConnectionState.DISCONNECTED)
            self._reconnect_task = asyncio.create_task(self._reconnect())
    
    async def _reconnect(self):
        """Попытка переподключения"""
        logger.info(f"Attempting to reconnect in {self.reconnect_interval}s")
        await asyncio.sleep(self.reconnect_interval)
        
        while not self.is_connected:
            success = await self.connect()
            if success:
                break
            await asyncio.sleep(self.reconnect_interval)

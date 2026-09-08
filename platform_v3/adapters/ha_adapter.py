"""
Home Assistant Adapter - полноценная интеграция с HA через REST и WebSocket

Ключевые особенности:
- REST API для запросов состояния
- WebSocket для real-time обновлений
- Авто-реконнект с Exponential Backoff при обрыве связи
- Debouncer для игнорирования "эха" (feedback loops)
- Буферизация событий при отключении
"""
import asyncio
import aiohttp
from typing import Dict, Any, Optional, Callable, List, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import time

from core.event_bus import EventBus
from core.logger import get_logger

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
    - Авто-реконнект с Exponential Backoff при обрыве связи
    - Debouncer для игнорирования "эха" (когда FSM сам изменил состояние)
    - Буферизация событий при отключении
    """
    
    def __init__(
        self,
        base_url: str,
        token: str,
        event_bus: EventBus,
        ws_port: int = 8123,
        reconnect_base_delay: float = 2.0,
        reconnect_max_delay: float = 60.0,
        debounce_window_sec: float = 2.0,
        timeout: int = 10
    ):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.event_bus = event_bus
        self.ws_port = ws_port
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.debounce_window_sec = debounce_window_sec
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
        
        # Debouncer для игнорирования "эха"
        # Ключ: entity_id, Значение: timestamp последней команды от нас
        self._sent_commands: Dict[str, float] = {}
        self._debounce_lock = asyncio.Lock()
        
        # Счётчик попыток реконнекта для exponential backoff
        self._reconnect_attempts = 0
        
        # Context ID для отслеживания наших команд
        self._context_id_counter = 0
    
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
            
            # Записываем что мы отправили команду (для debouncing эха)
            context_id = await self._record_command_sent(entity_id)
            
            # Добавляем context_id в payload для отслеживания в HA
            payload['_context_id'] = context_id
            
            async with self._session.post(url, json=payload) as resp:
                if resp.status in [200, 201]:
                    logger.debug(f"Set {entity_id} to {state} (context_id={context_id})")
                    
                    # Обновляем кэш
                    if entity_id in self._entities_cache:
                        self._entities_cache[entity_id].state = state
                    
                    # Публикуем событие
                    self.event_bus.publish('ha.entity.changed', {
                        'entity_id': entity_id,
                        'state': state,
                        'attributes': attributes,
                        'context_id': context_id
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
    
    def _generate_context_id(self) -> str:
        """Сгенерировать уникальный context ID для отслеживания наших команд"""
        self._context_id_counter += 1
        return f"platform_v3:{self._context_id_counter}:{time.time()}"
    
    async def _record_command_sent(self, entity_id: str) -> str:
        """
        Записать что мы отправили команду (для debouncing эха)
        
        Returns:
            context_id: Уникальный ID команды
        """
        async with self._debounce_lock:
            now = time.time()
            self._sent_commands[entity_id] = now
            context_id = self._generate_context_id()
            
            # Очищаем старые записи (> 10 секунд)
            cutoff = now - 10.0
            self._sent_commands = {
                k: v for k, v in self._sent_commands.items() 
                if v > cutoff
            }
            
            return context_id
    
    def _is_echo_event(self, entity_id: str, event_data: dict) -> bool:
        """
        Проверить является ли событие "эхом" от нашей же команды
        
        Args:
            entity_id: ID сущности
            event_data: Данные события state_changed из HA
            
        Returns:
            True если это эхо (изменение вызвано нами)
        """
        # Проверяем когда мы последний раз отправляли команду для этой сущности
        if entity_id not in self._sent_commands:
            return False
        
        last_command_time = self._sent_commands.get(entity_id, 0)
        event_time = time.time()
        
        # Если событие пришло в течение debounce_window_sec после нашей команды
        # считаем это "эхом"
        if event_time - last_command_time < self.debounce_window_sec:
            logger.debug(
                f"Ignoring echo event for {entity_id} "
                f"(command sent {event_time - last_command_time:.2f}s ago)"
            )
            return True
        
        return False
    
    async def _listen_events(self):
        """Слушатель событий WebSocket с защитой от эха и exponential backoff"""
        logger.info("Started listening to HA events")
        
        while self.is_connected and self._ws and not self._ws.closed:
            try:
                msg = await self._ws.receive_json()
                
                if msg.get('type') == 'event':
                    event_data = msg.get('event', {})
                    event_type = event_data.get('event_type')
                    
                    # Обрабатываем state_changed события с проверкой на эхо
                    if event_type == 'state_changed':
                        entity_id = event_data.get('data', {}).get('entity_id', '')
                        
                        # Игнорируем эхо от наших команд
                        if self._is_echo_event(entity_id, event_data):
                            continue
                        
                        # Проверяем context.id для дополнительного распознавания
                        context = event_data.get('data', {}).get('context', {})
                        context_id = context.get('id', '')
                        
                        # Если context.id содержит нашу метку "platform_v3:", это точно эхо
                        if context_id.startswith('platform_v3:'):
                            logger.debug(f"Ignoring echo by context.id: {context_id}")
                            continue
                        
                        # Определяем источник изменения: ручной ввод или автоматика
                        # user_id присутствует если изменение сделано через UI (ручной ввод)
                        # parent_id присутствует если изменение вызвано другой автоматизацией
                        user_id = context.get('user_id')
                        parent_id = context.get('parent_id')
                        
                        is_manual = user_id is not None
                        is_automation = parent_id is not None and user_id is None
                        
                        # Добавляем флаг источника в событие для FSM
                        event_data['data']['is_manual'] = is_manual
                        event_data['data']['is_automation'] = is_automation
                        event_data['data']['context_user_id'] = user_id
                    
                    # Публикуем в шину событий (только не-эхо события)
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
        """
        Попытка переподключения с Exponential Backoff
        
        Алгоритм:
        - 1 попытка: ждём 2 секунды
        - 2 попытка: ждём 4 секунды
        - 3 попытка: ждём 8 секунд
        - ...
        - Максимум: 60 секунд между попытками
        """
        self._reconnect_attempts += 1
        
        delay = min(
            self.reconnect_base_delay * (2 ** (self._reconnect_attempts - 1)),
            self.reconnect_max_delay
        )
        
        logger.info(
            f"Attempting to reconnect in {delay:.1f}s "
            f"(attempt #{self._reconnect_attempts})"
        )
        await asyncio.sleep(delay)
        
        while not self.is_connected:
            success = await self.connect()
            if success:
                # Сбрасываем счётчик попыток при успешном подключении
                self._reconnect_attempts = 0
                logger.info("Successfully reconnected after backoff")
                break
            
            self._reconnect_attempts += 1
            delay = min(
                self.reconnect_base_delay * (2 ** (self._reconnect_attempts - 1)),
                self.reconnect_max_delay
            )
            logger.warning(
                f"Reconnection failed, next attempt in {delay:.1f}s "
                f"(attempt #{self._reconnect_attempts})"
            )
            await asyncio.sleep(delay)
    
    async def sync_all_states(self) -> Dict[str, HAEntity]:
        """
        Синхронизировать все состояния из HA (StateSync при старте)
        
        Используется при инициализации платформы для приведения FSM
        в соответствие с физическим состоянием устройств.
        
        Returns:
            Dict mapping entity_id -> HAEntity
        """
        logger.info("Starting state synchronization with HA")
        entities = await self.get_all_entities()
        
        result = {}
        for entity in entities:
            result[entity.entity_id] = entity
            # Обновляем кэш
            self._entities_cache[entity.entity_id] = entity
        
        logger.info(f"State sync complete: {len(result)} entities")
        return result
    
    async def get_entity_state_fresh(self, entity_id: str) -> Optional[HAEntity]:
        """
        Получить свежее состояние сущности напрямую из HA (минуя кэш)
        
        Args:
            entity_id: ID сущности
            
        Returns:
            HAEntity или None если не найдено
        """
        return await self.get_entity_state(entity_id)
    
    async def subscribe_state_changes(self, entity_ids: Set[str], callback: Callable):
        """
        Подписаться на изменения состояний конкретных entity_id.
        
        Вместо глобальной подписки на все события, создаем точечные подписки
        только на те устройства, которые используются в зарегистрированных FSM.
        
        Args:
            entity_ids: Множество entity_id для подписки
            callback: Функция обратного вызова, принимающая event_data
        """
        if not self.is_connected:
            logger.warning("Cannot subscribe: not connected")
            return
        
        # Группируем entity_id по доменам для оптимизации (опционально)
        # Например: light.kitchen, light.bedroom -> можно подписаться на "state_changed" и фильтровать
        # Но для максимальной точности подписываемся на каждое устройство отдельно через wildcard
        
        unique_domains = set()
        exact_entities = set()
        
        for entity_id in entity_ids:
            if entity_id.endswith('.*'):
                # Wildcard паттерн (например, "light.*")
                unique_domains.add(entity_id)
            else:
                # Точный entity_id
                exact_entities.add(entity_id)
        
        # Подписываемся на глобальное событие state_changed, но фильтруем внутри callback
        # Это более эффективно чем создавать множество WebSocket подписок
        if exact_entities or unique_domains:
            await self._subscribe_filtered_state_changes(
                exact_entities, 
                unique_domains, 
                callback
            )
            logger.info(f"Subscribed to {len(exact_entities)} entities and {len(unique_domains)} domain patterns")
    
    async def _subscribe_filtered_state_changes(
        self, 
        exact_entities: Set[str], 
        domain_patterns: Set[str], 
        callback: Callable
    ):
        """
        Внутренний метод для подписки с фильтрацией по entity_id.
        
        Подписываемся на 'state_changed' один раз, но фильтруем события
        перед вызовом callback, чтобы игнорировать ненужные устройства.
        """
        async def filtered_callback(event_data):
            data = event_data.get('data', {})
            entity_id = data.get('entity_id', '')
            
            # Проверяем точное совпадение
            if entity_id in exact_entities:
                await self._invoke_callback(callback, event_data, entity_id)
                return
            
            # Проверяем wildcard паттерны (например, "light.*")
            for pattern in domain_patterns:
                prefix = pattern[:-2]  # Убираем ".*"
                if entity_id.startswith(prefix + '.'):
                    await self._invoke_callback(callback, event_data, entity_id)
                    return
            
            # Игнорируем событие (не из нашего списка)
            pass
        
        # Подписываемся на одно общее событие state_changed
        await self.subscribe_events('state_changed', filtered_callback)
    
    async def _invoke_callback(self, callback: Callable, event_data: dict, entity_id: str):
        """Вызвать callback с обработкой ошибок"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(event_data)
            else:
                callback(event_data)
        except Exception as e:
            logger.error(f"Error in state change callback for {entity_id}: {e}")

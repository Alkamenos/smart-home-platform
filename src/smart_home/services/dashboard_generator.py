"""
Генератор дашбордов Home Assistant из манифеста и состояния FSM.

Создаёт YAML-файлы Lovelace дашбордов для Home Assistant с:
- Отдельной вкладкой для каждой комнаты (zone)
- Карточками устройств с состоянием FSM
- Индикацией активного behavior
- Историей переходов (последние 10)
- Кнопками manual override

Использование:
    from smart_home.services.dashboard_generator import DashboardGenerator
    
    manifest = load_manifest("instances/leonids_house/manifest.yaml")
    generator = DashboardGenerator(manifest)
    
    # Сгенерировать полную панель
    dashboard = generator.generate_full_dashboard()
    generator.save_to_file(dashboard, "/config/dashboards/ui-lovelace.yaml")
"""

import yaml
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from smart_home.core.models.manifest import Manifest, Zone, AnyDevice, BehaviorConfig


class DashboardGenerator:
    """
    Генератор дашбордов Lovelace из манифеста и состояния FSM.

    Создаёт карточки для:
    - Статуса автоматов (real-time состояния FSM)
    - Активных behaviors (кто управляет устройством)
    - Истории переходов (последние 10 событий)
    - Кнопок manual override
    """

    # Иконки для типов устройств
    DEVICE_ICONS = {
        "light_motion": "mdi:lightbulb",
        "climate_hysteresis": "mdi:thermometer",
        "ventilation_humidity": "mdi:fan",
        "cover": "mdi:blinds",
        "switch": "mdi:power-socket",
    }

    # Иконки для templates/behaviors
    BEHAVIOR_ICONS = {
        "lighting": "mdi:lightbulb-on",
        "night_light": "mdi:lightbulb-night",
        "climate_hysteresis": "mdi:thermostat",
        "ventilation_humidity": "mdi:air-filter",
        "motion": "mdi:motion-sensor",
        "schedule": "mdi:clock-outline",
    }

    # Цвета состояний для индикаторов
    STATE_COLORS = {
        "OFF": "#6c757d",      # серый
        "ON": "#28a745",        # зелёный
        "ACTIVE": "#28a745",    # зелёный
        "INACTIVE": "#6c757d",  # серый
        "MANUAL": "#ffc107",    # жёлтый
        "HEATING": "#dc3545",   # красный
        "COOLING": "#007bff",   # синий
        "IDLE": "#28a745",      # зелёный
    }

    def __init__(self, manifest: Manifest, fsm_states: Optional[dict] = None):
        """
        Инициализация генератора.

        Args:
            manifest: Объект Manifest с зонами, устройствами и поведениями
            fsm_states: Опциональный словарь состояний FSM для отображения
                       актуальной информации. Формат:
                       {entity_id: {"state": str, "active_behavior": str, "history": [...]}}
        """
        self._manifest = manifest
        self._fsm_states = fsm_states or {}

    def generate_full_dashboard(self) -> dict:
        """
        Генерирует полный дашборд со всеми карточками.

        Создаёт многостраничный дашборд с:
        - Главной страницей (общий статус)
        - Вкладками по комнатам (zones)
        - Страницей истории

        Returns:
            dict: Полная конфигурация дашборда Lovelace
        """
        dashboard_config = self._manifest.dashboard
        title = dashboard_config.title

        views = []

        # === Главная страница ===
        main_cards = []

        # Карточка управления платформой
        main_cards.append(self._generate_platform_control_card())

        # Карточка статуса всех автоматов
        main_cards.append(self._generate_automations_status_card())

        # Датчики движения (если включено)
        if dashboard_config.show_motion_sensors:
            motion_card = self._generate_motion_sensors_card()
            if motion_card:
                main_cards.append(motion_card)

        # Климат (если включено)
        if dashboard_config.show_climate:
            climate_card = self._generate_climate_overview_card()
            if climate_card:
                main_cards.append(climate_card)

        views.append({
            "title": "Главная",
            "icon": "mdi:home",
            "cards": main_cards,
        })

        # === Вкладки по комнатам (для каждой зоны) ===
        for zone in self._manifest.zones:
            zone_devices = [d for d in self._manifest.devices if d.room == zone.id]
            if zone_devices:
                views.append(self._generate_zone_view(zone, zone_devices))

        # === Страница истории (если включено) ===
        if dashboard_config.show_history:
            views.append({
                "title": "История",
                "icon": "mdi:history",
                "cards": [self._generate_history_card()],
            })

        return {
            "title": title,
            "views": views,
        }

    def _generate_platform_control_card(self) -> dict:
        """
        Генерирует карточку управления платформой.

        Содержит кнопки для:
        - Включения/выключения автоматики
        - Ручного режима
        - Получения статуса
        - Сброса блокировок

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        buttons = [
            {
                "type": "button",
                "name": "Включить",
                "icon": "mdi:robot",
                "show_name": True,
                "tap_action": {
                    "action": "call-service",
                    "service": "platform_v3.enable_automation",
                    "service_data": {},
                },
            },
            {
                "type": "button",
                "name": "Выключить",
                "icon": "mdi:robot-off",
                "show_name": True,
                "tap_action": {
                    "action": "call-service",
                    "service": "platform_v3.disable_automation",
                    "service_data": {},
                },
            },
            {
                "type": "button",
                "name": "Ручной",
                "icon": "mdi:hand-left",
                "show_name": True,
                "tap_action": {
                    "action": "call-service",
                    "service": "platform_v3.manual_mode",
                    "service_data": {},
                },
            },
            {
                "type": "button",
                "name": "Статус",
                "icon": "mdi:information-outline",
                "show_name": True,
                "tap_action": {
                    "action": "call-service",
                    "service": "platform_v3.status",
                    "service_data": {},
                },
            },
            {
                "type": "button",
                "name": "Сброс",
                "icon": "mdi:refresh",
                "show_name": True,
                "tap_action": {
                    "action": "call-service",
                    "service": "platform_v3.reset_lockouts",
                    "service_data": {},
                },
            },
        ]

        return {
            "type": "horizontal-stack",
            "cards": [{"type": "button", **btn} for btn in buttons],
        }

    def _generate_automations_status_card(self) -> dict:
        """
        Генерирует карточку статуса всех автоматов.

        Показывает все автоматы с:
        - Текущим состоянием FSM
        - Активным behavior
        - Временем последнего перехода

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        entities = []

        for device in self._manifest.devices:
            entity_id = device.id
            sensor_entity = f"sensor.platform_v3_{entity_id.replace('.', '_')}_state"

            # Получаем состояние FSM если доступно
            fsm_state = self._fsm_states.get(entity_id, {})
            current_state = fsm_state.get("state", "unknown")

            entities.append({
                "entity": sensor_entity,
                "name": device.name,
                "icon": self.DEVICE_ICONS.get(device.type, "mdi:robot"),
                "secondary_info": "last-changed",
            })

        return {
            "type": "entities",
            "title": "🏠 Автоматы",
            "show_header_toggle": False,
            "entities": entities,
        }

    def _generate_zone_view(self, zone: Zone, devices: list[AnyDevice]) -> dict:
        """
        Создать вкладку для одной зоны (комнаты).

        Для каждого устройства создаёт карточку с:
        - Текущим состоянием FSM
        - Активным behavior
        - Историей переходов
        - Кнопками manual override

        Args:
            zone: Объект зоны
            devices: Список устройств в этой зоне

        Returns:
            dict: Конфигурация вкладки Lovelace
        """
        cards = []

        for device in devices:
            # Основная карточка устройства с состоянием FSM
            device_card = self._generate_device_fsm_card(device)
            cards.append(device_card)

            # Карточка с активными behaviors
            behavior_cards = self._generate_behavior_cards(device)
            cards.extend(behavior_cards)

            # Карточка истории переходов
            history_card = self._generate_device_history_card(device)
            cards.append(history_card)

            # Карточка manual override
            override_card = self._generate_manual_override_card(device)
            cards.append(override_card)

        return {
            "title": zone.name,
            "path": zone.id,
            "icon": "mdi:room",
            "cards": cards,
        }

    def _generate_device_fsm_card(self, device: AnyDevice) -> dict:
        """
        Создать карточку с текущим состоянием FSM устройства.

        Args:
            device: Устройство из манифеста

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        entity_id = device.id
        sensor_entity = f"sensor.platform_v3_{entity_id.replace('.', '_')}_state"

        # Получаем состояние FSM если доступно
        fsm_state = self._fsm_states.get(entity_id, {})
        current_state = fsm_state.get("state", "unknown")

        return {
            "type": "entities",
            "title": f"{self.DEVICE_ICONS.get(device.type, 'mdi:device')} {device.name}",
            "show_header_toggle": False,
            "entities": [
                {
                    "entity": sensor_entity,
                    "name": "Состояние FSM",
                    "icon": "mdi:state-machine",
                },
                {
                    "content": f"**Текущее состояние:** `{current_state}`",
                    "type": "custom:markdown",
                },
            ],
        }

    def _generate_behavior_cards(self, device: AnyDevice) -> list[dict]:
        """
        Создать карточки с индикаторами активных behaviors.

        Args:
            device: Устройство из манифеста

        Returns:
            list[dict]: Список карточек Lovelace
        """
        cards = []

        for behavior in device.behaviors:
            behavior_name = behavior.template
            sensor_entity = f"binary_sensor.platform_v3_{device.id.replace('.', '_')}_{behavior_name}_active"

            # Выбираем иконку для behavior
            icon = self.BEHAVIOR_ICONS.get(behavior_name, "mdi:automation")

            cards.append({
                "type": "entity-button",
                "entity": sensor_entity,
                "name": f"{behavior_name}",
                "subtitle": f"Приоритет: {behavior.priority}",
                "icon": icon,
                "tap_action": {
                    "action": "more-info",
                },
                "hold_action": {
                    "action": "none",
                },
            })

        return cards

    def _generate_device_history_card(self, device: AnyDevice) -> dict:
        """
        Создать карточку с историей переходов устройства (последние 10).

        Args:
            device: Устройство из манифеста

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        history_entity = f"sensor.platform_v3_{device.id.replace('.', '_')}_history"

        # Получаем историю из FSM states если доступно
        fsm_state = self._fsm_states.get(device.id, {})
        history = fsm_state.get("history", [])

        entities_list = [
            {
                "entity": history_entity,
                "name": "История переходов",
                "secondary_info": "last-changed",
            },
        ]

        # Добавляем последние 10 записей истории если доступны
        for i, entry in enumerate(history[-10:], 1):
            from_state = entry.get("from_state", "?")
            to_state = entry.get("to_state", "?")
            trigger = entry.get("trigger", "?")
            timestamp = entry.get("timestamp", "")

            entities_list.append({
                "content": f"{i}. `{from_state}` → `{to_state}` [{trigger}] {timestamp}",
                "type": "custom:markdown",
            })

        return {
            "type": "entities",
            "title": "📜 История переходов",
            "show_header_toggle": False,
            "entities": entities_list,
            "sort": {"method": "last_changed", "reverse": True},
        }

    def _generate_manual_override_card(self, device: AnyDevice) -> dict:
        """
        Создать карточку с кнопками manual override для устройства.

        Args:
            device: Устройство из манифеста

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        entity_id = device.id

        # Определяем сервисы для управления в зависимости от типа устройства
        if device.type == "light_motion":
            service_on = "light.turn_on"
            service_off = "light.turn_off"
        elif device.type == "climate_hysteresis":
            service_on = "climate.set_hvac_mode"
            service_off = "climate.turn_off"
        elif device.type == "ventilation_humidity":
            service_on = "fan.turn_on"
            service_off = "fan.turn_off"
        else:
            service_on = "switch.turn_on"
            service_off = "switch.turn_off"

        return {
            "type": "horizontal-stack",
            "cards": [
                {
                    "type": "button",
                    "name": "Включить",
                    "icon": "mdi:power-on",
                    "show_name": True,
                    "tap_action": {
                        "action": "call-service",
                        "service": service_on,
                        "service_data": {"entity_id": entity_id},
                    },
                },
                {
                    "type": "button",
                    "name": "Выключить",
                    "icon": "mdi:power-off",
                    "show_name": True,
                    "tap_action": {
                        "action": "call-service",
                        "service": service_off,
                        "service_data": {"entity_id": entity_id},
                    },
                },
                {
                    "type": "button",
                    "name": "Ручной режим",
                    "icon": "mdi:hand-left",
                    "show_name": True,
                    "tap_action": {
                        "action": "call-service",
                        "service": "platform_v3.manual_mode",
                        "service_data": {"entity_id": entity_id},
                    },
                },
                {
                    "type": "button",
                    "name": "Авто режим",
                    "icon": "mdi:robot",
                    "show_name": True,
                    "tap_action": {
                        "action": "call-service",
                        "service": "platform_v3.enable_automation",
                        "service_data": {"entity_id": entity_id},
                    },
                },
            ],
        }

    def _generate_motion_sensors_card(self) -> Optional[dict]:
        """
        Генерирует карточку датчиков движения.

        Returns:
            dict | None: Конфигурация карточки Lovelace или None если нет датчиков
        """
        entities = []
        seen_sensors = set()

        for device in self._manifest.devices:
            # Получаем motion_sensor из params behavior
            for behavior in device.behaviors:
                motion_sensor = behavior.params.get("motion_sensor")
                if motion_sensor and motion_sensor not in seen_sensors:
                    seen_sensors.add(motion_sensor)
                    entities.append({
                        "entity": motion_sensor,
                        "name": f"Движение: {device.name}",
                        "icon": "mdi:motion-sensor",
                        "secondary_info": "last-changed",
                    })

        if not entities:
            return None

        return {
            "type": "entities",
            "title": "👁️ Датчики движения",
            "show_header_toggle": False,
            "entities": entities,
        }

    def _generate_climate_overview_card(self) -> Optional[dict]:
        """
        Генерирует карточку обзора климата.

        Returns:
            dict | None: Конфигурация карточки Lovelace или None если нет климатических устройств
        """
        entities = []

        for device in self._manifest.devices:
            if device.type == "climate_hysteresis":
                # Получаем sensor из params behavior
                for behavior in device.behaviors:
                    sensor_entity = behavior.params.get("sensor")
                    if sensor_entity:
                        entities.append({
                            "entity": sensor_entity,
                            "name": device.name,
                            "icon": "mdi:thermometer",
                            "secondary_info": "last-changed",
                        })

        if not entities:
            return None

        return {
            "type": "entities",
            "title": "🌡️ Климат",
            "show_header_toggle": False,
            "entities": entities,
        }

    def _generate_history_card(self) -> dict:
        """
        Генерирует карточку общей истории переходов.

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        entities = []
        history_days = self._manifest.dashboard.history_days

        for device in self._manifest.devices:
            history_entity = f"sensor.platform_v3_{device.id.replace('.', '_')}_history"

            entities.append({
                "entity": history_entity,
                "name": device.name,
                "secondary_info": "last-changed",
            })

        return {
            "type": "entities",
            "title": f"📜 История переходов ({history_days} дн.)",
            "show_header_toggle": False,
            "entities": entities,
            "sort": {"method": "last_changed", "reverse": True},
        }

    def save_to_file(
        self,
        dashboard: Optional[dict] = None,
        output_path: Optional[str] = None,
        preserve_existing: bool = True,
    ) -> bool:
        """
        Записывает дашборд в файл конфигурации HA.

        Args:
            dashboard: Конфигурация дашборда (если None, генерируется автоматически)
            output_path: Путь к файлу ui-lovelace.yaml
            preserve_existing: Сохранять существующие настройки (по умолчанию True)

        Returns:
            bool: True если запись успешна, False иначе
        """
        if dashboard is None:
            dashboard = self.generate_full_dashboard()

        # Определяем путь к файлу
        if output_path is None:
            output_path = "~/.homeassistant/ui-lovelace.yaml"
        output_path = Path(output_path).expanduser()

        # Читаем существующий файл если нужно сохранить
        existing = {}
        if preserve_existing and output_path.exists():
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                existing = {}

        # Обновляем секцию platform_v3_dashboard
        existing["platform_v3_dashboard"] = dashboard

        # Создаём директорию если не существует
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Записываем файл
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    existing,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            return True
        except Exception:
            return False

    def generate_and_save(
        self,
        output_dir: str = "generated_dashboards",
        filename: Optional[str] = None,
    ) -> Path:
        """
        Генерирует и сохраняет дашборд в отдельный файл.

        Args:
            output_dir: Директория для сохранения
            filename: Имя файла (по умолчанию dashboard_<instance>.yaml)

        Returns:
            Path: Путь к сохранённому файлу
        """
        if filename is None:
            instance_id = self._manifest.instance.id
            filename = f"dashboard_{instance_id}.yaml"

        output_path = Path(output_dir) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        dashboard = self.generate_full_dashboard()

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(
                dashboard,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

        return output_path

    def validate_dashboard_config(self) -> list:
        """
        Проверяет конфигурацию дашборда на ошибки.

        Returns:
            list: Список ошибок (пустой если всё ок)
        """
        errors = []
        dashboard_config = self._manifest.dashboard

        # Проверка обязательных полей
        if not dashboard_config.title:
            errors.append("dashboard.title: Отсутствует заголовок дашборда")

        # Проверка диапазонов
        history_days = dashboard_config.history_days
        if not (1 <= history_days <= 365):
            errors.append(
                f"dashboard.history_days: Значение {history_days} вне диапазона 1-365"
            )

        return errors


def generate_dashboard_from_manifest(
    manifest_path: str,
    output_path: str,
    fsm_states: Optional[dict] = None,
) -> bool:
    """
    Удобная функция для генерации дашборда из манифеста.

    Args:
        manifest_path: Путь к YAML файлу манифеста
        output_path: Путь для сохранения дашборда
        fsm_states: Опциональные состояния FSM

    Returns:
        bool: True если успешно, False иначе
    """
    from smart_home.core.models.manifest import load_manifest

    try:
        manifest = load_manifest(manifest_path)
        generator = DashboardGenerator(manifest, fsm_states)
        generator.save_to_file(output_path=output_path)
        return True
    except Exception as e:
        print(f"Ошибка генерации дашборда: {e}")
        return False

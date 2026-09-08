"""
Генератор дашбордов Home Assistant из манифеста.

Создаёт карточки Lovelace для:
- Статуса автоматов
- Управления устройствами
- Истории переходов

Использование:
    from tools.dashboard_generator import DashboardGenerator
    
    manifest = load_manifest("instances/leonids_house/manifest.yaml")
    generator = DashboardGenerator(manifest, logger)
    
    # Сгенерировать полную панель
    dashboard = generator.generate_full_dashboard()
    generator.write_to_ha(dashboard)
"""

import yaml
from pathlib import Path
from typing import Optional
from datetime import datetime


class DashboardGenerator:
    """
    Генератор дашбордов из манифеста.

    Создаёт карточки Lovelace для:
    - Статуса автоматов (real-time)
    - Управления устройствами (кнопки)
    - Истории переходов (логи)
    """

    # Иконки для типов устройств
    DEVICE_ICONS = {
        "lighting": "mdi:lightbulb",
        "climate": "mdi:thermometer",
        "ventilation": "mdi:fan",
        "cover": "mdi:blinds",
        "switch": "mdi:power-socket",
    }

    # Цвета состояний для индикаторов
    STATE_COLORS = {
        "OFF": "#6c757d",      # серый
        "ON_SCHEDULE": "#28a745",  # зелёный
        "ON_MOTION": "#17a2b8",    # голубой
        "MANUAL": "#ffc107",       # жёлтый
        "HEATING": "#dc3545",      # красный
        "COOLING": "#007bff",      # синий
        "IDLE": "#28a745",         # зелёный
        "ACTIVE": "#28a745",       # зелёный
        "INACTIVE": "#6c757d",     # серый
    }

    def __init__(self, manifest: dict, logger=None):
        """
        Инициализация генератора.

        Args:
            manifest: Словарь с данными манифеста
            logger: Логгер для вывода сообщений
        """
        self._manifest = manifest
        self._logger = logger or self._create_default_logger()

    @staticmethod
    def _create_default_logger():
        """Создаёт простой логгер по умолчанию"""
        import logging
        logger = logging.getLogger("dashboard_generator")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            logger.addHandler(handler)
        return logger

    def _log(self, message: str, level: str = "info"):
        """Логгирование сообщения"""
        getattr(self._logger, level.lower(), self._logger.info)(message)

    def generate_automations_status_card(self) -> dict:
        """
        Генерирует карточку статуса автоматов.

        Показывает все автоматы с:
        - Текущим состоянием
        - Цветовой индикацией
        - Временем последнего перехода
        - Иконкой устройства

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        entities = []

        # Собираем все устройства из манифеста
        devices_config = self._manifest.get("devices", {})

        for device_type in ["lighting", "climate", "ventilation", "cover", "switch"]:
            devices = devices_config.get(device_type, [])
            for device in devices:
                entity_id = device["id"]
                sensor_entity = f"sensor.platform_v3_{entity_id.replace('.', '_')}_state"

                entities.append({
                    "entity": sensor_entity,
                    "name": device.get("name", entity_id),
                    "icon": self.DEVICE_ICONS.get(device_type, "mdi:robot"),
                    "secondary_info": "last-changed",
                })

        # Группируем по комнатам если есть zones
        zones = self._manifest.get("zones", [])
        if zones:
            zone_map = {zone["id"]: zone.get("name", zone["id"]) for zone in zones}
        else:
            zone_map = {}

        return {
            "type": "entities",
            "title": "🏠 Автоматы",
            "show_header_toggle": False,
            "entities": entities,
        }

    def generate_control_card(self) -> dict:
        """
        Генерирует карточку управления автоматами.

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
            "cards": [
                {
                    "type": "button",
                    **btn
                }
                for btn in buttons
            ],
        }

    def generate_history_card(self) -> dict:
        """
        Генерирует карточку истории переходов.

        Показывает историю состояний для всех устройств
        с сортировкой по времени (новые сверху).

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        entities = []
        history_days = self._manifest.get("dashboard", {}).get("history_days", 7)

        devices_config = self._manifest.get("devices", {})

        for device_type in ["lighting", "climate", "ventilation", "cover", "switch"]:
            devices = devices_config.get(device_type, [])
            for device in devices:
                entity_id = device["id"]
                history_entity = f"sensor.platform_v3_{entity_id.replace('.', '_')}_history"

                entities.append({
                    "entity": history_entity,
                    "name": device.get("name", entity_id),
                    "secondary_info": "last-changed",
                })

        return {
            "type": "entities",
            "title": f"📜 История переходов ({history_days} дн.)",
            "show_header_toggle": False,
            "entities": entities,
            "sort": {"method": "last_changed", "reverse": True},
        }

    def generate_devices_by_room_card(self) -> dict:
        """
        Генерирует карточку устройств по комнатам.

        Группирует устройства по зонам/комнатам для удобного обзора.

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        zones = self._manifest.get("zones", [])
        devices_config = self._manifest.get("devices", {})

        if not zones:
            # Если зон нет, возвращаем простую карточку
            return self.generate_automations_status_card()

        # Создаём маппинг комната → устройства
        room_devices = {zone["id"]: [] for zone in zones}

        for device_type in ["lighting", "climate", "ventilation", "cover", "switch"]:
            devices = devices_config.get(device_type, [])
            for device in devices:
                room = device.get("room")
                if room and room in room_devices:
                    room_devices[room].append({
                        "type": device_type,
                        "device": device,
                    })

        # Формируем entities для карточки
        entities = []
        for zone in zones:
            zone_id = zone["id"]
            zone_name = zone.get("name", zone_id)
            devices_in_room = room_devices.get(zone_id, [])

            # Добавляем заголовок комнаты
            entities.append({
                "content": f"**{zone_name}**",
                "type": "custom:markdown",
            })

            # Добавляем устройства в комнате
            for item in devices_in_room:
                device = item["device"]
                entity_id = device["id"]
                sensor_entity = f"sensor.platform_v3_{entity_id.replace('.', '_')}_state"

                entities.append({
                    "entity": sensor_entity,
                    "name": device.get("name", entity_id),
                    "icon": self.DEVICE_ICONS.get(item["type"], "mdi:device"),
                    "secondary_info": "last-changed",
                })

            # Пустая строка между комнатами
            entities.append({"content": "", "type": "custom:markdown"})

        return {
            "type": "entities",
            "title": "🏠 Устройства по комнатам",
            "show_header_toggle": False,
            "entities": entities,
        }

    def generate_motion_sensors_card(self) -> dict:
        """
        Генерирует карточку датчиков движения.

        Показывает статус всех датчиков движения из манифеста.

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        show_motion = self._manifest.get("dashboard", {}).get("show_motion_sensors", True)
        if not show_motion:
            return None

        entities = []
        devices_config = self._manifest.get("devices", {})

        # Собираем все motion сенсоры
        seen_sensors = set()
        for device_type in ["lighting", "climate", "ventilation"]:
            devices = devices_config.get(device_type, [])
            for device in devices:
                motion_sensor = device.get("motion_sensor")
                if motion_sensor and motion_sensor not in seen_sensors:
                    seen_sensors.add(motion_sensor)
                    entities.append({
                        "entity": motion_sensor,
                        "name": f"Движение: {device.get('name', device['id'])}",
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

    def generate_climate_overview_card(self) -> dict:
        """
        Генерирует карточку обзора климата.

        Показывает температуру, целевую температуру и режим работы
        для всех климатических устройств.

        Returns:
            dict: Конфигурация карточки Lovelace
        """
        show_climate = self._manifest.get("dashboard", {}).get("show_climate", True)
        if not show_climate:
            return None

        entities = []
        climate_devices = self._manifest.get("devices", {}).get("climate", [])

        for device in climate_devices:
            entity_id = device["id"]
            sensor_entity = device.get("sensor", f"sensor.{entity_id.replace('.', '_')}_temperature")
            target_entity = f"number.{entity_id.replace('.', '_')}_target_temp"

            entities.append({
                "entity": sensor_entity,
                "name": device.get("name", entity_id),
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

    def generate_full_dashboard(self) -> dict:
        """
        Генерирует полный дашборд со всеми карточками.

        Создаёт многостраничный дашборд с:
        - Главной страницей (статус + управление)
        - Страницей истории
        - Страницей по комнатам (опционально)

        Returns:
            dict: Полная конфигурация дашборда Lovelace
        """
        dashboard_config = self._manifest.get("dashboard", {})
        title = dashboard_config.get("title", "Smart Home")

        views = []

        # === Главная страница ===
        main_cards = []

        # Карточка управления (всегда)
        main_cards.append(self.generate_control_card())

        # Карточка статуса автоматов (всегда)
        main_cards.append(self.generate_automations_status_card())

        # Датчики движения (если включено)
        motion_card = self.generate_motion_sensors_card()
        if motion_card:
            main_cards.append(motion_card)

        # Климат (если включено)
        climate_card = self.generate_climate_overview_card()
        if climate_card:
            main_cards.append(climate_card)

        views.append({
            "title": "Главная",
            "icon": "mdi:home",
            "cards": main_cards,
        })

        # === Страница истории (если включено) ===
        if dashboard_config.get("show_history", True):
            views.append({
                "title": "История",
                "icon": "mdi:history",
                "cards": [self.generate_history_card()],
            })

        # === Страница по комнатам (если есть зоны) ===
        if self._manifest.get("zones"):
            views.append({
                "title": "Комнаты",
                "icon": "mdi:floor-plan",
                "cards": [self.generate_devices_by_room_card()],
            })

        return {
            "title": title,
            "views": views,
        }

    def write_to_ha(
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
            output_path = self._manifest.get("dashboard", {}).get(
                "output_path",
                "~/.homeassistant/ui-lovelace.yaml"
            )
        output_path = Path(output_path).expanduser()

        # Читаем существующий файл если нужно сохранить
        existing = {}
        if preserve_existing and output_path.exists():
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
                self._log(f"Прочитан существующий файл: {output_path}")
            except Exception as e:
                self._log(f"Ошибка чтения файла: {e}", "warning")
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
            self._log(f"Дашборд записан в {output_path}")
            return True
        except Exception as e:
            self._log(f"Ошибка записи файла: {e}", "error")
            return False

    def generate_and_save(
        self,
        output_dir: str = "generated_dashboards",
        filename: Optional[str] = None,
    ) -> Path:
        """
        Генерирует и сохраняет дашборд в отдельный файл.

        Удобно для тестирования и отладки.

        Args:
            output_dir: Директория для сохранения
            filename: Имя файла (по умолчанию dashboard_<instance>.yaml)

        Returns:
            Path: Путь к сохранённому файлу
        """
        if filename is None:
            instance_id = self._manifest.get("instance", {}).get("id", "smart_home")
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

        self._log(f"Дашборд сохранён в {output_path}")
        return output_path

    def validate_dashboard_config(self) -> list:
        """
        Проверяет конфигурацию дашборда на ошибки.

        Returns:
            list: Список ошибок (пустой если всё ок)
        """
        errors = []
        dashboard_config = self._manifest.get("dashboard", {})

        # Проверка обязательных полей
        if "title" not in dashboard_config:
            errors.append("dashboard.title: Отсутствует заголовок дашборда")

        # Проверка диапазонов
        history_days = dashboard_config.get("history_days", 7)
        if not (1 <= history_days <= 365):
            errors.append(
                f"dashboard.history_days: Значение {history_days} вне диапазона 1-365"
            )

        return errors

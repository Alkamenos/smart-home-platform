#!/usr/bin/env python3
"""
Dashboard Generator V2 — автоматическая генерация дашбордов из манифеста.
"""
import yaml
import os

class DashboardGenerator:
    """Генератор дашбордов из манифеста"""
    
    def __init__(self, manifest: dict):
        self._manifest = manifest
        # Преобразуем группы из списка в словарь
        self._groups_dict = self._normalize_groups(manifest.get("groups", []))
    
    def _normalize_groups(self, groups) -> dict:
        """Преобразовать группы из списка в словарь"""
        if isinstance(groups, dict):
            return groups
        
        result = {}
        for group in groups:
            if isinstance(group, dict):
                group_id = str(group.get("id", "unknown"))
                result[group_id] = group
        return result
    
    def _get_groups(self) -> dict:
        """Получить группы как словарь"""
        return self._groups_dict
    
    def generate_home_dashboard(self) -> dict:
        """Сгенерировать главный дашборд (по комнатам)."""
        views = []
        
        # Собираем все комнаты
        rooms = set(self._manifest.get("rooms", []))
        
        # Добавляем комнаты из групп света
        for group in self._get_groups().values():
            room = group.get("room")
            if room and room != "unknown":
                rooms.add(room)
        
        # Сортируем комнаты в нужном порядке
        room_order = ["gostinnaia", "kitchen", "spalnia", "kabinet", "sanuzel", "gostevaia_spalnia"]
        sorted_rooms = [r for r in room_order if r in rooms]
        sorted_rooms += [r for r in sorted(rooms) if r not in sorted_rooms]
        
        for room_id in sorted_rooms:
            room_title = self._get_room_title(room_id)
            cards = self._generate_room_cards(room_id)
            
            views.append({
                "title": room_title,
                "path": room_id,
                "icon": self._get_room_icon(room_id),
                "cards": cards
            })
        
        return {
            "title": "Дом",
            "views": views
        }
    
    def generate_settings_dashboard(self) -> dict:
        """Сгенерировать дашборд настроек."""
        views = []
        
        views.append({
            "title": "💡 Общее",
            "path": "general",
            "icon": "mdi:cog",
            "cards": self._generate_general_settings()
        })
        
        if "lighting" in self._manifest.get("features", {}):
            views.append({
                "title": "💡 Освещение",
                "path": "lighting",
                "icon": "mdi:lightbulb",
                "cards": self._generate_lighting_settings()
            })
        
        if "ventilation" in self._manifest.get("features", {}):
            views.append({
                "title": "💨 Вентиляция",
                "path": "ventilation",
                "icon": "mdi:fan",
                "cards": self._generate_ventilation_settings()
            })
        
        return {
            "title": "Настройки",
            "views": views
        }
    
    def generate_admin_dashboard(self) -> dict:
        """Сгенерировать дашборд администратора."""
        views = [
            {
                "title": "⚙️ Фичи",
                "path": "features",
                "icon": "mdi:toggle-switch",
                "cards": self._generate_feature_cards()
            },
            {
                "title": "🔧 Диагностика",
                "path": "diagnostics",
                "icon": "mdi:wrench",
                "cards": self._generate_diagnostics_cards()
            }
        ]
        
        return {
            "title": "Админ",
            "views": views
        }
    
    def generate_fsm_dashboard(self) -> dict:
        """Сгенерировать дашборд автоматов."""
        cards = []
        
        cards.append({
            "type": "custom:mushroom-title-card",
            "title": "🤖 Автоматы освещения"
        })
        
        for group_id, group in self._get_groups().items():
            group_name = group.get("name", group_id)
            fsm_sensor = f"sensor.light_{group_id}_fsm_state"
            
            cards.append({
                "type": "custom:mushroom-template-card",
                "entity": fsm_sensor,
                "primary": group_name,
                "secondary": "Состояние: {{ states(entity) if states(entity) not in ('unknown', 'unavailable') else 'OFF' }}",
                "icon": "mdi:robot",
                "icon_color": "blue"
            })
        
        cards.append({
            "type": "custom:mushroom-title-card",
            "title": "💨 Автоматы вентиляции"
        })
        
        vent_devices = [d for d in self._manifest.get("devices", {}).values() 
                        if d.get("capabilities", {}).get("fan")]
        for device in vent_devices:
            entity = device.get("entity")
            if entity:
                # Сенсор состояния FSM для автомата вентиляции
                sensor_name = "sensor." + entity.replace(".", "_") + "_fsm_state"
                device_name = device.get("name", entity)
                
                cards.append({
                    "type": "custom:mushroom-template-card",
                    "entity": sensor_name,
                    "primary": device_name,
                    "secondary": "Состояние: {{ states(entity) if states(entity) not in ('unknown', 'unavailable') else 'OFF' }}",
                    "icon": "mdi:robot",
                    "icon_color": "green"
                })
        
        views = [
            {
                "title": "🤖 FSM Обзор",
                "path": "fsm-overview",
                "icon": "mdi:state-machine",
                "cards": cards
            }
        ]
        
        return {
            "title": "Автоматы",
            "views": views
        }
    
    def _get_room_title(self, room_id: str) -> str:
        titles = {
            "gostinnaia": "🛋️ Гостиная",
            "kitchen": "🍳 Кухня",
            "spalnia": "🛏️ Спальня",
            "kabinet": "💼 Кабинет",
            "sanuzel": "🚿 Санузел",
            "gostevaia_spalnia": "🛏️ Гостевая спальня",
        }
        return titles.get(room_id, room_id.replace("_", " ").title())
    
    def _get_room_icon(self, room_id: str) -> str:
        icons = {
            "gostinnaia": "mdi:sofa",
            "kitchen": "mdi:stove",
            "spalnia": "mdi:bed",
            "kabinet": "mdi:desk",
            "sanuzel": "mdi:shower",
            "gostevaia_spalnia": "mdi:bed-empty",
        }
        return icons.get(room_id, "mdi:home")
    
    def _generate_room_cards(self, room_id: str) -> list:
        """Сгенерировать карточки для комнаты"""
        cards = []
        
        # Свет в этой комнате
        room_groups = [g for g in self._get_groups().values() 
                       if g.get("room") == room_id]
        
        if room_groups:
            cards.append({"type": "custom:mushroom-title-card", "title": "💡 Свет"})
            for group in room_groups:
                devices = group.get("devices", [])
                for device in devices:
                    if isinstance(device, dict):
                        entity = device.get("entity")
                        name = group.get("name", "Свет")
                    else:
                        device_obj = self._manifest.get("devices", {}).get(device, {})
                        entity = device_obj.get("entity")
                        name = group.get("name", "Свет")
                    
                    if entity:
                        cards.append({
                            "type": "custom:mushroom-entity-card",
                            "entity": entity,
                            "name": name
                        })
        
        # Устройства в этой комнате
        room_devices = [d for d in self._manifest.get("devices", {}).values() 
                        if d.get("room") == room_id]
        
        # Вентиляторы
        fan_devices = [d for d in room_devices if d.get("capabilities", {}).get("fan")]
        if fan_devices:
            cards.append({"type": "custom:mushroom-title-card", "title": "💨 Вентиляция"})
            for device in fan_devices:
                cards.append({
                    "type": "custom:mushroom-fan-card",
                    "entity": device.get("entity"),
                    "name": device.get("name")
                })
        
        # Шторы
        cover_devices = [d for d in room_devices if d.get("capabilities", {}).get("cover")]
        if cover_devices:
            cards.append({"type": "custom:mushroom-title-card", "title": "🪟 Шторы"})
            for device in cover_devices:
                cards.append({
                    "type": "custom:mushroom-cover-card",
                    "entity": device.get("entity"),
                    "name": device.get("name")
                })
        
        # Сенсоры температуры
        temp_devices = [d for d in room_devices 
                        if "temperature" in d.get("entity", "") or "temp" in d.get("entity", "")]
        if temp_devices:
            cards.append({"type": "custom:mushroom-title-card", "title": "🌡️ Температура"})
            for device in temp_devices:
                cards.append({
                    "type": "custom:mushroom-entity-card",
                    "entity": device.get("entity"),
                    "name": "Температура"
                })
        
        # Заглушка если нет устройств
        if not cards:
            cards.append({
                "type": "markdown",
                "content": f"**Нет устройств в комнате '{room_id}'**"
            })
        
        return cards
    
    def _generate_general_settings(self) -> list:
        """Сгенерировать общие настройки"""
        return [
            {
                "type": "entities",
                "title": "Глобальные режимы",
                "entities": [
                    {"entity": "input_boolean.zima", "name": "Зима"},
                    {"entity": "input_boolean.vecher", "name": "Вечер"},
                    {"entity": "input_boolean.my_doma", "name": "Дома"},
                    {"entity": "input_boolean.party_mode", "name": "Вечеринка"},
                ]
            },
            {
                "type": "entities",
                "title": "Температура",
                "entities": [
                    {"entity": "input_number.temperatura", "name": "Целевая температура"},
                    {"entity": "input_number.maksimalno_komfortnaia_temperatura", "name": "Максимальная температура"},
                    {"entity": "input_number.temperatura_v_sanuzle", "name": "Температура в санузле"},
                ]
            },
            {
                "type": "entities",
                "title": "Освещение (глобально)",
                "entities": [
                    {"entity": "input_boolean.feature_color_temp", "name": "Авто color temp"},
                    {"entity": "input_boolean.feature_backlight", "name": "Подсветка выключателей"},
                    {"entity": "input_boolean.feature_imitation", "name": "Имитация присутствия"},
                ]
            }
        ]
    
    def _generate_lighting_settings(self) -> list:
        """Сгенерировать настройки освещения"""
        cards = []
        
        cards.append({
            "type": "entities",
            "title": "Температура света",
            "entities": [
                {"entity": "input_number.ct_day_kelvin", "name": "Дневная, K"},
                {"entity": "input_number.ct_night_kelvin", "name": "Ночная, K"},
                {"entity": "input_datetime.ct_warm_from", "name": "Смягчать с"},
                {"entity": "input_datetime.ct_night_from", "name": "Ночная с"},
            ]
        })
        
        for group_id, group in self._get_groups().items():
            if group.get("features", {}).get("motion"):
                group_name = group.get("name", group_id)
                cards.append({
                    "type": "entities",
                    "title": f"Движение: {group_name}",
                    "entities": [
                        {"entity": f"input_select.light_{group_id}_motion_mode", "name": "Режим"},
                        {"entity": f"input_boolean.light_{group_id}_motion_day", "name": "Днём"},
                    ]
                })
        
        return cards
    
    def _generate_ventilation_settings(self) -> list:
        """Сгенерировать настройки вентиляции"""
        cards = []
        
        vent_devices = [d for d in self._manifest.get("devices", {}).values() 
                        if d.get("capabilities", {}).get("fan")]
        if vent_devices:
            entities = []
            for device in vent_devices:
                entities.append({
                    "entity": device.get("entity"),
                    "name": device.get("name", "Вентилятор")
                })
            cards.append({
                "type": "entities",
                "title": "Устройства вентиляции",
                "entities": entities
            })
        
        vent_config = self._manifest.get("features", {}).get("ventilation", {}).get("config", {})
        vent_flags = vent_config.get("flags", {})
        if vent_flags:
            entities = []
            flag_names = {
                "boost_intake": "Проветривание (приток)",
                "boost_exhaust": "Проветривание (вытяжка)",
                "night": "Ночной режим",
                "away_home": "Дома",
            }
            for flag_key, flag_entity in vent_flags.items():
                name = flag_names.get(flag_key, flag_key)
                entities.append({"entity": flag_entity, "name": name})
            
            if entities:
                cards.append({
                    "type": "entities",
                    "title": "Режимы вентиляции",
                    "entities": entities
                })
        
        vent_sensors = vent_config.get("sensors", {})
        if vent_sensors:
            entities = []
            sensor_names = {
                "outdoor_temp": "Температура на улице",
                "outdoor_humidity": "Влажность на улице",
                "house_humidity": "Влажность в доме",
            }
            for sensor_key, sensor_entity in vent_sensors.items():
                name = sensor_names.get(sensor_key, sensor_key)
                entities.append({"entity": sensor_entity, "name": name})
            
            if entities:
                cards.append({
                    "type": "entities",
                    "title": "Сенсоры",
                    "entities": entities
                })
        
        return cards
    
    def _generate_feature_cards(self) -> list:
        """Сгенерировать карточки фич"""
        cards = []
        for feature_id, feature in self._manifest.get("features", {}).items():
            cards.append({
                "type": "custom:mushroom-entity-card",
                "entity": f"input_boolean.feature_{feature_id}",
                "name": feature_id.replace("_", " ").title()
            })
        return cards
    
    def _generate_diagnostics_cards(self) -> list:
        """Сгенерировать карточки диагностики"""
        return [
            {
                "type": "markdown",
                "title": "🏥 Диагностика платформы",
                "content": """{% set status = states('sensor.platform_v2_status') %}
{% if status == 'unknown' or status == 'unavailable' %}
⚠️ Сенсор статуса не создан. Нажмите кнопку ниже.
{% else %}
**Статус:** {{ status }}
**Комнаты:** {{ state_attr('sensor.platform_v2_status', 'rooms') }}
**Фичи:** {{ state_attr('sensor.platform_v2_status', 'features') }}
**Групп:** {{ state_attr('sensor.platform_v2_status', 'groups_count') }}
{% endif %}"""
            },
            {
                "type": "button",
                "name": "🔄 Обновить статус",
                "icon": "mdi:refresh",
                "tap_action": {
                    "action": "call-service",
                    "service": "pyscript.platform_v2_update_status_sensor"
                }
            },
            {
                "type": "button",
                "name": "Перезапустить платформу",
                "icon": "mdi:restart",
                "tap_action": {
                    "action": "call-service",
                    "service": "pyscript.platform_v2_restart"
                }
            },
            {
                "type": "button",
                "name": "Снять блокировки",
                "icon": "mdi:lock-open",
                "tap_action": {
                    "action": "call-service",
                    "service": "pyscript.platform_v2_override_clear"
                }
            }
        ]
    
    def save_dashboard(self, dashboard: dict, path: str):
        """Сохранить дашборд в YAML файл"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(dashboard, f, allow_unicode=True, sort_keys=False)

def generate_all_dashboards(manifest: dict, output_dir: str = "/config/dashboards"):
    """Сгенерировать все дашборды"""
    generator = DashboardGenerator(manifest)
    
    home = generator.generate_home_dashboard()
    generator.save_dashboard(home, f"{output_dir}/home-dashboard.yaml")
    
    settings = generator.generate_settings_dashboard()
    generator.save_dashboard(settings, f"{output_dir}/settings-dashboard.yaml")
    
    admin = generator.generate_admin_dashboard()
    generator.save_dashboard(admin, f"{output_dir}/admin-dashboard.yaml")
    
    fsm = generator.generate_fsm_dashboard()
    generator.save_dashboard(fsm, f"{output_dir}/fsm-dashboard.yaml")

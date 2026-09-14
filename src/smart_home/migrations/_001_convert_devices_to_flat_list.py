"""Первая миграция: конвертация устройств в плоский список.

Старый формат манифеста имел устройства, сгруппированные по зонам:
    zones:
      - id: living_room
        name: Гостиная
        devices:
          - id: light_1
            name: Свет 1
            type: light_motion
            ...

Новый формат имеет плоский список устройств и отдельные зоны:
    zones:
      - id: living_room
        name: Гостиная
        floor: 1
    devices:
      - id: light_1
        name: Свет 1
        type: light_motion
        room: living_room
        ...
"""

from smart_home.migrations import Migration


class Migration001ConvertDevicesToFlatList(Migration):
    """Миграция 001: Конвертация устройств из группировки по зонам в плоский список."""
    
    version = 1
    description = "Конвертирует старый формат манифеста с устройствами внутри зон в новый формат с плоским списком устройств"
    
    def up(self, manifest: dict) -> dict:
        """Применить миграцию: конвертировать старый формат в новый.
        
        Args:
            manifest: Манифест в старом формате (устройства внутри зон).
            
        Returns:
            dict: Манифест в новом формате (плоский список устройств).
        """
        # Создаем копию манифеста для модификации
        new_manifest = dict(manifest)
        
        # Проверяем, есть ли уже плоский список устройств
        if "devices" in new_manifest and isinstance(new_manifest["devices"], list):
            # Уже новый формат, ничего не делаем
            return new_manifest
        
        # Старый формат: устройства находятся внутри зон
        devices = []
        new_zones = []
        
        zones = manifest.get("zones", [])
        for zone in zones:
            zone_id = zone.get("id", "")
            zone_name = zone.get("name", "")
            
            # Извлекаем устройства из зоны
            zone_devices = zone.get("devices", [])
            for device in zone_devices:
                # Добавляем информацию о комнате к устройству
                new_device = dict(device)
                new_device["room"] = zone_id
                new_device["behaviors"] = device.get("behaviors", [])
                devices.append(new_device)
            
            # Создаем новую зону без устройств, но с floor
            new_zone = {
                "id": zone_id,
                "name": zone_name,
                "floor": zone.get("floor", 1)
            }
            new_zones.append(new_zone)
        
        # Обновляем манифест
        new_manifest["zones"] = new_zones
        new_manifest["devices"] = devices
        
        # Устанавливаем версию, если её нет
        if "version" not in new_manifest:
            new_manifest["version"] = self.version
        
        return new_manifest
    
    def down(self, manifest: dict) -> dict:
        """Отменить миграцию: вернуть устройства внутрь зон.
        
        Args:
            manifest: Манифест в новом формате (плоский список устройств).
            
        Returns:
            dict: Манифест в старом формате (устройства внутри зон).
        """
        # Создаем копию манифеста для модификации
        new_manifest = dict(manifest)
        
        devices = manifest.get("devices", [])
        zones = manifest.get("zones", [])
        
        # Группируем устройства по комнатам (room)
        devices_by_room: dict[str, list] = {}
        for device in devices:
            room = device.get("room", "")
            if room not in devices_by_room:
                devices_by_room[room] = []
            
            # Создаем копию устройства без поля room
            new_device = {k: v for k, v in device.items() if k != "room"}
            devices_by_room[room].append(new_device)
        
        # Обновляем зоны, добавляя устройства
        new_zones = []
        for zone in zones:
            zone_id = zone.get("id", "")
            new_zone = {k: v for k, v in zone.items() if k != "floor"}
            
            # Добавляем устройства, если они есть для этой зоны
            if zone_id in devices_by_room:
                new_zone["devices"] = devices_by_room[zone_id]
            
            new_zones.append(new_zone)
        
        new_manifest["zones"] = new_zones
        
        # Удаляем плоский список устройств
        if "devices" in new_manifest:
            del new_manifest["devices"]
        
        return new_manifest

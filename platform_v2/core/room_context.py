#!/usr/bin/env python3
"""
Room Context V2 — единый контекст для всех фич.

Содержит всю информацию, необходимую для принятия решений:
- Присутствие (кто дома, в какой комнате)
- Время суток (день/вечер/ночь/утро)
- Сезон (зима/лето)
- Режимы (вечеринка, отпуск, сон)
- Освещённость (темно/светло)
"""
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class TimeOfDay(Enum):
    MORNING = "morning"
    DAY = "day"
    EVENING = "evening"
    NIGHT = "night"

class Season(Enum):
    WINTER = "winter"
    SUMMER = "summer"

class Presence(Enum):
    EMPTY = "empty"        # Никого нет
    HOME_DAY = "home_day"  # Кто-то дома, день
    HOME_NIGHT = "home_night"  # Кто-то дома, ночь
    AWAY = "away"          # Все ушли
    PARTY = "party"        # Вечеринка
    SLEEP = "sleep"        # Сон

@dataclass
class RoomContext:
    """Контекст комнаты для принятия решений"""
    room_id: str
    presence: Presence = Presence.HOME_DAY
    time_of_day: TimeOfDay = TimeOfDay.DAY
    season: Season = Season.SUMMER
    
    # Сенсоры
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    co2: Optional[float] = None
    illuminance: Optional[float] = None
    motion: bool = False
    
    # Флаги режимов
    party_mode: bool = False
    sleep_mode: bool = False
    away_mode: bool = False
    
    # Время
    current_time_min: int = 0  # Минуты от полуночи
    
    # Освещённость
    is_dark: bool = False
    
    def is_night(self) -> bool:
        return self.time_of_day == TimeOfDay.NIGHT
    
    def is_home(self) -> bool:
        return self.presence in (Presence.HOME_DAY, Presence.HOME_NIGHT)
    
    def is_empty(self) -> bool:
        return self.presence == Presence.EMPTY

class RoomContextBuilder:
    """
    Строитель контекста комнаты.
    Собирает данные из сенсоров и флагов.
    """
    
    def __init__(self):
        self._state_reader = None
        self._time_reader = None
    
    def set_state_reader(self, reader):
        """Установить функцию чтения состояний из HA"""
        self._state_reader = reader
    
    def set_time_reader(self, reader):
        """Установить функцию получения времени"""
        self._time_reader = reader
    
    def build(self, room_id: str, config: dict = None) -> RoomContext:
        """Построить контекст комнаты"""
        config = config or {}
        
        # Получаем _resolved данные (прочитанные заранее из HA)
        resolved = config.get("_resolved", {})
        resolved_global_flags = resolved.get("global_flags", {})
        
        # Время суток
        time_of_day = self._get_time_of_day()
        
        # Сезон из _resolved
        winter = resolved_global_flags.get("winter") == "on"
        season = Season.WINTER if winter else Season.SUMMER
        
        # Присутствие из _resolved
        is_home = resolved_global_flags.get("home") == "on"
        
        # Флаги из _resolved
        party = resolved_global_flags.get("party") == "on"
        sleep = resolved_global_flags.get("sleep", "off") == "on"
        away = not is_home
        
        # Сенсоры из _resolved
        # Температура
        temp_sensor = config.get("temp_sensor")
        temp = None
        if temp_sensor:
            resolved_val = resolved.get(temp_sensor)
            if resolved_val is None:
                resolved_val = resolved.get("temp_sensor")
            if resolved_val is not None:
                try:
                    temp = float(resolved_val)
                except (ValueError, TypeError):
                    temp = None
        
        # Влажность
        humidity_sensor = config.get("humidity_sensor")
        humidity = None
        if humidity_sensor:
            resolved_val = resolved.get(humidity_sensor)
            if resolved_val is None:
                resolved_val = resolved.get("humidity_sensor")
            if resolved_val is not None:
                try:
                    humidity = float(resolved_val)
                except (ValueError, TypeError):
                    humidity = None
        
        # CO2
        co2_sensor = config.get("co2_sensor")
        co2 = None
        if co2_sensor:
            resolved_val = resolved.get(co2_sensor)
            if resolved_val is None:
                resolved_val = resolved.get("co2_sensor")
            if resolved_val is not None:
                try:
                    co2 = float(resolved_val)
                except (ValueError, TypeError):
                    co2 = None
        
        # Освещённость
        illuminance_sensor = config.get("illuminance_sensor")
        illuminance = None
        if illuminance_sensor:
            resolved_val = resolved.get(illuminance_sensor)
            if resolved_val is None:
                resolved_val = resolved.get("illuminance_sensor")
            if resolved_val is not None:
                try:
                    illuminance = float(resolved_val)
                except (ValueError, TypeError):
                    illuminance = None
        
        # Движение
        motion_sensor = config.get("motion_sensor")
        motion = False
        if motion_sensor:
            resolved_val = resolved.get(motion_sensor)
            if resolved_val is None:
                resolved_val = resolved.get("motion_sensor")
            if resolved_val is not None:
                motion = resolved_val in ("on", "true", True)
        
        # Темнота: флаг "вечер" или низкая освещённость
        night_flag = resolved_global_flags.get("night") == "on"
        
        is_dark = night_flag
        if illuminance is not None:
            dark_lux = 20  # порог темноты
            is_dark = illuminance < dark_lux or night_flag
        
        # Определяем presence
        if party:
            presence = Presence.PARTY
        elif sleep:
            presence = Presence.SLEEP
        elif away:
            presence = Presence.AWAY
        elif time_of_day == TimeOfDay.NIGHT:
            presence = Presence.HOME_NIGHT
        else:
            presence = Presence.HOME_DAY
        
        # Определяем время в минутах от полуночи
        current_time_min = 0
        if self._time_reader:
            time_now = self._time_reader()
            current_time_min = time_now.tm_hour * 60 + time_now.tm_min
        
        return RoomContext(
            room_id=room_id,
            presence=presence,
            time_of_day=time_of_day,
            season=season,
            temperature=temp,
            humidity=humidity,
            co2=co2,
            illuminance=illuminance,
            motion=motion,
            party_mode=party,
            sleep_mode=sleep,
            away_mode=away,
            current_time_min=current_time_min,
            is_dark=is_dark,
        )
    
    def _get_time_of_day(self) -> TimeOfDay:
        """Определить время суток"""
        if not self._time_reader:
            return TimeOfDay.DAY
        
        time_now = self._time_reader()
        hour = time_now.tm_hour
        
        if 6 <= hour < 10:
            return TimeOfDay.MORNING
        elif 10 <= hour < 18:
            return TimeOfDay.DAY
        elif 18 <= hour < 23:
            return TimeOfDay.EVENING
        else:
            return TimeOfDay.NIGHT
    
    def _get_flag(self, entity_id: str, invert: bool = False) -> bool:
        """Прочитать флаг из HA (используется только если нет _resolved)"""
        if not self._state_reader:
            return False
        state = self._state_reader(entity_id)
        if state is None or hasattr(state, "__await__"):
            result = False
        else:
            result = str(state) == "on"
        return not result if invert else result
    
    def _get_float(self, entity_id: str) -> Optional[float]:
        """Прочитать числовое значение (используется только если нет _resolved)"""
        if not self._state_reader:
            return None
        state = self._state_reader(entity_id)
        if state is None or hasattr(state, "__await__"):
            return None
        state_str = str(state)
        if state_str in ("unknown", "unavailable", ""):
            return None
        try:
            return float(state_str)
        except (ValueError, TypeError):
            return None
    
    def _get_bool(self, entity_id: str) -> bool:
        """Прочитать булево значение (используется только если нет _resolved)"""
        if not self._state_reader:
            return False
        state = self._state_reader(entity_id)
        if state is None or hasattr(state, "__await__"):
            return False
        return str(state) in ("on", "true", "True", True)

# Глобальный экземпляр строителя
CONTEXT_BUILDER = RoomContextBuilder()

#!/usr/bin/env python3
"""
Lighting Feature V2 — управление освещением.
"""
from typing import Optional
from platform_v2.core.feature_base import FeatureBase, FeatureDecision, Action
from platform_v2.core.fsm_engine import FSMEngine, FSMDefinition
from platform_v2.core.room_context import RoomContext, TimeOfDay, Season
from platform_v2.core.sync_engine import SyncEngine

class LightingFeature(FeatureBase):
    """Фича управления освещением"""
    
    def __init__(self, config: dict, sync_engine: SyncEngine):
        super().__init__("lighting", config, sync_engine)
        self._fsm = FSMEngine()
        self._groups = config.get("groups", {})
        self._color_temp = config.get("color_temp", {})
        
        # Логируем количество групп
        print(f"[LIGHTING] Init with {len(self._groups)} groups")
        for gid in list(self._groups.keys())[:3]:
            print(f"[LIGHTING]   Group: {gid}")
        
        # Регистрируем FSM для каждой группы
        self._register_fsm()
    
    def _register_fsm(self):
        """Зарегистрировать FSM для всех групп"""
        registered = 0
        for group_id, group_config in self._groups.items():
            fsm_config = group_config.get("fsm")
            if not fsm_config:
                continue
            
            definition = FSMDefinition(
                states=fsm_config.get("states", []),
                initial=fsm_config.get("initial", "OFF"),
                transitions=fsm_config.get("transitions", []),
                debounce_sec=fsm_config.get("debounce_sec", 0),
                debounce_exempt=set(fsm_config.get("debounce_exempt", []))
            )
            
            entity_id = f"light.{group_id}"
            self._fsm.register(entity_id, definition)
            registered += 1
        
        print(f"[LIGHTING] Registered {registered} FSM instances")
    
    def build_context(self, room_context: RoomContext) -> dict:
        """Собрать контекст для FSM освещения."""
        return {
            "dark": room_context.is_dark,
            "night": room_context.is_night(),
            "room_ok": room_context.is_home(),
            "motion": room_context.motion,
            "motion_mode": "Включать и выключать",
            "motion_day": False,
            "nightlight_enabled": True,
            "time_min": room_context.current_time_min,
        }
    
    def decide(self, room_context: RoomContext) -> FeatureDecision:
        """Принять решение для всех групп освещения"""
        ctx = self.build_context(room_context)
        actions = []
        
        if not self._groups:
            print("[LIGHTING] No groups to process")
            return FeatureDecision(actions=[])
        
        for group_id, group_config in self._groups.items():
            # Получаем реальный entity из группы
            devices = group_config.get("devices", [])
            entity_id = None
            
            if devices:
                first_device = devices[0]
                if isinstance(first_device, dict):
                    entity_id = first_device.get("entity")
                elif isinstance(first_device, str):
                    entity_id = first_device
            
            if not entity_id:
                entity_id = f"light.{group_id}"
            
            # FSM ключ всегда виртуальный
            fsm_key = f"light.{group_id}"
            
            # Определяем триггеры на основе контекста
            triggers = self._build_triggers(ctx, group_config)
            
            # Пробуем каждый триггер
            for trigger in triggers:
                if self._fsm.trigger(fsm_key, trigger, src="автоматика", ctx=ctx):
                    break
            
            # Получаем текущее состояние и формируем действие
            state = self._fsm.get_state(fsm_key)
            action = self._state_to_action(entity_id, state, group_config)
            if action:
                actions.append(action)
        
        return FeatureDecision(
            actions=actions,
            fsm_state=self._fsm.get_state(f"light.{list(self._groups.keys())[0]}") if self._groups else None,
            context_snapshot=ctx
        )
    
    def _build_triggers(self, ctx: dict, group_config: dict) -> list:
        """Определить активные триггеры на основе контекста и конфигурации группы"""
        triggers = []
        features = group_config.get("features", {})
        
        # Движение — только для групп с фичей motion
        if features.get("motion") and ctx.get("motion"):
            if ctx.get("night") and ctx.get("nightlight_enabled"):
                triggers.append("night_motion")
            else:
                triggers.append("motion")
        
        # Расписание — только для групп с фичей schedule или dusk
        has_schedule = features.get("schedule") is not None
        has_dusk = features.get("dusk") is not None
        
        if has_schedule or has_dusk:
            # Проверяем время включения/выключения из конфигурации
            schedule = features.get("schedule", {})
            dusk = features.get("dusk", {})
            
            # Определяем нужно ли включать по расписанию
            should_turn_on = False
            should_turn_off = False
            
            if has_dusk:
                # Включение по закату/темноте
                require_dark = dusk.get("require_dark", False)
                if ctx.get("dark") and (not require_dark or ctx.get("dark")):
                    should_turn_on = True
                elif not ctx.get("dark"):
                    should_turn_off = True
            
            if has_schedule:
                # Проверяем время включения/выключения
                on_time = schedule.get("true")  # время включения
                off_time = schedule.get("false")  # время выключения
                
                current_min = ctx.get("time_min", 0)
                
                if on_time and off_time:
                    on_min = self._parse_time(on_time)
                    off_min = self._parse_time(off_time)
                    
                    if on_min is not None and off_min is not None:
                        if on_min <= current_min < off_min:
                            should_turn_on = True
                        else:
                            should_turn_off = True
                elif off_time:
                    # Только время выключения
                    off_min = self._parse_time(off_time)
                    if off_min is not None and current_min >= off_min:
                        should_turn_off = True
            
            # schedule_off имеет приоритет над schedule_on
            if should_turn_off:
                triggers.append("schedule_off")
            elif should_turn_on:
                triggers.append("schedule_on")
        
        return triggers
    
    def _parse_time(self, time_str) -> Optional[int]:
        """Преобразовать время в минуты от полуночи"""
        if time_str is None:
            return None
        
        # Обработка sunrise/sunset
        if time_str in ("sunrise", "sunset"):
            # Для простоты: sunrise=06:00, sunset=21:00 (лето)
            return 6 * 60 if time_str == "sunrise" else 21 * 60
        
        # Обработка "23:00" формата
        if isinstance(time_str, str) and ":" in time_str:
            try:
                hours, minutes = time_str.split(":")
                return int(hours) * 60 + int(minutes)
            except (ValueError, AttributeError):
                return None
        
        return None
    
    def _state_to_action(self, entity_id: str, state: str, group_config: dict) -> Optional[Action]:
        """Преобразовать состояние FSM в действие"""
        if state is None:
            return None
        
        if state == "OFF":
            return Action(
                entity_id=entity_id,
                state="off",
                reason="FSM: OFF"
            )
        elif state in ("ON_SCHEDULE", "ON_MOTION", "PARTY"):
            brightness = 100
            return Action(
                entity_id=entity_id,
                state="on",
                attributes={"brightness_pct": brightness},
                reason=f"FSM: {state}"
            )
        elif state == "NIGHTLIGHT":
            nightlight_config = group_config.get("features", {}).get("nightlight", {})
            brightness = nightlight_config.get("brightness", 40)
            return Action(
                entity_id=entity_id,
                state="on",
                attributes={"brightness_pct": brightness},
                reason="FSM: NIGHTLIGHT"
            )
        elif state == "MANUAL_LOCK":
            return None
        elif state == "UNAVAILABLE":
            return None
        
        return None
    
    def apply(self, decision: FeatureDecision) -> None:
        """Применить решение через SyncEngine"""
        for action in decision.actions:
            # Не устанавливаем desired если устройство заблокировано вручную
            if self._sync.is_manual_locked(action.entity_id):
                continue
            
            self._sync.set_desired(
                entity_id=action.entity_id,
                state=action.state,
                attributes=action.attributes,
                source=action.source,
                reason=action.reason
            )
    
    def get_status(self) -> dict:
        """Получить статус фичи"""
        base = super().get_status()
        base.update({
            "groups": list(self._groups.keys()),
            "groups_count": len(self._groups),
        })
        return base

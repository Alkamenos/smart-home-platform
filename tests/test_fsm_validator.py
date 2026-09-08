"""
Тесты для валидатора FSM графов

Проверяют все 6 типов валидации:
1. initial не в states
2. to_state не существует
3. from_state не существует
4. Нет переходов из initial
5. Граф несвязный
6. Дубликаты переходов
"""

import pytest
from core.fsm_validator import (
    validate_definition,
    FSMValidationError,
    Transition,
    FSMDefinition
)


class TestValidateInitialNotInStates:
    """Тест проверки 1: initial состояние должно быть в списке states"""
    
    def test_validate_initial_not_in_states(self):
        """Должна падать ошибка если initial不在 states"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("ON", "OFF"),
            initial="INVALID_STATE",  # Не существует в states
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on"
                ),
            )
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "Initial state 'INVALID_STATE' not found in states" in str(exc_info.value)
        assert "light.test" in str(exc_info.value)


class TestValidateToStateNotExists:
    """Тест проверки 2: to_state должен существовать в states"""
    
    def test_validate_to_state_not_exists(self):
        """Должна падать ошибка если to_state不在 states"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("ON", "OFF"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="INVALID_TO_STATE",  # Не существует
                    trigger="turn_on"
                ),
            )
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "to_state 'INVALID_TO_STATE' not found in states" in str(exc_info.value)


class TestValidateFromStateNotExists:
    """Тест проверки 3: from_state должен существовать в states"""
    
    def test_validate_from_state_not_exists(self):
        """Должна падать ошибка если from_state不在 states"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("ON", "OFF"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="INVALID_FROM_STATE",  # Не существует
                    to_state="ON",
                    trigger="turn_on"
                ),
            )
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "from_state 'INVALID_FROM_STATE' not found in states" in str(exc_info.value)
    
    def test_validate_from_state_tuple_not_exists(self):
        """Должна падать ошибка если один из from_state в кортеже不在 states"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("ON", "OFF"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state=("OFF", "INVALID_STATE"),  # Один не существует
                    to_state="ON",
                    trigger="turn_on"
                ),
            )
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "from_state 'INVALID_STATE' not found in states" in str(exc_info.value)


class TestValidateNoOutgoingFromInitial:
    """Тест проверки 4: должен быть хотя бы один переход из initial"""
    
    def test_validate_no_outgoing_from_initial(self):
        """Должна падать ошибка если нет переходов из initial"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON", "BLINK"),
            initial="OFF",
            transitions=(
                # Переходы только между ON и BLINK, нет из OFF
                Transition(
                    from_state="ON",
                    to_state="BLINK",
                    trigger="blink"
                ),
                Transition(
                    from_state="BLINK",
                    to_state="ON",
                    trigger="stop_blink"
                ),
            )
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "No outgoing transitions from initial state 'OFF'" in str(exc_info.value)


class TestValidateDisconnectedGraph:
    """Тест проверки 5: граф должен быть связный"""
    
    def test_validate_disconnected_graph(self):
        """Должна падать ошибка если есть недостижимые состояния"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON", "UNREACHABLE"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on"
                ),
                Transition(
                    from_state="ON",
                    to_state="OFF",
                    trigger="turn_off"
                ),
                # UNREACHABLE состояние не достижимо из OFF или ON
            )
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "Unreachable states from initial 'OFF'" in str(exc_info.value)
        assert "UNREACHABLE" in str(exc_info.value)


class TestValidateDuplicateTransitions:
    """Тест проверки 6: не должно быть дубликатов с одинаковым приоритетом"""
    
    def test_validate_duplicate_transitions_same_priority(self):
        """Должна падать ошибка если есть дубликаты с одинаковым приоритетом"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON", "DIM"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    priority=10
                ),
                Transition(
                    from_state="OFF",
                    to_state="DIM",  # Другое состояние
                    trigger="turn_on",  # Тот же триггер
                    priority=10  # Тот же приоритет - ЭТО ОШИБКА
                ),
            )
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "Duplicate transitions with same" in str(exc_info.value)
        assert "turn_on" in str(exc_info.value)
        assert "priority=10" in str(exc_info.value)
    
    def test_validate_duplicate_transitions_different_priority_ok(self):
        """Дубликаты с разными приоритетами допустимы"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON", "DIM"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    priority=10
                ),
                Transition(
                    from_state="OFF",
                    to_state="DIM",
                    trigger="turn_on",
                    priority=20  # Другой приоритет - ОК
                ),
            )
        )
        
        # Не должно падать
        validate_definition(definition)


class TestValidateValidDefinitionPasses:
    """Тест что валидные определения проходят валидацию"""
    
    def test_validate_valid_simple_definition(self):
        """Простой валидный автомат"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on"
                ),
                Transition(
                    from_state="ON",
                    to_state="OFF",
                    trigger="turn_off"
                ),
            )
        )
        
        # Не должно падать
        validate_definition(definition)
    
    def test_validate_valid_wildcard_from_state(self):
        """Валидный автомат с wildcard from_state"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON", "PARTY"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on"
                ),
                Transition(
                    from_state="*",  # Из любого состояния
                    to_state="PARTY",
                    trigger="party_mode",
                    priority=50
                ),
                Transition(
                    from_state="PARTY",
                    to_state="OFF",
                    trigger="party_off"
                ),
                Transition(
                    from_state="ON",
                    to_state="OFF",
                    trigger="turn_off"
                ),
            )
        )
        
        # Не должно падать
        validate_definition(definition)
    
    def test_validate_valid_tuple_from_state(self):
        """Валидный автомат с tuple from_state"""
        definition = FSMDefinition(
            entity_id="light.test",
            states=("OFF", "ON", "DIM", "BRIGHT"),
            initial="OFF",
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on"
                ),
                Transition(
                    from_state=("ON", "DIM", "BRIGHT"),  # Из нескольких состояний
                    to_state="OFF",
                    trigger="turn_off"
                ),
                # Добавляем переходы для связности графа
                Transition(
                    from_state="ON",
                    to_state="DIM",
                    trigger="dim"
                ),
                Transition(
                    from_state="DIM",
                    to_state="BRIGHT",
                    trigger="brighten"
                ),
                Transition(
                    from_state="BRIGHT",
                    to_state="ON",
                    trigger="normal"
                ),
            )
        )
        
        # Не должно падать
        validate_definition(definition)
    
    def test_validate_valid_complex_graph(self):
        """Сложный связный граф"""
        definition = FSMDefinition(
            entity_id="light.living_room",
            states=("OFF", "ON_SCHEDULE", "ON_MOTION", "PARTY", "NIGHTLIGHT", "MANUAL"),
            initial="OFF",
            transitions=(
                Transition(from_state="OFF", to_state="ON_SCHEDULE", trigger="schedule_on"),
                Transition(from_state="ON_SCHEDULE", to_state="OFF", trigger="schedule_off"),
                Transition(from_state=("OFF", "ON_SCHEDULE"), to_state="ON_MOTION", trigger="motion_detected"),
                Transition(from_state="ON_MOTION", to_state="OFF", trigger="motion_cleared"),
                Transition(from_state="*", to_state="PARTY", trigger="party_mode_on", priority=50),
                Transition(from_state="PARTY", to_state="OFF", trigger="party_mode_off"),
                Transition(from_state="*", to_state="NIGHTLIGHT", trigger="night_mode_on", priority=40),
                Transition(from_state="NIGHTLIGHT", to_state="OFF", trigger="night_mode_off"),
                Transition(from_state="*", to_state="MANUAL", trigger="manual_change", priority=100),
                Transition(from_state="MANUAL", to_state="OFF", trigger="timeout"),
            )
        )
        
        # Не должно падать
        validate_definition(definition)


class TestValidateWithEntityIdInError:
    """Тест что entity_id правильно подставляется в ошибки"""
    
    def test_error_contains_entity_id(self):
        """entity_id должен быть в сообщении об ошибке"""
        definition = FSMDefinition(
            entity_id="light.kitchen_special_test",
            states=("ON", "OFF"),
            initial="INVALID",
            transitions=()
        )
        
        with pytest.raises(FSMValidationError) as exc_info:
            validate_definition(definition)
        
        assert "light.kitchen_special_test" in str(exc_info.value)

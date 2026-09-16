"""
Tests for Registry - Тесты реестра для регистрации guard и action функций

Проверка спецификации реестра:
1. Регистрация guard функций
2. Регистрация action функций
3. Проверка наличия зарегистрированных функций
4. Получение зарегистрированных функций
5. Список всех зарегистрированных функций
6. Очистка реестра
"""

import pytest
from src.core.registry import Registry


class TestRegistryGuards:
    """Тесты регистрации и работы с guard функциями"""

    @pytest.fixture
    def registry(self):
        return Registry()

    def test_register_guard(self, registry):
        """Спецификация: Можно зарегистрировать guard функцию по имени"""
        def mock_guard(context) -> bool:
            return True

        registry.register_guard("test_guard", mock_guard)
        assert registry.has_guard("test_guard") is True

    def test_register_guard_overwrite(self, registry):
        """Спецификация: Повторная регистрация guard перезаписывает предыдущую"""
        def guard_v1(context) -> bool:
            return False

        def guard_v2(context) -> bool:
            return True

        registry.register_guard("my_guard", guard_v1)
        registry.register_guard("my_guard", guard_v2)

        guard = registry.get_guard("my_guard")
        assert guard is guard_v2

    def test_has_guard_not_registered(self, registry):
        """Спецификация: has_guard возвращает False для незарегистрированного guard"""
        assert registry.has_guard("nonexistent") is False

    def test_get_guard_returns_function(self, registry):
        """Спецификация: get_guard возвращает зарегистрированную функцию"""
        def mock_guard(context) -> bool:
            return True

        registry.register_guard("test_guard", mock_guard)
        guard = registry.get_guard("test_guard")
        assert guard is mock_guard

    def test_get_guard_not_registered_returns_none(self, registry):
        """Спецификация: get_guard возвращает None для незарегистрированного guard"""
        guard = registry.get_guard("nonexistent")
        assert guard is None

    def test_guard_can_be_called(self, registry):
        """Спецификация: Зарегистрированный guard можно вызвать"""
        call_args = []

        def mock_guard(context) -> bool:
            call_args.append(context)
            return context.get("value", False)

        registry.register_guard("test_guard", mock_guard)
        guard = registry.get_guard("test_guard")

        result = guard({"value": True})
        assert result is True
        assert call_args == [{"value": True}]

    def test_list_guards_empty(self, registry):
        """Спецификация: list_guards возвращает пустой список для пустого реестра"""
        guards = registry.list_guards()
        assert guards == []

    def test_list_guards_multiple(self, registry):
        """Спецификация: list_guards возвращает все зарегистрированные guard имена"""
        def dummy_guard(context) -> bool:
            return True

        registry.register_guard("guard_a", dummy_guard)
        registry.register_guard("guard_b", dummy_guard)
        registry.register_guard("guard_c", dummy_guard)

        guards = registry.list_guards()
        assert len(guards) == 3
        assert set(guards) == {"guard_a", "guard_b", "guard_c"}


class TestRegistryActions:
    """Тесты регистрации и работы с action функциями"""

    @pytest.fixture
    def registry(self):
        return Registry()

    def test_register_action(self, registry):
        """Спецификация: Можно зарегистрировать action функцию по имени"""
        async def mock_action(context):
            pass

        registry.register_action("test_action", mock_action)
        assert registry.has_action("test_action") is True

    def test_register_action_overwrite(self, registry):
        """Спецификация: Повторная регистрация action перезаписывает предыдущую"""
        async def action_v1(context):
            pass

        async def action_v2(context):
            pass

        registry.register_action("my_action", action_v1)
        registry.register_action("my_action", action_v2)

        action = registry.get_action("my_action")
        assert action is action_v2

    def test_has_action_not_registered(self, registry):
        """Спецификация: has_action возвращает False для незарегистрированного action"""
        assert registry.has_action("nonexistent") is False

    def test_get_action_returns_function(self, registry):
        """Спецификация: get_action возвращает зарегистрированную функцию"""
        async def mock_action(context):
            return "result"

        registry.register_action("test_action", mock_action)
        action = registry.get_action("test_action")
        assert action is mock_action

    def test_get_action_not_registered_returns_none(self, registry):
        """Спецификация: get_action возвращает None для незарегистрированного action"""
        action = registry.get_action("nonexistent")
        assert action is None

    @pytest.mark.asyncio
    async def test_action_can_be_called(self, registry):
        """Спецификация: Зарегистрированный action можно вызвать (async)"""
        call_args = []

        async def mock_action(context):
            call_args.append(context)
            return "action_result"

        registry.register_action("test_action", mock_action)
        action = registry.get_action("test_action")

        result = await action({"key": "value"})
        assert result == "action_result"
        assert call_args == [{"key": "value"}]

    def test_action_sync_function(self, registry):
        """Спецификация: Можно зарегистрировать синхронную action функцию"""
        call_args = []

        def sync_action(context):
            call_args.append(context)
            return "sync_result"

        registry.register_action("sync_action", sync_action)
        action = registry.get_action("sync_action")

        result = action({"data": 123})
        assert result == "sync_result"
        assert call_args == [{"data": 123}]

    def test_list_actions_empty(self, registry):
        """Спецификация: list_actions возвращает пустой список для пустого реестра"""
        actions = registry.list_actions()
        assert actions == []

    def test_list_actions_multiple(self, registry):
        """Спецификация: list_actions возвращает все зарегистрированные action имена"""
        async def dummy_action(context):
            pass

        registry.register_action("action_x", dummy_action)
        registry.register_action("action_y", dummy_action)
        registry.register_action("action_z", dummy_action)

        actions = registry.list_actions()
        assert len(actions) == 3
        assert set(actions) == {"action_x", "action_y", "action_z"}


class TestRegistryClear:
    """Тесты очистки реестра"""

    @pytest.fixture
    def registry(self):
        return Registry()

    def test_clear_removes_all_guards(self, registry):
        """Спецификация: clear удаляет все зарегистрированные guard функции"""
        def dummy_guard(context) -> bool:
            return True

        registry.register_guard("guard_1", dummy_guard)
        registry.register_guard("guard_2", dummy_guard)

        registry.clear()

        assert registry.has_guard("guard_1") is False
        assert registry.has_guard("guard_2") is False
        assert registry.list_guards() == []

    def test_clear_removes_all_actions(self, registry):
        """Спецификация: clear удаляет все зарегистрированные action функции"""
        async def dummy_action(context):
            pass

        registry.register_action("action_1", dummy_action)
        registry.register_action("action_2", dummy_action)

        registry.clear()

        assert registry.has_action("action_1") is False
        assert registry.has_action("action_2") is False
        assert registry.list_actions() == []

    def test_clear_both_guards_and_actions(self, registry):
        """Спецификация: clear удаляет и guard и action функции"""
        def dummy_guard(context) -> bool:
            return True

        async def dummy_action(context):
            pass

        registry.register_guard("my_guard", dummy_guard)
        registry.register_action("my_action", dummy_action)

        registry.clear()

        assert registry.list_guards() == []
        assert registry.list_actions() == []

    def test_clear_multiple_times_safe(self, registry):
        """Спецификация: Многократный вызов clear безопасен"""
        registry.clear()
        registry.clear()
        registry.clear()
        # Не должно вызывать ошибок
        assert registry.list_guards() == []
        assert registry.list_actions() == []


class TestRegistryIndependence:
    """Тесты независимости guard и action реестров"""

    @pytest.fixture
    def registry(self):
        return Registry()

    def test_guards_and_actions_independent(self, registry):
        """Спецификация: Guard и action реестры независимы"""
        def dummy_guard(context) -> bool:
            return True

        async def dummy_action(context):
            pass

        registry.register_guard("same_name", dummy_guard)
        registry.register_action("same_name", dummy_action)

        # Оба должны быть доступны по одному имени в своих реестрах
        assert registry.has_guard("same_name") is True
        assert registry.has_action("same_name") is True

        guard = registry.get_guard("same_name")
        action = registry.get_action("same_name")

        assert guard is dummy_guard
        assert action is dummy_action

    def test_clear_guards_does_not_affect_actions(self, registry):
        """Спецификация: Очистка guard реестра не влияет на action реестр"""
        def dummy_guard(context) -> bool:
            return True

        async def dummy_action(context):
            pass

        registry.register_guard("my_guard", dummy_guard)
        registry.register_action("my_action", dummy_action)

        # Очищаем только guards через register_guard с тем же именем
        registry._guards.clear()

        assert registry.has_guard("my_guard") is False
        assert registry.has_action("my_action") is True

    def test_separate_internal_storage(self, registry):
        """Спецификация: Guards и actions используют разные внутренние хранилища"""
        assert hasattr(registry, '_guards')
        assert hasattr(registry, '_actions')
        assert registry._guards is not registry._actions


class TestRegistryEdgeCases:
    """Тесты граничных случаев и специальных ситуаций"""

    @pytest.fixture
    def registry(self):
        return Registry()

    def test_register_guard_with_empty_name(self, registry):
        """Спецификация: Можно зарегистрировать guard с пустым именем"""
        def dummy_guard(context) -> bool:
            return True

        registry.register_guard("", dummy_guard)
        assert registry.has_guard("") is True

    def test_register_action_with_empty_name(self, registry):
        """Спецификация: Можно зарегистрировать action с пустым именем"""
        async def dummy_action(context):
            pass

        registry.register_action("", dummy_action)
        assert registry.has_action("") is True

    def test_register_guard_with_special_characters(self, registry):
        """Спецификация: Имена могут содержать специальные символы"""
        def dummy_guard(context) -> bool:
            return True

        special_names = ["guard-with-dash", "guard.with.dots", "guard_with_underscore"]
        for name in special_names:
            registry.register_guard(name, dummy_guard)
            assert registry.has_guard(name) is True

    def test_register_lambda_guard(self, registry):
        """Спецификация: Можно зарегистрировать lambda функцию как guard"""
        registry.register_guard("lambda_guard", lambda ctx: ctx.get("val", False))
        guard = registry.get_guard("lambda_guard")
        assert guard({"val": True}) is True
        assert guard({"val": False}) is False

    def test_register_lambda_action(self, registry):
        """Спецификация: Можно зарегистрировать lambda функцию как action"""
        registry.register_action("lambda_action", lambda ctx: ctx.get("result"))
        action = registry.get_action("lambda_action")
        assert action({"result": 42}) == 42

    def test_register_callable_object_as_guard(self, registry):
        """Спецификация: Можно зарегистрировать callable объект как guard"""
        class CallableGuard:
            def __call__(self, context):
                return context.get("active", False)

        registry.register_guard("callable_guard", CallableGuard())
        guard = registry.get_guard("callable_guard")
        assert guard({"active": True}) is True

    def test_register_callable_object_as_action(self, registry):
        """Спецификация: Можно зарегистрировать callable объект как action"""
        class CallableAction:
            def __call__(self, context):
                return context.get("data")

        registry.register_action("callable_action", CallableAction())
        action = registry.get_action("callable_action")
        assert action({"data": "test"}) == "test"

    def test_get_guard_after_clear(self, registry):
        """Спецификация: get_guard после clear возвращает None"""
        def dummy_guard(context) -> bool:
            return True

        registry.register_guard("temp_guard", dummy_guard)
        registry.clear()

        assert registry.get_guard("temp_guard") is None

    def test_get_action_after_clear(self, registry):
        """Спецификация: get_action после clear возвращает None"""
        async def dummy_action(context):
            pass

        registry.register_action("temp_action", dummy_action)
        registry.clear()

        assert registry.get_action("temp_action") is None

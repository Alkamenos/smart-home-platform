"""
FSM Factory - Фабрика для создания FSM на основе композиции поведений.

Этот модуль создает экземпляры FSM для каждого поведения устройства,
загружая YAML-шаблоны из features/ и применяя параметры из BehaviorConfig.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from core.fsm.engine import FSMDefinition, FSMEngine
from core.fsm.factory_creation import FsmFactoryCreationMixin
from core.fsm.factory_loading import (
    FsmFactoryLoadingMixin,
    _apply_domain_rules_to_behavior as _apply_domain_rules_to_behavior,
    _domain_rules_for_template as _domain_rules_for_template,
    _resolve_features_dir,
)
from core.fsm.factory_models import (
    LoadReport as LoadReport,
    MissingTemplateError as MissingTemplateError,
    SkippedBehavior as SkippedBehavior,
    TemplateLoadError as TemplateLoadError,
)
from core.registry import Registry


class FSMFactory(FsmFactoryLoadingMixin, FsmFactoryCreationMixin):
    """
    Фабрика для создания FSM на основе композиции поведений.

    Для каждого устройства итерация по device.behaviors:
    1. Находит соответствующий YAML-шаблон в features/
    2. Создает отдельный экземпляр FSM для каждого поведения
    3. Применяет параметры из params к шаблону
    4. Регистрирует все FSM в engine с уникальными entity_id

    Usage:
        engine = FSMEngine()
        registry = Registry()
        factory = FSMFactory(engine, registry)

        # Загрузить behaviors из манифеста
        manifest = load_manifest("instances/leonids_house/manifest.yaml")
        factory.create_from_manifest(manifest)
    """

    def __init__(
        self,
        engine: FSMEngine,
        registry: Registry,
        features_dir: str | None = None,
        event_bus: Any | None = None,
    ) -> None:
        """
        Инициализировать фабрику.

        Args:
            engine: Экземпляр FSMEngine для регистрации автоматов.
            registry: Экземпляр Registry для получения guard/action функций.
            features_dir: Путь к папке с YAML шаблонами. Если не указан,
                используется каталог ``features`` рядом с пакетом ``src``.
            event_bus: Опциональный EventBus для подписки на события сенсоров.
        """
        self._engine = engine
        self._registry = registry
        self._features_dir = _resolve_features_dir(features_dir)
        self._template_cache: dict[str, dict[str, Any]] = {}
        # Хранится как Any, а не Any | None: подписка на сенсоры в
        # create_from_manifest уже защищена проверкой `is not None`, но mypy
        # не сужает тип атрибута через границу метода. Аннотация ничего
        # не меняет во время выполнения.
        self._event_bus: Any = event_bus

    def register_in_engine(self, definitions: list[FSMDefinition]) -> None:
        """
        Зарегистрировать определения FSM в двигателе.

        Args:
            definitions: Список определений FSM для регистрации.
        """
        for definition in definitions:
            self._engine.register_definition(definition)

        logger.info(f"Registered {len(definitions)} FSM definitions in engine")

    def create_and_register(
        self, manifest: Any, restore_states: bool = True
    ) -> list[FSMDefinition]:
        """
        Создать FSM из манифеста и сразу зарегистрировать их в двигателе.

        Args:
            manifest: Валидированный объект Manifest.
            restore_states: If True, attempt to restore saved states from persistence.
                           The FSM engine will check for persisted states and use them
                           instead of initial_state if valid saved states exist.

        Returns:
            list[FSMDefinition]: Список всех созданных и зарегистрированных определений.
        """
        definitions = self.create_from_manifest(manifest)

        # Register each definition with state restoration enabled
        for definition in definitions:
            self._engine.register_definition(definition, restore_state=restore_states)

        logger.info(f"Created and registered {len(definitions)} FSM definitions")
        return definitions

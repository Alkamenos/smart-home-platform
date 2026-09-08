"""
Loader - Загрузчик YAML-конфигураций автоматов.

Этот модуль читает YAML файлы из папки features/, валидирует их через Pydantic,
преобразует в объекты FSMDefinition и регистрирует в FSMEngine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from .definitions import YAMLFSMDefinition, YAMLTransition
from .fsm import FSMDefinition, Transition, FSMEngine
from .registry import Registry


class Loader:
    """
    Загрузчик YAML-конфигураций автоматов.
    
    Читает YAML файлы из указанной папки, валидирует их через Pydantic,
    преобразует в объекты FSMDefinition и регистрирует в FSMEngine.
    
    Usage:
        engine = FSMEngine()
        registry = Registry()
        loader = Loader(engine, registry)
        
        # Зарегистрировать guard/action функции
        registry.register_guard("is_night_time", is_night_time_fn)
        registry.register_action("turn_on_light", turn_on_light_fn)
        
        # Загрузить YAML файлы из папки features/
        loader.load_from_directory("features/")
    """

    def __init__(self, engine: FSMEngine, registry: Registry, features_dir: str = "features") -> None:
        """
        Инициализировать загрузчик.
        
        Args:
            engine: Экземпляр FSMEngine для регистрации автоматов.
            registry: Экземпляр Registry для получения guard/action функций.
            features_dir: Путь к папке с YAML файлами.
        """
        self._engine = engine
        self._registry = registry
        self._features_dir = Path(features_dir)

    def _yaml_to_transition(self, yaml_transition: YAMLTransition) -> Transition:
        """
        Преобразовать YAMLTransition в Transition.
        
        Args:
            yaml_transition: Валидированная YAML-модель перехода.
            
        Returns:
            Transition: Объект перехода для FSM.
        """
        return Transition(
            from_state=yaml_transition.from_state,
            to_state=yaml_transition.to_state,
            trigger=yaml_transition.trigger,
            guard=yaml_transition.guard,
            action=yaml_transition.action,
            timeout_sec=yaml_transition.timeout_sec,
        )

    def _yaml_to_fsm_definition(self, yaml_def: YAMLFSMDefinition) -> FSMDefinition:
        """
        Преобразовать YAMLFSMDefinition в FSMDefinition.
        
        Args:
            yaml_def: Валидированная YAML-модель определения FSM.
            
        Returns:
            FSMDefinition: Объект определения FSM для двигателя.
        """
        transitions = tuple(
            self._yaml_to_transition(t) for t in yaml_def.transitions
        )
        
        return FSMDefinition(
            entity_id=yaml_def.entity_id,
            initial_state=yaml_def.initial_state,
            states=tuple(yaml_def.states),
            transitions=transitions,
            debounce_sec=yaml_def.debounce_sec,
        )

    def _validate_guards_and_actions(self, yaml_def: YAMLFSMDefinition) -> list[str]:
        """
        Проверить, что все guard и action функции зарегистрированы в реестре.
        
        Args:
            yaml_def: Валидированная YAML-модель определения FSM.
            
        Returns:
            list[str]: Список предупреждений о незарегистрированных функциях.
        """
        warnings = []
        
        for transition in yaml_def.transitions:
            if transition.guard and not self._registry.has_guard(transition.guard):
                warnings.append(
                    f"Guard '{transition.guard}' not found in registry for entity '{yaml_def.entity_id}'"
                )
            
            if transition.action and not self._registry.has_action(transition.action):
                warnings.append(
                    f"Action '{transition.action}' not found in registry for entity '{yaml_def.entity_id}'"
                )
        
        return warnings

    def load_yaml_file(self, yaml_path: Path) -> list[FSMDefinition]:
        """
        Загрузить и обработать один YAML файл.
        
        Args:
            yaml_path: Путь к YAML файлу.
            
        Returns:
            list[FSMDefinition]: Список загруженных определений FSM.
        """
        definitions = []
        
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to read YAML file {yaml_path}: {e}")
            return definitions
        
        # YAML может содержать один автомат или список автоматов
        if not isinstance(data, list):
            data = [data]
        
        for item in data:
            try:
                # Валидация через Pydantic
                yaml_def = YAMLFSMDefinition.model_validate(item)
                
                # Проверка guard/action функций
                warnings = self._validate_guards_and_actions(yaml_def)
                for warning in warnings:
                    logger.warning(warning)
                
                # Преобразование в FSMDefinition
                fsm_def = self._yaml_to_fsm_definition(yaml_def)
                definitions.append(fsm_def)
                
                logger.info(f"Loaded FSM for entity '{fsm_def.entity_id}' from {yaml_path}")
                
            except Exception as e:
                logger.error(f"Failed to validate/load FSM from {yaml_path}: {e}")
        
        return definitions

    def load_from_directory(self, directory: str | None = None) -> list[FSMDefinition]:
        """
        Загрузить все YAML файлы из указанной директории.
        
        Args:
            directory: Путь к директории (по умолчанию используется features_dir).
            
        Returns:
            list[FSMDefinition]: Список всех загруженных определений FSM.
        """
        dir_path = Path(directory) if directory else self._features_dir
        
        if not dir_path.exists():
            logger.warning(f"Features directory does not exist: {dir_path}")
            return []
        
        all_definitions = []
        yaml_files = list(dir_path.glob("*.yaml")) + list(dir_path.glob("*.yml"))
        
        for yaml_file in yaml_files:
            definitions = self.load_yaml_file(yaml_file)
            all_definitions.extend(definitions)
        
        logger.info(f"Loaded {len(all_definitions)} FSM definitions from {dir_path}")
        return all_definitions

    def register_in_engine(self, definitions: list[FSMDefinition]) -> None:
        """
        Зарегистрировать определения FSM в двигателе.
        
        Args:
            definitions: Список определений FSM для регистрации.
        """
        for definition in definitions:
            self._engine.register_definition(definition)
        
        logger.info(f"Registered {len(definitions)} FSM definitions in engine")

    def load_and_register(self, directory: str | None = None) -> list[FSMDefinition]:
        """
        Загрузить YAML файлы и сразу зарегистрировать их в двигателе.
        
        Также регистрирует все guard/action функции из Registry в FSMEngine.
        
        Args:
            directory: Путь к директории (по умолчанию используется features_dir).
            
        Returns:
            list[FSMDefinition]: Список всех загруженных и зарегистрированных определений.
        """
        # Сначала регистрируем все guard/action функции из Registry в FSMEngine
        for guard_name in self._registry.list_guards():
            guard_fn = self._registry.get_guard(guard_name)
            if guard_fn:
                self._engine.register_guard(guard_name, guard_fn)
        
        for action_name in self._registry.list_actions():
            action_fn = self._registry.get_action(action_name)
            if action_fn:
                self._engine.register_action(action_name, action_fn)
        
        # Затем загружаем и регистрируем FSM определения
        definitions = self.load_from_directory(directory)
        self.register_in_engine(definitions)
        return definitions


# Пример использования
if __name__ == "__main__":
    # Создание двигателя и реестра
    engine = FSMEngine()
    registry = Registry()
    
    # Регистрация guard/action функций
    def is_night_time(ctx: dict[str, Any]) -> bool:
        """Пример guard функции - проверка ночного времени."""
        return ctx.get("hour", 12) >= 22 or ctx.get("hour", 12) < 6
    
    def turn_on_light(ctx: dict[str, Any]) -> None:
        """Пример action функции - включение света."""
        logger.info(f"Turning on light for entity {ctx.get('entity_id')}")
    
    registry.register_guard("is_night_time", is_night_time)
    registry.register_action("turn_on_light", turn_on_light)
    
    # Загрузка из папки features/
    loader = Loader(engine, registry, features_dir="features")
    definitions = loader.load_and_register()
    
    print(f"Loaded {len(definitions)} FSM definitions:")
    for d in definitions:
        print(f"  - {d.entity_id}: {d.initial_state} -> {d.states}")

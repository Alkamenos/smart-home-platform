"""
Migration Tool - утилита для миграции данных из V1/V2 в V3

Поддерживает:
- Экспорт конфигураций из старых версий
- Преобразование форматов FSM
- Импорт в новую структуру
- Валидацию данных
"""
import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    """Отчет о миграции"""
    source_version: str
    target_version: str
    timestamp: str
    total_items: int
    migrated: int
    failed: int
    skipped: int
    errors: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MigrationTool:
    """
    Инструмент для миграции данных между версиями платформы
    """
    
    def __init__(self, workspace_path: str = "/workspace"):
        self.workspace = Path(workspace_path)
        self.v1_path = self.workspace / "v1"
        self.v2_path = self.workspace / "v2"
        self.v3_path = self.workspace / "platform_v3"
        
        self._report: Optional[MigrationReport] = None
    
    async def migrate_from_v2(
        self,
        config_file: str,
        output_dir: Optional[str] = None
    ) -> MigrationReport:
        """
        Миграция конфигурации из V2 в V3
        
        Args:
            config_file: Путь к файлу конфигурации V2
            output_dir: Директория для сохранения результата
            
        Returns:
            MigrationReport: Отчет о миграции
        """
        logger.info(f"Starting migration from V2: {config_file}")
        
        errors = []
        migrated_count = 0
        failed_count = 0
        skipped_count = 0
        
        # Загружаем старую конфигурацию
        try:
            with open(config_file, 'r') as f:
                if config_file.endswith('.yaml') or config_file.endswith('.yml'):
                    v2_config = yaml.safe_load(f)
                else:
                    v2_config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load V2 config: {e}")
            return MigrationReport(
                source_version="2.0",
                target_version="3.0",
                timestamp=datetime.now().isoformat(),
                total_items=0,
                migrated=0,
                failed=1,
                skipped=0,
                errors=[str(e)]
            )
        
        # Преобразуем структуры данных
        v3_config = {
            'version': '3.0',
            'migrated_from': '2.0',
            'migration_date': datetime.now().isoformat(),
            'features': {},
            'adapters': {},
            'global_settings': {}
        }
        
        # Мигрируем features
        if 'automations' in v2_config:
            for auto_id, auto_config in v2_config['automations'].items():
                try:
                    v3_feature = self._convert_v2_automation_to_v3(auto_id, auto_config)
                    v3_config['features'][auto_id] = v3_feature
                    migrated_count += 1
                except Exception as e:
                    logger.warning(f"Failed to migrate {auto_id}: {e}")
                    errors.append(f"Feature {auto_id}: {str(e)}")
                    failed_count += 1
        
        # Мигрируем adapters
        if 'adapters' in v2_config:
            for adapter_name, adapter_config in v2_config['adapters'].items():
                v3_config['adapters'][adapter_name] = self._convert_v2_adapter(adapter_config)
        
        # Мигрируем глобальные настройки
        if 'settings' in v2_config:
            v3_config['global_settings'] = self._convert_v2_settings(v2_config['settings'])
        
        total_items = len(v2_config.get('automations', {}))
        
        # Сохраняем результат
        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            output_file = output_path / "v3_config.yaml"
            with open(output_file, 'w') as f:
                yaml.dump(v3_config, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"Migrated config saved to {output_file}")
        
        self._report = MigrationReport(
            source_version="2.0",
            target_version="3.0",
            timestamp=datetime.now().isoformat(),
            total_items=total_items,
            migrated=migrated_count,
            failed=failed_count,
            skipped=skipped_count,
            errors=errors
        )
        
        return self._report
    
    def _convert_v2_automation_to_v3(
        self,
        automation_id: str,
        v2_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Преобразовать автоматизацию V2 в формат V3"""
        
        # Определяем тип фичи
        feature_type = self._detect_feature_type(v2_config)
        
        # Преобразуем состояния
        states = []
        v2_states = v2_config.get('states', {})
        for state_id, state_config in v2_states.items():
            states.append({
                'id': state_id,
                'name': state_config.get('name', state_id),
                'actions': state_config.get('actions', [])
            })
        
        # Преобразуем переходы
        transitions = []
        v2_transitions = v2_config.get('transitions', [])
        for transition in v2_transitions:
            new_transition = {
                'from': transition.get('from'),
                'to': transition.get('to'),
                'event': transition.get('trigger', transition.get('event')),
                'priority': transition.get('priority', 0)
            }
            
            # Конвертируем guard условия
            if 'condition' in transition:
                new_transition['guard'] = self._convert_v2_condition(transition['condition'])
            
            transitions.append(new_transition)
        
        return {
            'id': automation_id,
            'type': feature_type,
            'name': v2_config.get('name', automation_id),
            'description': v2_config.get('description', ''),
            'initial_state': v2_config.get('initial_state', 'off'),
            'states': states,
            'transitions': transitions,
            'entities': v2_config.get('entities', []),
            'metadata': {
                'migrated_from': 'v2',
                'original_id': automation_id
            }
        }
    
    def _convert_v2_adapter(self, v2_config: Dict[str, Any]) -> Dict[str, Any]:
        """Преобразовать адаптер V2 в формат V3"""
        return {
            'type': v2_config.get('type', 'mock'),
            'enabled': v2_config.get('enabled', True),
            'config': v2_config.get('config', {}),
            'metadata': {'migrated_from': 'v2'}
        }
    
    def _convert_v2_settings(self, v2_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Преобразовать настройки V2 в формат V3"""
        return {
            'logging': v2_settings.get('logging', {'level': 'INFO'}),
            'event_bus': v2_settings.get('event_bus', {'buffer_size': 1000}),
            'fsm': v2_settings.get('fsm', {'history_size': 20}),
            'metadata': {'migrated_from': 'v2'}
        }
    
    def _detect_feature_type(self, config: Dict[str, Any]) -> str:
        """Определить тип фичи по конфигурации"""
        entities = config.get('entities', [])
        
        # Проверяем по entity_id
        for entity in entities:
            if isinstance(entity, str):
                if entity.startswith('light.'):
                    return 'lighting'
                elif entity.startswith('climate.') or entity.startswith('sensor.temperature'):
                    return 'climate'
                elif entity.startswith('fan.') or entity.startswith('sensor.humidity'):
                    return 'ventilation'
                elif entity.startswith('binary_sensor.motion') or entity.startswith('alarm_control_panel'):
                    return 'security'
        
        # Проверяем по названию
        name = config.get('name', '').lower()
        if 'light' in name:
            return 'lighting'
        elif 'temp' in name or 'climate' in name or 'thermo' in name:
            return 'climate'
        elif 'vent' in name or 'fan' in name:
            return 'ventilation'
        elif 'security' in name or 'alarm' in name:
            return 'security'
        
        return 'custom'
    
    def _convert_v2_condition(self, condition: Any) -> Dict[str, Any]:
        """Преобразовать условие V2 в guard формат V3"""
        if isinstance(condition, str):
            # Старый формат: строка с выражением
            return {
                'type': 'expression',
                'value': condition
            }
        elif isinstance(condition, dict):
            # Новый формат: dict с type и value
            return condition
        else:
            return {'type': 'always', 'value': True}
    
    def get_report(self) -> Optional[MigrationReport]:
        """Получить последний отчет о миграции"""
        return self._report
    
    def validate_v3_config(self, config: Dict[str, Any]) -> List[str]:
        """
        Валидировать конфигурацию V3
        
        Args:
            config: Конфигурация для проверки
            
        Returns:
            List[str]: Список ошибок валидации
        """
        errors = []
        
        # Проверка версии
        if config.get('version') != '3.0':
            errors.append(f"Invalid version: {config.get('version')}, expected 3.0")
        
        # Проверка features
        features = config.get('features', {})
        for feature_id, feature_config in features.items():
            if 'id' not in feature_config:
                errors.append(f"Feature {feature_id}: missing 'id' field")
            if 'type' not in feature_config:
                errors.append(f"Feature {feature_id}: missing 'type' field")
            if 'states' not in feature_config or not feature_config['states']:
                errors.append(f"Feature {feature_id}: no states defined")
            if 'transitions' not in feature_config:
                errors.append(f"Feature {feature_id}: no transitions defined")
            if 'initial_state' not in feature_config:
                errors.append(f"Feature {feature_id}: no initial_state defined")
        
        return errors
    
    async def export_current_config(
        self,
        registry,
        output_file: str
    ) -> bool:
        """
        Экспортировать текущую конфигурацию из registry
        
        Args:
            registry: Registry с загруженными автоматами
            output_file: Путь для сохранения
            
        Returns:
            bool: True если успешно
        """
        try:
            config = {
                'version': '3.0',
                'exported_at': datetime.now().isoformat(),
                'features': {},
                'adapters': {}
            }
            
            # Экспортируем FSM из registry
            for fsm_id, fsm in registry._automata.items():
                config['features'][fsm_id] = {
                    'id': fsm_id,
                    'type': getattr(fsm, 'feature_type', 'unknown'),
                    'name': getattr(fsm, 'name', fsm_id),
                    'initial_state': fsm.current_state.id if hasattr(fsm, 'current_state') else 'unknown',
                    'states': [
                        {'id': state.id, 'name': state.name}
                        for state in fsm.states.values()
                    ] if hasattr(fsm, 'states') else [],
                    'metadata': {'source': 'runtime'}
                }
            
            # Сохраняем
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"Config exported to {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export config: {e}")
            return False

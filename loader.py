#!/usr/bin/env python3
"""
Loader для загрузки платформы V3 в Home Assistant PyScript

Этот скрипт:
1. Копирует файлы ядра в директорию pyscript
2. Создаёт конфигурационный файл pyscript.yaml
3. Опционально перезагружает PyScript через HA API
4. Поддерживает hot-reload при изменениях файлов
"""

import os
import sys
import shutil
import hashlib
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Set
from datetime import datetime

try:
    import watchfiles
    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False


class PyscriptLoader:
    """Загрузчик платформы V3 в Home Assistant PyScript"""
    
    def __init__(self, ha_config_dir: Optional[str] = None, manifest_path: Optional[str] = None):
        """
        Инициализация загрузчика
        
        Args:
            ha_config_dir: Путь к директории конфигурации HA.
                          Если None, используется стандартный путь ~/.homeassistant
            manifest_path: Путь к манифесту. Если None, используется путь по умолчанию
        """
        self.source_dir = Path(__file__).parent
        self.ha_config_dir = Path(ha_config_dir) if ha_config_dir else Path.home() / ".homeassistant"
        self.pyscript_dir = self.ha_config_dir / "pyscript"
        
        # ← НОВОЕ: Манифест обязателен
        self._manifest_path = manifest_path or "instances/leonids_house/manifest.yaml"
        
        if not Path(self._manifest_path).exists():
            raise FileNotFoundError(f"Манифест не найден: {self._manifest_path}")
        
        # Загружаем манифест для валидации
        import yaml
        with open(self._manifest_path) as f:
            self._manifest = yaml.safe_load(f)
        
        # Валидируем манифест при инициализации
        from core.manifest_validator import ManifestValidator
        validator = ManifestValidator()
        errors = validator.validate(self._manifest)
        if errors:
            raise ValueError(f"Манифест невалиден: {[str(e) for e in errors]}")
        
        # Для hot-reload
        self._file_hashes: Dict[str, str] = {}
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_watching = False
        self._on_reload_callback = None
        
    def _compute_file_hash(self, file_path: Path) -> str:
        """Вычислить хэш файла для отслеживания изменений"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def _update_file_hashes(self, directory: Path) -> None:
        """Обновить хэши всех файлов в директории"""
        for py_file in directory.rglob("*.py"):
            rel_path = str(py_file.relative_to(self.source_dir))
            self._file_hashes[rel_path] = self._compute_file_hash(py_file)
    
    def _check_file_changes(self) -> Set[str]:
        """Проверить изменения файлов, вернуть список изменённых"""
        changed = set()
        for rel_path, old_hash in list(self._file_hashes.items()):
            file_path = self.source_dir / rel_path
            if file_path.exists():
                new_hash = self._compute_file_hash(file_path)
                if new_hash != old_hash:
                    changed.add(rel_path)
                    self._file_hashes[rel_path] = new_hash
        return changed
    
    def _watch_files_loop(self) -> None:
        """Цикл отслеживания изменений файлов"""
        print("[Hot-Reload] Started watching for file changes...")
        while not self._stop_watching:
            time.sleep(2)  # Проверяем каждые 2 секунды
            changed = self._check_file_changes()
            if changed and self._on_reload_callback:
                print(f"\n[Hot-Reload] Detected changes in {len(changed)} file(s):")
                for f in changed:
                    print(f"  - {f}")
                self._on_reload_callback(changed)
    
    def start_hot_reload(self, callback=None) -> None:
        """
        Запустить отслеживание изменений файлов
        
        Args:
            callback: Функция обратного вызова при изменениях (получает set изменённых файлов)
        """
        if self._watch_thread is not None:
            print("[Hot-Reload] Already running")
            return
        
        # Инициализируем хэши
        self._update_file_hashes(self.source_dir / "core")
        self._update_file_hashes(self.source_dir / "features")
        self._update_file_hashes(self.source_dir / "adapters")
        
        self._on_reload_callback = callback
        self._stop_watching = False
        self._watch_thread = threading.Thread(target=self._watch_files_loop, daemon=True)
        self._watch_thread.start()
        print("[Hot-Reload] File watcher started")
    
    def stop_hot_reload(self) -> None:
        """Остановить отслеживание изменений"""
        self._stop_watching = True
        if self._watch_thread:
            self._watch_thread.join(timeout=5)
            self._watch_thread = None
        print("[Hot-Reload] File watcher stopped")
        
    def copy_core_files(self) -> list[Path]:
        """Копировать файлы ядра в pyscript"""
        copied = []
        
        # Создаём директорию core в pyscript
        target_core_dir = self.pyscript_dir / "platform_v3" / "core"
        target_core_dir.mkdir(parents=True, exist_ok=True)
        
        # Копируем файлы core
        source_core_dir = self.source_dir / "core"
        for py_file in source_core_dir.glob("*.py"):
            target_file = target_core_dir / py_file.name
            shutil.copy2(py_file, target_file)
            copied.append(target_file)
            print(f"✓ Скопировано: {py_file.name} -> {target_core_dir}")
        
        return copied
    
    def copy_features_files(self) -> list[Path]:
        """Копировать файлы фич в pyscript"""
        copied = []
        
        # Создаём директорию features в pyscript
        target_features_dir = self.pyscript_dir / "platform_v3" / "features"
        target_features_dir.mkdir(parents=True, exist_ok=True)
        
        # Копируем файлы features
        source_features_dir = self.source_dir / "features"
        for py_file in source_features_dir.glob("*.py"):
            if py_file.name != "__init__.py":  # Пропускаем __init__.py
                target_file = target_features_dir / py_file.name
                shutil.copy2(py_file, target_file)
                copied.append(target_file)
                print(f"✓ Скопировано: {py_file.name} -> {target_features_dir}")
        
        return copied
    
    def copy_adapters_files(self) -> list[Path]:
        """Копировать файлы адаптеров в pyscript"""
        copied = []
        
        # Создаём директорию adapters в pyscript
        target_adapters_dir = self.pyscript_dir / "platform_v3" / "adapters"
        target_adapters_dir.mkdir(parents=True, exist_ok=True)
        
        # Копируем файлы adapters
        source_adapters_dir = self.source_dir / "adapters"
        for py_file in source_adapters_dir.glob("*.py"):
            if py_file.name != "__init__.py":  # Пропускаем __init__.py
                target_file = target_adapters_dir / py_file.name
                shutil.copy2(py_file, target_file)
                copied.append(target_file)
                print(f"✓ Скопировано: {py_file.name} -> {target_adapters_dir}")
        
        return copied
    
    def create_pyscript_yaml(self) -> Path:
        """Создать файл конфигурации pyscript.yaml"""
        pyscript_yaml = self.pyscript_dir / "pyscript.yaml"
        
        config_content = """# Platform V3 Configuration
# Auto-generated by loader.py

# Allow imports from platform_v3 directory
allow_all_imports: true

# Enable state persistence (optional)
# state_change_listener: true

# Logging settings
logging:
  level: info
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s
"""
        
        with open(pyscript_yaml, 'w') as f:
            f.write(config_content)
        
        print(f"✓ Создан конфиг: {pyscript_yaml}")
        return pyscript_yaml
    
    def create_init_script(self) -> Path:
        """Создать главный скрипт инициализации"""
        init_script = self.pyscript_dir / "platform_v3_init.py"
        
        init_content = '''"""
Platform V3 - Инициализация

Этот скрипт запускается при старте PyScript и инициализирует платформу.
"""

import sys
from pathlib import Path

# Добавляем platform_v3 в path
platform_dir = Path(__file__).parent / "platform_v3"
sys.path.insert(0, str(platform_dir))

# Импортируем компоненты
from core.fsm import FSMEngine
from core.event_bus import EventBus
from core.logger import Logger
from core.registry import Registry
from core.fsm_persistence import FSMPersistence
from adapters.ha_adapter import HAAdapter

# Создаём глобальные экземпляры
event_bus = EventBus()
logger = Logger(component="platform_v3")
fsm_engine = FSMEngine(event_bus, logger)
registry = Registry()
ha_adapter = HAAdapter()

# Регистрируем адаптер в FSM
fsm_engine.set_adapter(ha_adapter)

# Инициализируем персистентность состояний
persistence = FSMPersistence(event_bus, fsm_engine, ha_adapter, logger)

# Импортируем и регистрируем автоматы
from features.lighting import create_lighting_automations
from features.climate import create_climate_automations

# Конфигурация комнат и зон (можно вынести в variables.yaml)
ROOMS = ["living_room", "bedroom", "kitchen", "bathroom"]
ZONES = ["zone_1", "zone_2"]

# Создаём и регистрируем автоматы
lighting_defs = create_lighting_automations(ROOMS)
climate_defs = create_climate_automations(ZONES)

all_definitions = []
for definition in lighting_defs + climate_defs:
    fsm_engine.register(definition)
    all_definitions.append(definition)
    logger.info(f"Зарегистрирован автомат: {definition.entity_id}")
    
    # Включаем персистентность для каждого автомата
    persistence.enable_for_entity(definition.entity_id)

logger.info(f"Platform V3 запущена. Всего автоматов: {len(all_definitions)}")
logger.info(f"Персистентность включена для {len(all_definitions)} автоматов")


# Обработчики событий от HA
@state_changed("*")
def handle_state_change(entity_id, old_state, new_state):
    """Обработка изменений состояний устройств"""
    # Публикуем событие в шину
    event_bus.publish("device.state_changed", {
        "entity_id": entity_id,
        "old_state": old_state,
        "new_state": new_state
    })


# Сервисы для отладки
@service
def fsm_debug(entity_id: str):
    """Показать состояние автомата"""
    state = fsm_engine.get_state(entity_id)
    if state:
        logger.info(f"Состояние {entity_id}: {state.current}")
        return {"state": state.current, "history": state.history}
    return {"error": "Автомат не найден"}


@service
def fsm_reset(entity_id: str):
    """Сбросить автомат в начальное состояние"""
    result = fsm_engine.reset(entity_id)
    logger.info(f"Сброшен автомат {entity_id}: {result}")
    return {"success": result}


@service
def fsm_trigger(entity_id: str, trigger: str, **context):
    """Вызвать триггер вручную"""
    result = fsm_engine.trigger(entity_id, trigger, context)
    logger.info(f"Триггер {trigger} для {entity_id}: {result}")
    return {"success": result}


@service
def fsm_persist_list():
    """Показать список автоматов с включенной персистентностью"""
    return {"enabled_entities": list(persistence._enabled_entities.keys())}
'''
        
        with open(init_script, 'w') as f:
            f.write(init_content)
        
        print(f"✓ Создан скрипт инициализации: {init_script}")
        return init_script
    
    def reload_pyscript(self, ha_url: str, ha_token: str) -> bool:
        """Перезагрузить PyScript через HA API"""
        import requests
        
        url = f"{ha_url}/api/services/pyscript/reload"
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(url, headers=headers, timeout=10)
            if response.status_code == 200:
                print("✓ PyScript перезапущен")
                return True
            else:
                print(f"✗ Ошибка перезагрузки: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ Ошибка подключения к HA: {e}")
            return False
    
    def deploy(self, ha_url: Optional[str] = None, ha_token: Optional[str] = None) -> bool:
        """
        Полный процесс деплоя
        
        Args:
            ha_url: URL Home Assistant (опционально, для перезагрузки)
            ha_token: Токен доступа (опционально, для перезагрузки)
        
        Returns:
            bool: Успешность деплоя
        """
        print("\n=== Деплой Platform V3 в Home Assistant ===\n")
        
        # Копируем файлы
        print("1. Копирование файлов ядра...")
        self.copy_core_files()
        
        print("\n2. Копирование файлов фич...")
        self.copy_features_files()
        
        print("\n3. Копирование файлов адаптеров...")
        self.copy_adapters_files()
        
        print("\n4. Создание конфигурации...")
        self.create_pyscript_yaml()
        
        print("\n5. Создание скрипта инициализации...")
        self.create_init_script()
        
        # Перезагружаем PyScript если предоставлены credentials
        if ha_url and ha_token:
            print("\n6. Перезагрузка PyScript...")
            self.reload_pyscript(ha_url, ha_token)
        else:
            print("\n⚠ Перезагрузка PyScript пропущена (нет credentials)")
            print("  Перезапустите PyScript вручную через Developer Tools > Services > pyscript.reload")
        
        print("\n=== Деплой завершён ===\n")
        return True


def main():
    """Точка входа для CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Loader для Platform V3")
    parser.add_argument("--ha-config", help="Путь к директории конфигурации HA")
    parser.add_argument("--ha-url", help="URL Home Assistant (для перезагрузки)")
    parser.add_argument("--token", help="Long-lived token (для перезагрузки)")
    parser.add_argument("--dry-run", action="store_true", help="Тестовый режим без копирования")
    parser.add_argument("--watch", action="store_true", help="Включить hot-reload мониторинг")
    parser.add_argument("--reload-cmd", help="Команда для перезагрузки (по умолчанию: pyscript.reload)")
    
    args = parser.parse_args()
    
    if args.dry_run:
        print("=== Dry-run режим ===")
        print(f"Директория HA: {args.ha_config or '~/.homeassistant'}")
        print(f"Директория pyscript: {Path(args.ha_config).expanduser() / 'pyscript' if args.ha_config else '~/.homeassistant/pyscript'}")
        print("\nФайлы для копирования:")
        print("  core/*.py -> pyscript/platform_v3/core/")
        print("  features/*.py -> pyscript/platform_v3/features/")
        print("  adapters/*.py -> pyscript/platform_v3/adapters/")
        print("\nФайлы для создания:")
        print("  pyscript/platform_v3/pyscript.yaml")
        print("  pyscript/platform_v3_init.py")
        
        if args.watch:
            print("\nHot-reload будет включён после деплоя")
        return
    
    loader = PyscriptLoader(ha_config_dir=args.ha_config)
    success = loader.deploy(ha_url=args.ha_url, ha_token=args.token)
    
    # Запускаем hot-reload если запрошено
    if args.watch and success:
        def on_reload(changed_files):
            """Callback при изменении файлов"""
            print("\n[Hot-Reload] Перезагрузка изменённых файлов...")
            loader.copy_core_files()
            loader.copy_features_files()
            loader.copy_adapters_files()
            
            if args.ha_url and args.token:
                loader.reload_pyscript(args.ha_url, args.token)
            else:
                print("⚠ Для авто-перезагрузки укажите --ha-url и --token")
        
        loader.start_hot_reload(callback=on_reload)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Hot-Reload] Остановка по запросу пользователя")
            loader.stop_hot_reload()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

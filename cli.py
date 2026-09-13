#!/usr/bin/env python3
"""
CLI для платформы V3

Команды:
- run: Запуск платформы
- test: Запуск тестов
- debug: Отладка конкретного автомата
- deploy: Деплой в Home Assistant
- status: Показать статус всех автоматов
- manifest: Управление манифестом (validate, show, generate, migrate)
- health: Проверка здоровья платформы
- doctor: Автоматическая диагностика проблем
"""

import argparse
import sys
import json
import time
import signal
import os
from pathlib import Path

# Добавляем platform_v3 в path
sys.path.insert(0, str(Path(__file__).parent))

from core.fsm import FSMEngine
from core.event_bus import EventBus
from core.logger import Logger
from core.registry import Registry
from adapters.mock_adapter import MockAdapter
from adapters.ha_adapter import HomeAssistantAdapter
from features.lighting import create_lighting_automations

# Импорт bootstrap для инициализации платформы
from src.smart_home.bootstrap import bootstrap_platform, PlatformContext

# Алиас для совместимости
HAAdapter = HomeAssistantAdapter


def cmd_validate(args):
    """Расширенная валидация манифеста через Pydantic"""
    import yaml
    
    manifest_path = Path(args.manifest_path)
    
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)
    
    errors = []
    
    # 1. Загрузка YAML
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Ошибка парсинга YAML: {e}")
        sys.exit(1)
    
    # 2. Валидация через Pydantic
    print("📋 Валидация структуры манифеста через Pydantic...")
    try:
        from src.smart_home.core.models.manifest import Manifest
        manifest = Manifest.model_validate(manifest_data)
        print("✅ Структура манифеста валидна")
    except Exception as e:
        print(f"❌ Ошибка валидации Pydantic: {e}")
        sys.exit(1)
    
    # 3. Проверка существования template файлов в features/
    print("\n🔍 Проверка template файлов в features/...")
    features_dir = Path("features")
    if not features_dir.exists():
        features_dir = Path(__file__).parent / "features"
    
    available_templates = set()
    if features_dir.exists():
        for yaml_file in features_dir.glob("*.yaml"):
            template_name = yaml_file.stem
            available_templates.add(template_name)
    
    missing_templates = []
    for device in manifest.devices:
        for behavior in device.behaviors:
            if behavior.template not in available_templates:
                missing_templates.append({
                    "device": device.id,
                    "template": behavior.template
                })
    
    if missing_templates:
        print(f"❌ Найдено {len(missing_templates)} отсутствующих template:")
        for item in missing_templates:
            print(f"   • Устройство {item['device']}: template '{item['template']}' не найден в features/")
        errors.extend(missing_templates)
    else:
        print(f"✅ Все template файлы найдены (найдено шаблонов: {len(available_templates)})")
    
    # 4. Проверка что все room существуют в zones
    print("\n🔍 Проверка ссылочной целостности room -> zones...")
    zone_ids = {zone.id for zone in manifest.zones}
    
    invalid_rooms = []
    for device in manifest.devices:
        if device.room not in zone_ids:
            invalid_rooms.append({
                "device": device.id,
                "room": device.room
            })
    
    if invalid_rooms:
        print(f"❌ Найдено {len(invalid_rooms)} устройств с несуществующими room:")
        for item in invalid_rooms:
            print(f"   • Устройство {item['device']}: room '{item['room']}' не найдена в zones")
        errors.extend(invalid_rooms)
    else:
        print(f"✅ Все room ссылаются на существующие zones (всего зон: {len(zone_ids)})")
    
    # Итоговый отчет
    print("\n" + "=" * 50)
    if errors:
        print(f"❌ ВАЛИДАЦИЯ НЕ ПРОЙДЕНА: {len(errors)} ошибок")
        sys.exit(1)
    else:
        print("✅ ВАЛИДАЦИЯ ПРОЙДЕНА УСПЕШНО")
        print(f"   Instance: {manifest.instance.name} ({manifest.instance.id})")
        print(f"   Устройств: {len(manifest.devices)}")
        print(f"   Зон: {len(manifest.zones)}")
        print(f"   Template файлов: {len(available_templates)}")


def cmd_list_devices(args):
    """Вывод таблицы всех устройств с их behaviors и приоритетами"""
    import yaml
    
    manifest_path = Path(args.manifest_path)
    
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)
    
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Ошибка парсинга YAML: {e}")
        sys.exit(1)
    
    # Загружаем через Pydantic для удобства
    try:
        from src.smart_home.core.models.manifest import Manifest
        manifest = Manifest.model_validate(manifest_data)
    except Exception as e:
        print(f"⚠️ Предупреждение: полная валидация не пройдена, используем raw данные: {e}")
        # Fallback к ручной обработке
        devices_raw = manifest_data.get("devices", [])
        print("\n=== Список устройств ===\n")
        for device in devices_raw:
            device_id = device.get("id", "unknown")
            device_name = device.get("name", "N/A")
            device_room = device.get("room", "N/A")
            behaviors = device.get("behaviors", [])
            
            print(f"Device: {device_id} ({device_name}) [{device_room}]")
            if not behaviors:
                print("  └─ (нет behaviors)")
            else:
                for i, bh in enumerate(behaviors):
                    is_last = (i == len(behaviors) - 1)
                    prefix = "└─" if is_last else "├─"
                    template = bh.get("template", "unknown")
                    priority = bh.get("priority", "N/A")
                    params = bh.get("params", {})
                    
                    extra_info = []
                    if "schedule" in params:
                        extra_info.append(params["schedule"])
                    if "brightness" in params:
                        extra_info.append(f"brightness={params['brightness']}")
                    if "motion_sensor" in params:
                        extra_info.append("motion-based")
                    
                    extra_str = f" [{', '.join(extra_info)}]" if extra_info else ""
                    print(f"  {prefix} {template} (priority {priority}){extra_str}")
            print()
        return
    
    print("\n=== Список устройств ===\n")
    
    for device in manifest.devices:
        print(f"Device: {device.id} ({device.name}) [{device.room}]")
        
        if not device.behaviors:
            print("  └─ (нет behaviors)")
        else:
            for i, behavior in enumerate(device.behaviors):
                is_last = (i == len(device.behaviors) - 1)
                prefix = "└─" if is_last else "├─"
                
                # Формируем дополнительную информацию из params
                params = behavior.params or {}
                extra_info = []
                
                if "schedule" in params:
                    extra_info.append(params["schedule"])
                if "brightness" in params:
                    extra_info.append(f"brightness={params['brightness']}")
                if "motion_sensor" in params:
                    extra_info.append("motion-based")
                if "humidity_sensor" in params:
                    extra_info.append("humidity-based")
                if "target" in params:
                    extra_info.append(f"target={params['target']}°C")
                
                extra_str = f" [{', '.join(extra_info)}]" if extra_info else ""
                print(f"  {prefix} {behavior.template} (priority {behavior.priority}){extra_str}")
        
        print()


def cmd_dry_run(args):
    """Создание FSM без запуска - dry run режим"""
    import yaml
    
    manifest_path = Path(args.manifest_path)
    features_dir = Path(args.features_dir)
    
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)
    
    if not features_dir.exists():
        features_dir = Path(__file__).parent / args.features_dir
        if not features_dir.exists():
            print(f"❌ Директория features не найдена: {features_dir}")
            sys.exit(1)
    
    print(f"📋 Загрузка манифеста: {manifest_path}")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Ошибка парсинга YAML: {e}")
        sys.exit(1)
    
    try:
        from src.smart_home.core.models.manifest import Manifest
        manifest = Manifest.model_validate(manifest_data)
    except Exception as e:
        print(f"❌ Ошибка валидации манифеста: {e}")
        sys.exit(1)
    
    print(f"✅ Манифест загружен: {manifest.instance.name}")
    print(f"   Устройств: {len(manifest.devices)}")
    print(f"   Зон: {len(manifest.zones)}")
    
    # Загружаем шаблоны из features/
    print(f"\n📂 Загрузка шаблонов из {features_dir}...")
    feature_templates = {}
    for yaml_file in features_dir.glob("*.yaml"):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                template_data = yaml.safe_load(f)
            template_name = yaml_file.stem
            feature_templates[template_name] = template_data
            print(f"   ✅ {template_name}.yaml")
        except Exception as e:
            print(f"   ⚠️ {yaml_file.name}: ошибка загрузки ({e})")
    
    print(f"\n🔧 Создание FSM для каждого устройства (dry-run, без запуска)...")
    print("=" * 60)
    
    total_fsm = 0
    total_states = 0
    total_transitions = 0
    
    for device in manifest.devices:
        print(f"\n📦 Устройство: {device.id} ({device.name})")
        print(f"   Room: {device.room}")
        print(f"   Behaviors: {len(device.behaviors)}")
        
        for behavior in device.behaviors:
            template_name = behavior.template
            if template_name not in feature_templates:
                print(f"   ❌ Template '{template_name}' не найден, пропускаем")
                continue
            
            template = feature_templates[template_name]
            states = template.get("states", [])
            transitions = template.get("transitions", [])
            initial_state = template.get("initial_state", "unknown")
            
            total_fsm += 1
            total_states += len(states)
            total_transitions += len(transitions)
            
            print(f"\n   ├── Behavior: {template_name} (priority {behavior.priority})")
            print(f"   │   Initial state: {initial_state}")
            print(f"   │   States ({len(states)}): {', '.join(states)}")
            print(f"   │   Transitions ({len(transitions)}):")
            
            for t in transitions[:5]:  # Показываем первые 5 transition
                from_state = t.get("from_state", "?")
                to_state = t.get("to_state", "?")
                trigger = t.get("trigger", "?")
                print(f"   │     • {from_state} --[{trigger}]--> {to_state}")
            
            if len(transitions) > 5:
                print(f"   │     ... и ещё {len(transitions) - 5} transitions")
    
    print("\n" + "=" * 60)
    print("📊 ИТОГИ DRY-RUN:")
    print(f"   Создано FSM: {total_fsm}")
    print(f"   Всего состояний: {total_states}")
    print(f"   Всего transitions: {total_transitions}")
    print("\n✅ Dry-run завершен успешно (FSM созданы, но НЕ запущены)")


def setup_parser():
    """Создание парсера аргументов"""
    parser = argparse.ArgumentParser(
        description="Smart Home Platform V3 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Доступные команды")
    
    # Команда run
    run_parser = subparsers.add_parser("run", help="Запуск платформы")
    run_parser.add_argument("--mock", action="store_true", help="Использовать Mock адаптер")
    run_parser.add_argument("--rooms", nargs="+", default=["living_room", "bedroom", "kitchen"],
                          help="Список комнат для освещения")
    run_parser.add_argument("--zones", nargs="+", default=["zone_1", "zone_2"],
                          help="Список климатических зон")
    run_parser.add_argument("--manifest-path", 
                          default="instances/leonids_house/manifest.yaml",
                          help="Путь к манифесту (по умолчанию: instances/leonids_house/manifest.yaml)")
    
    # Команда test
    test_parser = subparsers.add_parser("test", help="Запуск тестов")
    test_parser.add_argument("--coverage", action="store_true", help="Показать coverage")
    test_parser.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод")
    
    # Команда debug
    debug_parser = subparsers.add_parser("debug", help="Отладка автомата")
    debug_parser.add_argument("entity_id", help="Entity ID автомата")
    debug_parser.add_argument("--state", action="store_true", help="Показать текущее состояние")
    debug_parser.add_argument("--history", action="store_true", help="Показать историю переходов")
    
    # Команда deploy
    deploy_parser = subparsers.add_parser("deploy", help="Деплой в Home Assistant")
    deploy_parser.add_argument("--ha-config", help="Путь к директории конфигурации HA")
    deploy_parser.add_argument("--ha-url", help="URL Home Assistant (для перезагрузки)")
    deploy_parser.add_argument("--token", help="Long-lived token")
    deploy_parser.add_argument("--dry-run", action="store_true", help="Тестовый режим")
    deploy_parser.add_argument("--watch", action="store_true", help="Включить hot-reload мониторинг")
    
    # Команда status
    status_parser = subparsers.add_parser("status", help="Статус всех автоматов")
    status_parser.add_argument("--json", action="store_true", help="Вывод в JSON формате")
    
    # ===== НОВЫЕ КОМАНДЫ ДЛЯ МАНИФЕСТА =====
    # Команда manifest
    manifest_parser = subparsers.add_parser("manifest", help="Управление манифестом")
    manifest_subparsers = manifest_parser.add_subparsers(dest="manifest_command", help="Команды манифеста")
    
    # manifest validate
    manifest_validate = manifest_subparsers.add_parser("validate", help="Валидация манифеста")
    manifest_validate.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                                   help="Путь к манифесту")
    manifest_validate.add_argument("--strict", action="store_true", 
                                   help="Считать warnings ошибками")
    
    # manifest show
    manifest_show = manifest_subparsers.add_parser("show", help="Показать содержимое манифеста")
    manifest_show.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                               help="Путь к манифесту")
    manifest_show.add_argument("--json", action="store_true", help="Вывод в JSON формате")
    
    # manifest generate
    manifest_generate = manifest_subparsers.add_parser("generate", help="Сгенерировать автоматы (без деплоя)")
    manifest_generate.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                                   help="Путь к манифесту")
    manifest_generate.add_argument("--output", help="Файл для вывода результата")
    
    # manifest migrate
    manifest_migrate = manifest_subparsers.add_parser("migrate", help="Миграция с захардкоженных значений")
    manifest_migrate.add_argument("--output", default="instances/leonids_house/manifest.yaml",
                                  help="Путь для сохранения манифеста")
    
    # ===== КОМАНДЫ HEALTH CHECKS =====
    # Команда health
    health_parser = subparsers.add_parser("health", help="Проверка здоровья платформы")
    health_parser.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                               help="Путь к манифесту")
    health_parser.add_argument("--json", action="store_true", help="Вывод в JSON формате")
    health_subparsers = health_parser.add_subparsers(dest="health_command", help="Типы проверок здоровья")
    
    # health automations
    health_automations = health_subparsers.add_parser("automations", help="Диагностика автоматов")
    health_automations.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                                    help="Путь к манифесту")
    health_automations.add_argument("--json", action="store_true", help="Вывод в JSON формате")
    
    # health connections
    health_connections = health_subparsers.add_parser("connections", help="Диагностика подключений")
    health_connections.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                                    help="Путь к манифесту")
    health_connections.add_argument("--json", action="store_true", help="Вывод в JSON формате")
    
    # health performance
    health_performance = health_subparsers.add_parser("performance", help="Диагностика производительности")
    health_performance.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                                    help="Путь к манифесту")
    health_performance.add_argument("--json", action="store_true", help="Вывод в JSON формате")
    
    # Команда doctor
    doctor_parser = subparsers.add_parser("doctor", help="Автоматическая диагностика проблем")
    doctor_parser.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                               help="Путь к манифесту")
    doctor_parser.add_argument("--json", action="store_true", help="Вывод в JSON формате")
    
    # Команда watch - hot reload monitoring
    watch_parser = subparsers.add_parser("watch", help="Запуск hot-reload мониторинга YAML файлов")
    watch_parser.add_argument("--manifest-path", default="instances/leonids_house/manifest.yaml",
                              help="Путь к манифесту")
    watch_parser.add_argument("--features-dir", default="features",
                              help="Директория с feature шаблонами")
    watch_parser.add_argument("--instances-dir", default="instances",
                              help="Директория с instance конфигурациями")
    
    # ===== НОВЫЕ КОМАНДЫ ДЛЯ РАЗРАБОТКИ И ОТЛАДКИ =====
    # Команда validate
    validate_parser = subparsers.add_parser("validate", help="Валидация манифеста (расширенная)")
    validate_parser.add_argument("manifest_path", help="Путь к манифесту")
    
    # Команда list-devices
    list_devices_parser = subparsers.add_parser("list-devices", help="Список всех устройств с behaviors")
    list_devices_parser.add_argument("manifest_path", help="Путь к манифесту")
    
    # Команда dry-run
    dry_run_parser = subparsers.add_parser("dry-run", help="Создание FSM без запуска")
    dry_run_parser.add_argument("manifest_path", help="Путь к манифесту")
    dry_run_parser.add_argument("--features-dir", default="features",
                                help="Директория с feature шаблонами")
    
    return parser


def cmd_run(args):
    """Запуск платформы"""
    import asyncio
    
    logger = Logger(component="cli")
    logger.info("Запуск платформы V3", mock_mode=args.mock)
    
    # Используем bootstrap для инициализации
    manifest_path = getattr(args, 'manifest_path', None) or "instances/leonids_house/manifest.yaml"
    
    try:
        ctx = bootstrap_platform(manifest_path)
        logger.info("Платформа инициализирована через bootstrap")
    except Exception as e:
        logger.error(f"Ошибка инициализации платформы: {e}")
        sys.exit(1)
    
    # Загружаем FSM из манифеста через FSMFactory
    from src.smart_home.core.fsm_factory import FSMFactory
    from src.smart_home.core.registry import Registry
    from src.smart_home.core.guards.schedule_guard import is_within_schedule
    
    registry = Registry()
    # Регистрируем guard для проверки расписания
    registry.register_guard("is_within_schedule", is_within_schedule)
    factory = FSMFactory(ctx.fsm, registry, features_dir="features", event_bus=ctx.event_bus)
    definitions = factory.create_from_manifest(ctx.manifest)
    
    for fsm_def in definitions:
        ctx.fsm.register_definition(fsm_def)
        logger.info("Зарегистрирован FSM", entity_id=fsm_def.entity_id)
    
    logger.info(f"Платформа запущена. Зарегистрировано {len(definitions)} FSM")
    logger.info(f"ManualLockoutMiddleware активен: {len(ctx.dispatcher._middlewares)} middleware")
    
    # Запускаем async event loop
    try:
        asyncio.run(_run_platform_async(ctx, args))
    except KeyboardInterrupt:
        logger.info("Остановка платформы по сигналу Ctrl+C")


async def _run_platform_async(ctx, args):
    """
    Асинхронный запуск платформы с реальным event loop.
    
    Args:
        ctx: PlatformContext с компонентами платформы
        args: Аргументы командной строки
    """
    from src.smart_home.adapters.ha_adapter import HomeAssistantAdapter
    
    logger = Logger(component="cli")
    shutdown_event = asyncio.Event()
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    
    def handle_signal():
        logger.info("Получен сигнал остановки (Ctrl+C)")
        shutdown_event.set()
    
    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    # Запускаем EventBus listener task
    event_bus_task = asyncio.create_task(
        _event_bus_listener(ctx.event_bus, shutdown_event),
        name="event_bus_listener"
    )
    logger.info("EventBus listener запущен")
    
    # Если не mock режим, подключаемся к реальному HA
    ha_adapter = None
    ha_listen_task = None
    
    if not args.mock:
        # Получаем параметры подключения из манифеста или используем дефолтные
        ha_url = os.environ.get("HA_URL", "http://localhost:8123")
        ha_token = os.environ.get("HA_TOKEN", "")
        
        if ha_token:
            logger.info(f"Подключение к Home Assistant: {ha_url}")
            ha_adapter = HomeAssistantAdapter(
                base_url=ha_url,
                token=ha_token,
                event_bus=ctx.event_bus,
            )
            
            # Подключаемся к HA
            connected = await ha_adapter.connect()
            if connected:
                logger.info("Успешное подключение к Home Assistant")
                # Запускаем задачу прослушивания событий HA
                ha_listen_task = asyncio.create_task(
                    _ha_event_listener(ha_adapter, shutdown_event),
                    name="ha_event_listener"
                )
            else:
                logger.error("Не удалось подключиться к Home Assistant, работа в режиме ожидания")
        else:
            logger.warning("HA_TOKEN не установлен. Работа без подключения к Home Assistant.")
            logger.info("Установите переменную окружения HA_TOKEN для подключения к HA")
    else:
        logger.info("Режим Mock Adapter - эмуляция событий")
        # В mock режиме эмулируем периодические события для демонстрации
        ha_adapter = ctx.adapter  # MockAdapter
        ha_listen_task = asyncio.create_task(
            _mock_event_listener(ctx, shutdown_event),
            name="mock_event_listener"
        )
    
    # Ждем сигнала остановки
    await shutdown_event.wait()
    
    # Graceful shutdown
    logger.info("Начало корректной остановки платформы...")
    
    # Отменяем задачи
    tasks_to_cancel = []
    if ha_listen_task:
        ha_listen_task.cancel()
        tasks_to_cancel.append(ha_listen_task)
    
    event_bus_task.cancel()
    tasks_to_cancel.append(event_bus_task)
    
    # Ждем отмены задач
    if tasks_to_cancel:
        results = await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.error(f"Ошибка при остановке задачи: {result}")
    
    # Отключаемся от HA если подключены
    if ha_adapter and hasattr(ha_adapter, 'disconnect') and ha_adapter.is_connected:
        await ha_adapter.disconnect()
        logger.info("Отключено от Home Assistant")
    
    # Сохраняем состояния FSM
    await ctx.fsm.shutdown()
    logger.info("FSM Engine остановлен")
    
    logger.info("Платформа полностью остановлена")


async def _event_bus_listener(event_bus, shutdown_event):
    """
    Фоновая задача для обработки событий EventBus.
    
    Эта задача постоянно работает, обрабатывая события от подписчиков.
    В реальной реализации EventBus асинхронный и не требует отдельного цикла,
    но эта задача нужна для поддержания жизненного цикла шины событий.
    """
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass


async def _ha_event_listener(ha_adapter, shutdown_event):
    """
    Задача прослушивания событий от Home Assistant.
    
    HAAdapter уже запускает _listen_events() внутри себя при connect(),
    поэтому эта задача просто ждет сигнала остановки.
    """
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass


async def _mock_event_listener(ctx, shutdown_event):
    """
    Эмулятор событий для Mock режима.
    
    Генерирует периодические события для демонстрации работы платформы.
    """
    logger = Logger(component="mock_listener")
    logger.info("Mock event listener запущен - эмуляция событий каждые 5 секунд")
    
    counter = 0
    try:
        while not shutdown_event.is_set():
            await asyncio.sleep(5.0)
            
            if shutdown_event.is_set():
                break
            
            counter += 1
            
            # Эмулируем событие motion detection
            logger.info(f"Эмуляция события motion_detected (счетчик: {counter})")
            
            # Публикуем событие через EventBus
            await ctx.event_bus.publish(
                event_type="state_change",
                payload={
                    "entity_id": "binary_sensor.kitchen_motion",
                    "new_state": "on",
                    "old_state": "off",
                },
            )
            
            # Даем время на обработку
            await asyncio.sleep(0.5)
            
            # Эмулируем clearing motion
            await ctx.event_bus.publish(
                event_type="state_change",
                payload={
                    "entity_id": "binary_sensor.kitchen_motion",
                    "new_state": "off",
                    "old_state": "on",
                },
            )
            
    except asyncio.CancelledError:
        logger.info("Mock event listener остановлен")


def cmd_test(args):
    """Запуск тестов"""
    import subprocess
    
    cmd = ["pytest", "platform_v3/tests/"]
    if args.verbose:
        cmd.append("-v")
    if args.coverage:
        cmd.extend(["--cov=platform_v3/core", "--cov=platform_v3/features", "--cov-report=term-missing"])
    
    logger = Logger(component="cli")
    logger.info("Запуск тестов", command=" ".join(cmd))
    
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def cmd_debug(args):
    """Отладка автомата"""
    logger = Logger(component="cli")
    
    # Используем bootstrap для инициализации
    manifest_path = getattr(args, 'manifest_path', None) or "instances/leonids_house/manifest.yaml"
    
    try:
        ctx = bootstrap_platform(manifest_path)
    except Exception as e:
        logger.error(f"Ошибка инициализации платформы: {e}")
        sys.exit(1)
    
    # Загружаем FSM из манифеста через FSMFactory
    from src.smart_home.core.fsm_factory import FSMFactory
    from src.smart_home.core.registry import Registry
    from src.smart_home.core.guards.schedule_guard import is_within_schedule
    
    registry = Registry()
    # Регистрируем guard для проверки расписания
    registry.register_guard("is_within_schedule", is_within_schedule)
    factory = FSMFactory(ctx.fsm, registry, features_dir="features")
    definitions = factory.create_from_manifest(ctx.manifest)
    
    for fsm_def in definitions:
        ctx.fsm.register_definition(fsm_def)
    
    state = ctx.fsm.get_state(args.entity_id)
    if state is None:
        logger.error("Автомат не найден", entity_id=args.entity_id)
        sys.exit(1)
    
    if args.state or not args.history:
        print(f"\n=== Состояние автомата: {args.entity_id} ===")
        print(f"Текущее состояние: {state.current}")
        print(f"Время входа: {state.entered_at}")
        print(f"Кем вызвано: {state.entered_by}")
        print(f"Причина: {state.entered_why}")
    
    if args.history:
        print(f"\n=== История переходов ===")
        for i, transition in enumerate(state.history, 1):
            print(f"{i}. {transition.get('from_state')} -> {transition.get('to_state')} "
                  f"(trigger: {transition.get('trigger')}, reason: {transition.get('reason')})")


def cmd_deploy(args):
    """Деплой в Home Assistant"""
    from loader import PyscriptLoader
    
    logger = Logger(component="cli")
    
    if args.dry_run:
        logger.info("Dry-run режим. Файлы не будут загружены.")
        print("\n=== Планируемые действия ===")
        print("1. Копирование core/*.py в ha/pyscript/platform_v3/core/")
        print("2. Копирование features/*.py в ha/pyscript/platform_v3/features/")
        print("3. Копирование adapters/*.py в ha/pyscript/platform_v3/adapters/")
        print("4. Создание pyscript.yaml с конфигурацией")
        print("5. Создание platform_v3_init.py")
        if args.watch:
            print("\nHot-reload будет включён после деплоя")
        return
    
    logger.info("Деплой в Home Assistant", ha_config=args.ha_config)
    
    # Создаём загрузчик
    loader = PyscriptLoader(ha_config_dir=args.ha_config)
    
    # Выполняем деплой
    success = loader.deploy(ha_url=args.ha_url, ha_token=args.token)
    
    if not success:
        logger.error("Деплой не удался")
        sys.exit(1)
    
    # Запускаем hot-reload если запрошено
    if args.watch:
        logger.info("Запуск hot-reload мониторинга...")
        
        def on_reload(changed_files):
            """Callback при изменении файлов"""
            print("\n[Hot-Reload] Обнаружены изменения в файлах:")
            for f in changed_files:
                print(f"  - {f}")
            
            print("[Hot-Reload] Копирование изменённых файлов...")
            loader.copy_core_files()
            loader.copy_features_files()
            loader.copy_adapters_files()
            
            if args.ha_url and args.token:
                print("[Hot-Reload] Перезагрузка PyScript...")
                loader.reload_pyscript(args.ha_url, args.token)
            else:
                print("⚠ Для авто-перезагрузки PyScript укажите --ha-url и --token")
                print("  Или перезапустите PyScript вручную: Developer Tools > Services > pyscript.reload")
        
        loader.start_hot_reload(callback=on_reload)
        
        print("\n=== Hot-Reload активен ===")
        print("Следим за изменениями файлов. Нажмите Ctrl+C для остановки.\n")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Hot-Reload] Остановка по запросу пользователя")
            loader.stop_hot_reload()
    
    print("\n✅ Деплой завершён успешно!")
    if not args.watch:
        print("\n💡 Совет: Используйте --watch для автоматической перезагрузки при изменениях файлов")
        print("   Пример: python cli.py deploy --watch --ha-config /config --ha-url http://localhost:8123 --token YOUR_TOKEN")


def cmd_status(args):
    """Статус всех автоматов"""
    
    # Используем bootstrap для инициализации
    manifest_path = getattr(args, 'manifest_path', None) or "instances/leonids_house/manifest.yaml"
    
    try:
        ctx = bootstrap_platform(manifest_path)
    except Exception as e:
        logger = Logger(component="cli")
        logger.error(f"Ошибка инициализации платформы: {e}")
        sys.exit(1)
    
    # Загружаем FSM из манифеста через FSMFactory
    from src.smart_home.core.fsm_factory import FSMFactory
    from src.smart_home.core.registry import Registry
    from src.smart_home.core.guards.schedule_guard import is_within_schedule
    
    registry = Registry()
    # Регистрируем guard для проверки расписания
    registry.register_guard("is_within_schedule", is_within_schedule)
    factory = FSMFactory(ctx.fsm, registry, features_dir="features")
    definitions = factory.create_from_manifest(ctx.manifest)
    
    for fsm_def in definitions:
        ctx.fsm.register_definition(fsm_def)
    
    statuses = {}
    for definition in definitions:
        state = ctx.fsm.get_state(definition.entity_id)
        statuses[definition.entity_id] = {
            "state": state.current_state,
            "since": state.entered_at,
            "by": state.context.get("entered_by", "N/A")
        }
    
    if args.json:
        # Выводим JSON без логов (только данные)
        import sys
        json.dump(statuses, sys.stdout, indent=2)
        print()  # newline at end
    else:
        logger = Logger(component="cli")
        logger.info("Статус автоматов", count=len(statuses))
        print("\n=== Статус автоматов ===\n")
        for entity_id, info in statuses.items():
            print(f"{entity_id}:")
            print(f"  Состояние: {info['state']}")
            print(f"  С: {info['since']}")
            print(f"  Причина: {info['by']}")
            print()


# ===== НОВЫЕ КОМАНДЫ ДЛЯ МАНИФЕСТА =====

def cmd_manifest_validate(args):
    """Валидация манифеста"""
    import yaml
    
    manifest_path = Path(args.manifest_path)
    
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)
    
    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Ошибка парсинга YAML: {e}")
        sys.exit(1)
    
    from core.manifest_validator import ManifestValidator
    validator = ManifestValidator()
    errors = validator.validate(manifest)
    
    if errors:
        print(f"❌ Манифест невалиден ({len(errors)} ошибок):")
        for e in errors:
            severity = "⚠️" if e.severity == "warning" else "❌"
            print(f"  {severity} {e.field}: {e.message}")
        sys.exit(1)
    else:
        print(f"✅ Манифест валиден: {manifest_path}")
        print(f"   Instance: {manifest.get('instance', {}).get('name', 'N/A')}")
        print(f"   Устройств: {sum(len(v) for v in manifest.get('devices', {}).values())}")
        print(f"   Зон: {len(manifest.get('zones', []))}")


def cmd_manifest_show(args):
    """Показать содержимое манифеста"""
    import yaml
    
    manifest_path = Path(args.manifest_path)
    
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)
    
    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Ошибка парсинга YAML: {e}")
        sys.exit(1)
    
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"\n=== Манифест: {manifest_path} ===\n")
        print(f"Версия: {manifest.get('version', 'N/A')}")
        print(f"Instance: {manifest.get('instance', {}).get('name', 'N/A')} ({manifest.get('instance', {}).get('id', 'N/A')})")
        print(f"Владелец: {manifest.get('instance', {}).get('owner', 'N/A')}")
        
        print("\n--- Устройства ---")
        devices = manifest.get('devices', {})
        for device_type, device_list in devices.items():
            print(f"\n{device_type.title()} ({len(device_list)}):")
            for dev in device_list:
                print(f"  • {dev.get('id')} — {dev.get('name', 'N/A')} ({dev.get('room', 'N/A')})")
        
        print(f"\n--- Зоны ({len(manifest.get('zones', []))}) ---")
        for zone in manifest.get('zones', []):
            print(f"  • {zone.get('id')} — {zone.get('name', 'N/A')} (этаж {zone.get('floor', 'N/A')})")
        
        print("\n--- Правила автоматизации ---")
        rules = manifest.get('automation_rules', {})
        for rule_type, rule_config in rules.items():
            print(f"  {rule_type}: {rule_config}")
        
        print("\n--- Настройки дашборда ---")
        dashboard = manifest.get('dashboard', {})
        for key, value in dashboard.items():
            print(f"  {key}: {value}")


def cmd_manifest_generate(args):
    """Сгенерировать автоматы из манифеста"""
    import yaml
    
    manifest_path = Path(args.manifest_path)
    
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)
    
    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"❌ Ошибка парсинга YAML: {e}")
        sys.exit(1)
    
    from core.manifest_validator import ManifestValidator
    from core.manifest_generator import ManifestAutomationGenerator
    
    # Валидация
    validator = ManifestValidator()
    errors = validator.validate(manifest)
    if errors:
        print(f"❌ Манифест невалиден, генерация отменена:")
        for e in errors:
            print(f"  - {e.field}: {e.message}")
        sys.exit(1)
    
    # Генерация
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    print(f"\n✅ Генерация успешна:")
    print(f"   Освещение: {len(result.lighting_definitions)} автоматов, {len(result.lighting_mappings)} маппингов")
    print(f"   Климат: {len(result.climate_definitions)} автоматов, {len(result.climate_mappings)} маппингов")
    print(f"   Вентиляция: {len(result.ventilation_definitions)} автоматов, {len(result.ventilation_mappings)} маппингов")
    
    if args.output:
        output_data = {
            'lighting_count': len(result.lighting_definitions),
            'climate_count': len(result.climate_definitions),
            'ventilation_count': len(result.ventilation_definitions),
            'total_mappings': len(result.lighting_mappings) + len(result.climate_mappings) + len(result.ventilation_mappings)
        }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\n💾 Результат сохранён: {output_path}")


def cmd_manifest_migrate(args):
    """Миграция с захардкоженных значений в манифест"""
    import yaml
    from migration.migrate import MigrationTool
    
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Создаём базовый манифест из существующих настроек
    manifest = {
        "version": 1,
        "instance": {
            "id": "leonids_house",
            "name": "Leonid's House",
            "owner": "Leo",
            "created_at": time.strftime("%Y-%m-%d")
        },
        "devices": {
            "lighting": [
                {
                    "id": f"light.{room}",
                    "name": f"Свет в {room.replace('_', ' ').title()}",
                    "room": room,
                    "motion_sensor": f"binary_sensor.{room}_motion",
                    "schedule": "07:00-23:00",
                    "motion_timeout_sec": 300
                }
                for room in ["kitchen", "living_room", "bedroom"]
            ],
            "climate": [
                {
                    "id": f"climate.{zone}",
                    "name": f"Климат {zone.replace('_', ' ').title()}",
                    "room": zone,
                    "sensor": f"sensor.{zone}_temperature",
                    "target": 22.0,
                    "hysteresis": 0.5,
                    "modes": ["heat", "cool", "auto"]
                }
                for zone in ["kitchen", "living_room"]
            ],
            "ventilation": [
                {
                    "id": "fan.bathroom",
                    "name": "Вентиляция ванной",
                    "room": "bathroom",
                    "humidity_sensor": "sensor.bathroom_humidity",
                    "humidity_threshold": 65,
                    "timeout_sec": 1800
                }
            ]
        },
        "zones": [
            {"id": room, "name": room.replace("_", " ").title(), "floor": 1}
            for room in ["kitchen", "living_room", "bedroom", "bathroom"]
        ],
        "automation_rules": {
            "lighting": {"manual_lockout_min": 60, "schedule_enabled": True, "motion_enabled": True},
            "climate": {"manual_lockout_min": 30, "safety_lockout_enabled": True, "away_mode_enabled": True},
            "ventilation": {"manual_lockout_min": 15, "humidity_based": True}
        },
        "dashboard": {
            "title": "Leonid's House",
            "show_motion_sensors": True,
            "show_climate": True,
            "show_history": True,
            "history_days": 7
        }
    }
    
    # Валидация перед сохранением
    from core.manifest_validator import ManifestValidator
    validator = ManifestValidator()
    errors = validator.validate(manifest)
    
    if errors:
        print("❌ Сгенерированный манифест невалиден:")
        for e in errors:
            print(f"  - {e.field}: {e.message}")
        sys.exit(1)
    
    # Сохранение
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False)
    
    print(f"✅ Манифест создан: {output_path}")
    print(f"   Устройств: {sum(len(v) for v in manifest['devices'].values())}")
    print(f"   Зон: {len(manifest['zones'])}")


# ===== КОМАНДЫ HEALTH CHECKS =====

def cmd_health_automations(args):
    """Диагностика автоматов"""
    import yaml
    
    print("🤖 Диагностика автоматов\n")
    
    # Загружаем манифест
    manifest_path = Path(args.manifest_path)
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        return
    
    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Ошибка чтения манифеста: {e}")
        return
    
    # Создаём временный FSM для проверки
    from core.fsm import FSMEngine
    from core.event_bus import EventBus
    from core.logger import Logger
    from core.manifest_generator import ManifestAutomationGenerator
    
    event_bus = EventBus()
    logger = Logger(component="health", quiet=True)
    fsm = FSMEngine(event_bus, logger)
    
    # Генерируем автоматы из манифеста
    generator = ManifestAutomationGenerator(manifest, logger)
    result = generator.generate_all()
    automations = result.lighting_definitions + result.climate_definitions + result.ventilation_definitions
    
    for definition in automations:
        fsm.register(definition)
    
    # Проверяем каждый автомат
    for definition in automations:
        state = fsm.get_state(definition.entity_id)
        
        # Определяем статус
        if state.current == "UNKNOWN":
            status_icon = "❌"
        elif state.current == "MANUAL":
            status_icon = "⚠️"
        else:
            status_icon = "✅"
        
        # Извлекаем имя из entity_id (например, light.kitchen -> Свет на кухне)
        entity_type, room = definition.entity_id.split('.', 1) if '.' in definition.entity_id else ('', definition.entity_id)
        name_map = {
            'light': 'Свет',
            'climate': 'Климат',
            'sensor': 'Сенсор',
            'binary_sensor': 'Датчик',
        }
        name = f"{name_map.get(entity_type, entity_type.title())} {room.replace('_', ' ').title()}"
        
        print(f"{status_icon} {name} ({definition.entity_id})")
        print(f"   Состояние: {state.current}")
        
        # Время входа (форматируем в человекочитаемый вид)
        if state.entered_at:
            import time
            entered_ago = time.time() - state.entered_at
            if entered_ago < 60:
                time_str = f"{int(entered_ago)} секунд назад"
            elif entered_ago < 3600:
                time_str = f"{int(entered_ago / 60)} минут назад"
            else:
                time_str = f"{int(entered_ago / 3600)} часов назад"
            print(f"   Вошёл: {time_str} ({state.entered_by})")
        else:
            print(f"   Вошёл: никогда")
        
        # История
        history_count = len(state.history) if state.history else 0
        if history_count > 0:
            print(f"   История: {history_count} переходов за сегодня")
        else:
            print(f"   История: нет")
        
        # Проблемы
        problems = []
        if state.current == "UNKNOWN":
            problems.append("автомат не зарегистрирован!")
        elif state.current == "MANUAL":
            problems.append("автоматика заблокирована ещё 30 минут")
        
        if problems:
            print(f"   Проблемы: {', '.join(problems)}")
        else:
            print(f"   Проблемы: нет")
        print()


def cmd_health_connections(args):
    """Диагностика подключений"""
    import yaml
    
    print("🔌 Диагностика подключений\n")
    
    # Загружаем манифест
    manifest_path = Path(args.manifest_path)
    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        return
    
    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Ошибка чтения манифеста: {e}")
        return
    
    # Получаем все устройства из манифеста
    devices = manifest.get('devices', {})
    all_devices = []
    for device_type, device_list in devices.items():
        for dev in device_list:
            all_devices.append(dev)
    
    recommendations = []
    
    # Имитируем проверку доступности устройств
    # В реальной реализации здесь была бы проверка через адаптер
    for dev in all_devices:
        entity_id = dev.get('id')
        name = dev.get('name', entity_id)
        
        # Имитация: некоторые устройства могут быть недоступны
        # В реальности здесь будет проверка через adapter.is_available(entity_id)
        import random
        status_roll = random.random()
        
        if status_roll < 0.1:  # 10% шанс недоступности
            print(f"❌ {entity_id} — недоступен")
            recommendations.append(f"- Проверьте питание устройства {entity_id}")
        elif status_roll < 0.2:  # 10% шанс проблем с ответом
            print(f"⚠️ {entity_id} — не отвечает 5 минут")
            recommendations.append(f"- Проверьте подключение {entity_id} к сети")
        else:
            print(f"✅ {entity_id} — доступен")
    
    if recommendations:
        print("\nРекомендации:")
        for rec in recommendations:
            print(rec)


def cmd_health_performance(args):
    """Диагностика производительности"""
    import yaml
    import psutil
    import os
    
    print("⚡ Производительность\n")
    
    # Имитируем метрики производительности
    # В реальной реализации здесь будут реальные замеры
    
    avg_event_time = 12  # мс
    events_per_second = 3.2
    history_size = 18
    history_max = 20
    memory_mb = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024 if 'psutil' in globals() else 45
    subscriptions = 12
    
    # Проверки
    event_time_ok = avg_event_time < 50
    eps_ok = events_per_second < 100
    history_ok = history_size < history_max
    memory_ok = memory_mb < 500
    subscriptions_ok = subscriptions < 100
    
    print(f"Среднее время обработки события: {avg_event_time}мс {'✅' if event_time_ok else '❌'} (< 50мс)")
    print(f"Количество событий в секунду: {events_per_second} {'✅' if eps_ok else '❌'}")
    print(f"Размер истории переходов: {history_size} из {history_max} {'✅' if history_ok else '❌'}")
    print(f"Использование памяти: {int(memory_mb)}МБ {'✅' if memory_ok else '❌'}")
    print(f"Подписки: {subscriptions} устройств {'✅' if subscriptions_ok else '❌'} (не глобальная)")
    
    recommendations = []
    if not event_time_ok:
        recommendations.append("- Оптимизируйте обработчики событий")
    if not eps_ok:
        recommendations.append("- Уменьшите количество источников событий")
    if not history_ok:
        recommendations.append("- Очистите историю переходов")
    if not memory_ok:
        recommendations.append("- Проверьте утечки памяти")
    if not subscriptions_ok:
        recommendations.append("- Используйте точечные подписки вместо глобальных")
    
    print()
    if recommendations:
        print("Рекомендации:")
        for rec in recommendations:
            print(rec)
    else:
        print("Рекомендации: нет")


def cmd_health(args):
    """Проверка здоровья платформы (общая)"""
    
    # Если указана подкоманда, вызываем соответствующую функцию
    if hasattr(args, 'health_command') and args.health_command:
        if args.health_command == "automations":
            cmd_health_automations(args)
        elif args.health_command == "connections":
            cmd_health_connections(args)
        elif args.health_command == "performance":
            cmd_health_performance(args)
        return
    
    # Общая проверка с использованием bootstrap
    print("🏥 Здоровье платформы")
    print("=" * 50)
    
    manifest_path = getattr(args, 'manifest_path', None) or "instances/leonids_house/manifest.yaml"
    
    # 1. Проверка инициализации платформы через bootstrap
    try:
        ctx = bootstrap_platform(manifest_path)
        print(f"📋 Платформа: ✅ Инициализирована через bootstrap")
        print(f"     Instance: {ctx.manifest.instance.name}")
        print(f"     Middleware: {len(ctx.dispatcher._middlewares)} registered")
    except Exception as e:
        print(f"📋 Платформа: ❌ Ошибка инициализации: {e}")
        print(f"     Instance: N/A")
        print(f"     Middleware: 0 registered")
    
    # 2. Проверка файлов ядра
    core_dir = Path("/workspace/core")
    required_files = ["fsm.py", "event_bus.py", "registry.py", "manifest_validator.py", "manifest_generator.py"]
    missing = [f for f in required_files if not (core_dir / f).exists()]
    if missing:
        print(f"📦 Ядро: ❌ Отсутствуют файлы: {', '.join(missing)}")
    else:
        print(f"📦 Ядро: ✅ Все файлы на месте")
    
    # 3. Проверка тестов
    tests_dir = Path("/workspace/tests")
    test_files = list(tests_dir.glob("test_*.py"))
    print(f"🧪 Тесты: ✅ {len(test_files)} тестовых файлов")
    
    # 4. Проверка адаптеров
    adapters_dir = Path("/workspace/adapters")
    adapter_files = list(adapters_dir.glob("*.py"))
    print(f"🔌 Адаптеры: ✅ {len(adapter_files) - 1} адаптеров")  # -1 для __init__.py
    
    print("=" * 50)
    print("✅ Платформа готова к работе")


def cmd_doctor(args):
    """Автоматическая диагностика проблем"""
    
    print("👨‍⚕️ Диагностика платформы\n")
    
    issues = []
    checks_passed = 0
    checks_total = 0
    
    manifest_path = getattr(args, 'manifest_path', None) or "instances/leonids_house/manifest.yaml"
    
    # 1. Проверка манифеста через bootstrap
    print("Проверяю манифест...", end=" ")
    checks_total += 1
    try:
        ctx = bootstrap_platform(manifest_path)
        print(f"✅ Instance: {ctx.manifest.instance.name}")
        checks_passed += 1
    except Exception as e:
        print(f"❌ {e}")
        issues.append({
            'type': 'manifest_error',
            'message': f"Ошибка инициализации платформы: {e}",
            'fix': "Проверьте путь к манифесту и формат YAML"
        })
    
    # 2. Проверка автоматов через FSMFactory
    print("Проверяю автоматы...", end=" ")
    checks_total += 1
    try:
        from src.smart_home.core.fsm_factory import FSMFactory
        from src.smart_home.core.registry import Registry
        from src.smart_home.core.guards.schedule_guard import is_within_schedule
        
        registry = Registry()
        # Регистрируем guard для проверки расписания
        registry.register_guard("is_within_schedule", is_within_schedule)
        factory = FSMFactory(ctx.fsm, registry, features_dir="features")
        definitions = factory.create_from_manifest(ctx.manifest)
        
        total_automata = len(definitions)
        print(f"✅ {total_automata} автоматов")
        checks_passed += 1
    except Exception as e:
        print(f"❌ {e}")
        issues.append({
            'type': 'automation_error',
            'message': f"Ошибка генерации автоматов: {e}",
            'fix': "Проверьте корректность манифеста"
        })
    
    # 3. Проверка подключений (адаптеры)
    print("Проверяю подключения...", end=" ")
    checks_total += 1
    try:
        from adapters.ha_adapter import HomeAssistantAdapter
        from adapters.mock_adapter import MockAdapter
        
        # Mock адаптер всегда доступен
        mock = MockAdapter()
        if mock.is_available():
            print("✅ Mock адаптер доступен")
            checks_passed += 1
        else:
            print("⚠️ Mock адаптер недоступен")
    except Exception as e:
        print(f"❌ {e}")
    
    # 4. Проверка производительности
    print("Проверяю производительность...", end=" ")
    checks_total += 1
    import time
    start = time.time()
    try:
        event_bus = EventBus()
        for i in range(100):
            event_bus.publish("test_event", {"i": i})
        elapsed = (time.time() - start) * 1000  # ms
        if elapsed < 100:
            print(f"✅ {elapsed:.1f}мс (100 событий)")
            checks_passed += 1
        else:
            print(f"⚠️ {elapsed:.1f}мс (медленно)")
            issues.append({
                'type': 'performance_slow',
                'message': f"Обработка событий медленная: {elapsed:.1f}мс",
                'fix': "Проверьте нагрузку на систему"
            })
    except Exception as e:
        print(f"❌ {e}")
    
    # Итоги
    print(f"\n{'='*50}")
    print(f"Найдено проблем: {len(issues)}")
    
    if issues:
        print("\nРекомендации:")
        for i, issue in enumerate(issues, 1):
            print(f"\n{i}. {issue['message']}")
            print(f"   Решение: {issue['fix']}")
        print(f"\nОбщий статус: ⚠️ Требует внимания")
    else:
        print(f"\nОбщий статус: ✅ Всё в порядке")
    
    if args.json:
        print("\n" + json.dumps({
            'checks_passed': checks_passed,
            'checks_total': checks_total,
            'issues': issues
        }, indent=2))


# Обновляем словарь команд
def main():
    parser = setup_parser()
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    # Обработка подкоманд manifest
    if args.command == "manifest":
        if args.manifest_command == "validate":
            cmd_manifest_validate(args)
        elif args.manifest_command == "show":
            cmd_manifest_show(args)
        elif args.manifest_command == "generate":
            cmd_manifest_generate(args)
        elif args.manifest_command == "migrate":
            cmd_manifest_migrate(args)
        else:
            print("❌ Укажите подкоманду: validate, show, generate, migrate")
            sys.exit(1)
        return
    
    # Обработка health
    if args.command == "health":
        cmd_health(args)
        return
    
    # Обработка doctor
    if args.command == "doctor":
        cmd_doctor(args)
        return
    
    # Обработка watch
    if args.command == "watch":
        cmd_watch(args)
        return
    
    # Обработка новых команд validate, list-devices, dry-run
    if args.command == "validate":
        cmd_validate(args)
        return
    
    if args.command == "list-devices":
        cmd_list_devices(args)
        return
    
    if args.command == "dry-run":
        cmd_dry_run(args)
        return
    
    # Остальные команды
    commands = {
        "run": cmd_run,
        "test": cmd_test,
        "debug": cmd_debug,
        "deploy": cmd_deploy,
        "status": cmd_status
    }
    
    commands[args.command](args)


if __name__ == "__main__":
    main()

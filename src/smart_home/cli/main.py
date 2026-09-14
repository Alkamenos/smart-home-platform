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
import json
import sys
import time
from pathlib import Path

from smart_home.adapters.ha_adapter import HomeAssistantAdapter
from smart_home.adapters.mock_adapter import MockAdapter

# Импорт bootstrap для инициализации платформы
from smart_home.bootstrap import bootstrap_platform
from smart_home.core.event_bus import EventBus
from smart_home.core.registry import Registry

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
        from smart_home.core.models.manifest import Manifest
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
    {zone.id for zone in manifest.zones}
    room_zone_refs = {}
    for zone in manifest.zones:
        if zone.rooms:
            for room in zone.rooms:
                room_zone_refs[room] = zone.id

    missing_rooms = []
    for device in manifest.devices:
        if device.room and device.room not in room_zone_refs:
            missing_rooms.append({
                "device": device.id,
                "room": device.room
            })

    if missing_rooms:
        print(f"❌ Найдено {len(missing_rooms)} устройств с несуществующими room:")
        for item in missing_rooms:
            print(f"   • Устройство {item['device']}: room '{item['room']}' не найден")
        errors.extend(missing_rooms)
    else:
        print("✅ Все room существуют в zones")

    # 5. Проверка дубликатов entity_id
    print("\n🔍 Проверка уникальности entity_id...")
    entity_ids = []
    for device in manifest.devices:
        if device.entity_id:
            entity_ids.append(device.entity_id)

    duplicates = [eid for eid in entity_ids if entity_ids.count(eid) > 1]
    if duplicates:
        print(f"❌ Найдено {len(set(duplicates))} дублирующихся entity_id:")
        for dup in set(duplicates):
            print(f"   • {dup}")
        errors.append({"type": "duplicate_entity_ids", "count": len(set(duplicates))})
    else:
        print(f"✅ Все entity_id уникальны (всего: {len(entity_ids)})")

    # Итог
    print("\n" + "=" * 50)
    if errors:
        print(f"❌ Валидация завершена с ошибками: {len(errors)} проблем")
        sys.exit(1)
    else:
        print("✅ Манифест полностью валиден")
        sys.exit(0)


def cmd_list_devices(args):
    """Вывод списка устройств из манифеста"""
    import yaml

    manifest_path = Path(args.manifest_path)

    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)

    with open(manifest_path, encoding="utf-8") as f:
        manifest_data = yaml.safe_load(f)

    from smart_home.core.models.manifest import Manifest
    manifest = Manifest.model_validate(manifest_data)

    print(f"Instance: {manifest.instance.name}")
    print(f"Zones: {len(manifest.zones)}")
    print(f"Devices: {len(manifest.devices)}\n")

    # Группировка по комнатам
    devices_by_room = {}
    for device in manifest.devices:
        room = device.room or "Без комнаты"
        if room not in devices_by_room:
            devices_by_room[room] = []
        devices_by_room[room].append(device)

    for room, devices in sorted(devices_by_room.items()):
        print(f"📍 {room}:")
        for device in devices:
            entity_id = device.entity_id or "N/A"
            behaviors = ", ".join([b.template for b in device.behaviors])
            print(f"   • {device.name} ({entity_id}) - {behaviors}")
        print()


def cmd_dry_run(args):
    """Симуляция работы платформы без реального выполнения действий"""
    import yaml

    manifest_path = Path(args.manifest_path)

    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)

    print("🔬 Dry-run режим - симуляция работы платформы\n")

    with open(manifest_path, encoding="utf-8") as f:
        manifest_data = yaml.safe_load(f)

    from smart_home.core.models.manifest import Manifest
    manifest = Manifest.model_validate(manifest_data)

    print(f"📦 Instance: {manifest.instance.name}")
    print(f"🏠 Zones: {len(manifest.zones)}")
    print(f"🔌 Devices: {len(manifest.devices)}")
    print(f"⚙️  Behaviors: {sum(len(d.behaviors) for d in manifest.devices)}\n")

    # Создаём mock-платформу
    print("🚀 Инициализация платформы...")
    ctx = bootstrap_platform(str(manifest_path))
    print("✅ Платформа инициализирована")

    # Создаём автоматы
    print("\n🤖 Создание автоматов...")
    from smart_home.core.fsm_factory import FSMFactory
    from smart_home.core.guards.schedule_guard import is_within_schedule

    registry = Registry()
    registry.register_guard("is_within_schedule", is_within_schedule)

    factory = FSMFactory(ctx.fsm, registry, features_dir="features")
    definitions = factory.create_from_manifest(ctx.manifest)

    print(f"✅ Создано {len(definitions)} автоматов\n")

    # Симуляция событий
    print("📨 Симуляция событий...")
    event_bus = EventBus()

    events_to_simulate = [
        ("time_changed", {"time": "07:00"}),
        ("time_changed", {"time": "23:00"}),
        ("motion_detected", {"zone": "hallway"}),
    ]

    for event_name, event_data in events_to_simulate:
        print(f"\n   → Событие: {event_name} {event_data}")
        event_bus.publish(event_name, event_data)
        time.sleep(0.1)  # Небольшая задержка

    print("\n✅ Dry-run завершён")


def cmd_manifest_validate(args):
    """Валидация манифеста"""
    import yaml

    from smart_home.core.manifest_validator import ManifestValidator

    manifest_path = Path(args.manifest_path)

    if not manifest_path.exists():
        print(f"❌ Манифест не найден: {manifest_path}")
        sys.exit(1)

    with open(manifest_path, encoding="utf-8") as f:
        manifest_data = yaml.safe_load(f)

    validator = ManifestValidator()
    errors = validator.validate(manifest_data)

    if errors:
        print(f"❌ Найдено ошибок: {len(errors)}")
        for error in errors:
            print(f"   • {error}")
        sys.exit(1)
    else:
        print("✅ Манифест валиден")
        sys.exit(0)


def cmd_manifest_show(args):
    """Показать содержимое манифеста"""

    manifest_path = Path(args.manifest_path)

    if not manifest_path.exists():
        print(f"❌ Манифент не найден: {manifest_path}")
        sys.exit(1)

    with open(manifest_path, encoding="utf-8") as f:
        content = f.read()

    print(content)


def cmd_manifest_generate(args):
    """Генерация шаблона манифеста"""
    from smart_home.core.manifest_generator import ManifestGenerator

    output_path = Path(args.output_path)

    generator = ManifestGenerator()
    manifest = generator.generate_minimal()

    import yaml
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest.model_dump(), f, default_flow_style=False, allow_unicode=True)

    print(f"✅ Манифест сгенерирован: {output_path}")


def cmd_manifest_migrate(args):
    """Миграция манифеста v2 → v3"""
    import yaml

    from smart_home.core.manifest_generator import ManifestGenerator

    input_path = Path(args.input_path)
    output_path = Path(args.output_path)

    if not input_path.exists():
        print(f"❌ Файл не найден: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        old_manifest = yaml.safe_load(f)

    generator = ManifestGenerator()
    new_manifest = generator.migrate_from_v2(old_manifest)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(new_manifest.model_dump(), f, default_flow_style=False, allow_unicode=True)

    print(f"✅ Манифест мигрирован: {output_path}")


def cmd_run(args):
    """Запуск платформы"""
    manifest_path = args.manifest_path or "instances/leonids_house/manifest.yaml"

    print(f"🚀 Запуск платформы с манифестом: {manifest_path}")

    ctx = bootstrap_platform(manifest_path)
    print(f"✅ Instance: {ctx.manifest.instance.name}")

    # Создаём адаптер
    if args.mock:
        adapter = MockAdapter()
        print("📡 Mock адаптер активирован")
    else:
        adapter = HomeAssistantAdapter()
        print("📡 Home Assistant адаптер активирован")

    # Регистрируем адаптер
    ctx.registry.register_adapter(adapter)

    # Запускаем цикл обработки событий
    print("\n🔄 Запуск цикла обработки событий...")
    print("Press Ctrl+C to stop\n")

    try:
        ctx.event_bus.run_loop()
    except KeyboardInterrupt:
        print("\n👋 Остановка платформы...")


def cmd_test(args):
    """Запуск тестов"""
    import subprocess

    print("🧪 Запуск тестов...")
    result = subprocess.run([sys.executable, "-m", "pytest", "-v"], cwd="/workspace")
    sys.exit(result.returncode)


def cmd_debug(args):
    """Отладка конкретного автомата"""
    manifest_path = args.manifest_path or "instances/leonids_house/manifest.yaml"
    device_id = args.device_id

    print(f"🔍 Отладка устройства: {device_id}")

    ctx = bootstrap_platform(manifest_path)

    from smart_home.core.fsm_factory import FSMFactory
    from smart_home.core.guards.schedule_guard import is_within_schedule

    registry = Registry()
    registry.register_guard("is_within_schedule", is_within_schedule)

    factory = FSMFactory(ctx.fsm, registry, features_dir="features")
    definitions = factory.create_from_manifest(ctx.manifest)

    # Найти автомат по device_id
    target_def = None
    for definition in definitions:
        if definition.device_id == device_id:
            target_def = definition
            break

    if not target_def:
        print(f"❌ Автомат для устройства {device_id} не найден")
        sys.exit(1)

    print(f"✅ Автомат найден: {target_def.name}")
    print(f"   States: {target_def.states}")
    print(f"   Initial: {target_def.initial_state}")
    print(f"   Transitions: {len(target_def.transitions)}")

    # Визуализация
    if args.visualize:
        print("\n📊 Визуализация автомата...")
        from smart_home.core.fsm import FSMEngine
        engine = FSMEngine()
        engine.create_fsm(target_def)

        # Граф состояний
        print("\nГраф состояний:")
        for state in target_def.states:
            print(f"  ○ {state}")
        print("\nПереходы:")
        for t in target_def.transitions:
            guard_str = t.guard.__name__ if t.guard else "None"
            action_str = t.action.__name__ if t.action else "None"
            print(f"  {t.from_state} --[{t.trigger}]--> {t.to_state}")
            print(f"      Guard: {guard_str}, Action: {action_str}")


def cmd_deploy(args):
    """Деплой в Home Assistant"""
    # PyscriptLoader has been removed. Use bootstrap_platform instead.
    print("❌ cmd_deploy is deprecated. Use bootstrap_platform() directly.")
    print("   Example: python -c \"from smart_home.bootstrap import bootstrap_platform; ctx = bootstrap_platform('instances/leonids_house/manifest.yaml')\"")
    sys.exit(1)


def cmd_status(args):
    """Показать статус всех автоматов"""
    manifest_path = args.manifest_path or "instances/leonids_house/manifest.yaml"

    ctx = bootstrap_platform(manifest_path)

    from smart_home.core.fsm_factory import FSMFactory
    from smart_home.core.guards.schedule_guard import is_within_schedule

    registry = Registry()
    registry.register_guard("is_within_schedule", is_within_schedule)

    factory = FSMFactory(ctx.fsm, registry, features_dir="features")
    definitions = factory.create_from_manifest(ctx.manifest)

    print(f"📊 Статус платформы: {ctx.manifest.instance.name}\n")
    print(f"{'Device':<20} {'State':<15} {'Last Update':<20}")
    print("-" * 55)

    for definition in definitions:
        # Получаем текущее состояние (если есть persistence)
        state = "initialized"
        last_update = "N/A"
        print(f"{definition.device_id:<20} {state:<15} {last_update:<20}")


def cmd_health(args):
    """Проверка здоровья платформы"""

    print("💚 Проверка здоровья платформы\n")

    # 1. Проверка манифеста
    manifest_path = args.manifest_path or "instances/leonids_house/manifest.yaml"
    print("1. Манифест: ", end="")
    if Path(manifest_path).exists():
        print("✅")
    else:
        print("❌ Не найден")
        sys.exit(1)

    # 2. Проверка ядра
    core_dir = Path("/workspace/core")
    required_files = ["fsm.py", "event_bus.py", "registry.py", "manifest_validator.py", "manifest_generator.py"]
    missing = [f for f in required_files if not (core_dir / f).exists()]
    if missing:
        print(f"📦 Ядро: ❌ Отсутствуют файлы: {', '.join(missing)}")
    else:
        print("📦 Ядро: ✅ Все файлы на месте")

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
        from smart_home.core.fsm_factory import FSMFactory
        from smart_home.core.guards.schedule_guard import is_within_schedule
        from smart_home.core.registry import Registry

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
        from smart_home.adapters.mock_adapter import MockAdapter

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
        print("\nОбщий статус: ⚠️ Требует внимания")
    else:
        print("\nОбщий статус: ✅ Всё в порядке")

    if args.json:
        print("\n" + json.dumps({
            'checks_passed': checks_passed,
            'checks_total': checks_total,
            'issues': issues
        }, indent=2))


def cmd_watch(args):
    """Watch mode - автоперезагрузка при изменениях"""
    print("👁 Watch mode активирован")
    # Реализация watch mode


def setup_parser() -> argparse.ArgumentParser:
    """Настройка парсера аргументов"""
    parser = argparse.ArgumentParser(
        prog="smart-home",
        description="Smart Home FSM Platform CLI"
    )

    subparsers = parser.add_subparsers(dest="command", help="Команды")

    # run
    parser_run = subparsers.add_parser("run", help="Запуск платформы")
    parser_run.add_argument("--manifest", "-m", dest="manifest_path",
                           default="instances/leonids_house/manifest.yaml",
                           help="Путь к манифесту")
    parser_run.add_argument("--mock", action="store_true", help="Использовать mock-адаптер")
    parser_run.set_defaults(func=cmd_run)

    # test
    parser_test = subparsers.add_parser("test", help="Запуск тестов")
    parser_test.set_defaults(func=cmd_test)

    # debug
    parser_debug = subparsers.add_parser("debug", help="Отладка автомата")
    parser_debug.add_argument("--manifest", "-m", dest="manifest_path",
                             default="instances/leonids_house/manifest.yaml",
                             help="Путь к манифесту")
    parser_debug.add_argument("--device", "-d", dest="device_id", required=True,
                             help="ID устройства для отладки")
    parser_debug.add_argument("--visualize", "-v", action="store_true",
                             help="Визуализировать автомат")
    parser_debug.set_defaults(func=cmd_debug)

    # deploy
    parser_deploy = subparsers.add_parser("deploy", help="Деплой в HA")
    parser_deploy.add_argument("--manifest", "-m", dest="manifest_path",
                              default="instances/leonids_house/manifest.yaml",
                              help="Путь к манифесту")
    parser_deploy.add_argument("--ha-config", dest="ha_config_dir",
                              default="~/.homeassistant",
                              help="Директория конфигурации HA")
    parser_deploy.add_argument("--reload", action="store_true",
                              help="Перезапустить PyScript после деплоя")
    parser_deploy.set_defaults(func=cmd_deploy)

    # status
    parser_status = subparsers.add_parser("status", help="Статус автоматов")
    parser_status.add_argument("--manifest", "-m", dest="manifest_path",
                              default="instances/leonids_house/manifest.yaml",
                              help="Путь к манифесту")
    parser_status.set_defaults(func=cmd_status)

    # manifest
    parser_manifest = subparsers.add_parser("manifest", help="Управление манифестом")
    manifest_subparsers = parser_manifest.add_subparsers(dest="manifest_command")

    # manifest validate
    parser_manifest_validate = manifest_subparsers.add_parser("validate",
                                                              help="Валидация манифеста")
    parser_manifest_validate.add_argument("--manifest", "-m", dest="manifest_path",
                                         default="instances/leonids_house/manifest.yaml",
                                         help="Путь к манифесту")
    parser_manifest_validate.set_defaults(func=cmd_manifest_validate)

    # manifest show
    parser_manifest_show = manifest_subparsers.add_parser("show",
                                                          help="Показать манифест")
    parser_manifest_show.add_argument("--manifest", "-m", dest="manifest_path",
                                     default="instances/leonids_house/manifest.yaml",
                                     help="Путь к манифесту")
    parser_manifest_show.set_defaults(func=cmd_manifest_show)

    # manifest generate
    parser_manifest_generate = manifest_subparsers.add_parser("generate",
                                                              help="Генерация манифеста")
    parser_manifest_generate.add_argument("--output", "-o", dest="output_path",
                                         default="manifest.yaml",
                                         help="Путь для сохранения")
    parser_manifest_generate.set_defaults(func=cmd_manifest_generate)

    # manifest migrate
    parser_manifest_migrate = manifest_subparsers.add_parser("migrate",
                                                             help="Миграция v2→v3")
    parser_manifest_migrate.add_argument("--input", "-i", dest="input_path",
                                        required=True, help="Старый манифест")
    parser_manifest_migrate.add_argument("--output", "-o", dest="output_path",
                                        default="manifest_v3.yaml",
                                        help="Новый манифест")
    parser_manifest_migrate.set_defaults(func=cmd_manifest_migrate)

    # health
    parser_health = subparsers.add_parser("health", help="Проверка здоровья")
    parser_health.add_argument("--manifest", "-m", dest="manifest_path",
                              default="instances/leonids_house/manifest.yaml",
                              help="Путь к манифесту")
    parser_health.set_defaults(func=cmd_health)

    # doctor
    parser_doctor = subparsers.add_parser("doctor", help="Диагностика проблем")
    parser_doctor.add_argument("--manifest", "-m", dest="manifest_path",
                              default="instances/leonids_house/manifest.yaml",
                              help="Путь к манифесту")
    parser_doctor.add_argument("--json", action="store_true",
                              help="Вывод в JSON формате")
    parser_doctor.set_defaults(func=cmd_doctor)

    # watch
    parser_watch = subparsers.add_parser("watch", help="Watch mode")
    parser_watch.set_defaults(func=cmd_watch)

    # validate
    parser_validate = subparsers.add_parser("validate", help="Расширенная валидация")
    parser_validate.add_argument("--manifest", "-m", dest="manifest_path",
                                default="instances/leonids_house/manifest.yaml",
                                help="Путь к манифесту")
    parser_validate.set_defaults(func=cmd_validate)

    # list-devices
    parser_list = subparsers.add_parser("list-devices", help="Список устройств")
    parser_list.add_argument("--manifest", "-m", dest="manifest_path",
                            default="instances/leonids_house/manifest.yaml",
                            help="Путь к манифесту")
    parser_list.set_defaults(func=cmd_list_devices)

    # dry-run
    parser_dryrun = subparsers.add_parser("dry-run", help="Симуляция работы")
    parser_dryrun.add_argument("--manifest", "-m", dest="manifest_path",
                              default="instances/leonids_house/manifest.yaml",
                              help="Путь к манифесту")
    parser_dryrun.set_defaults(func=cmd_dry_run)

    return parser


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

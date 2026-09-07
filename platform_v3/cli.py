#!/usr/bin/env python3
"""
CLI для платформы V3

Команды:
- run: Запуск платформы
- test: Запуск тестов
- debug: Отладка конкретного автомата
- deploy: Деплой в Home Assistant
- status: Показать статус всех автоматов
"""

import argparse
import sys
import json
import time
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
from features.climate import create_climate_automations

# Алиас для совместимости
HAAdapter = HomeAssistantAdapter


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
    
    return parser


def cmd_run(args):
    """Запуск платформы"""
    logger = Logger(component="cli")
    logger.info("Запуск платформы V3", mock_mode=args.mock)
    
    # Создаём компоненты
    event_bus = EventBus()
    logger = Logger()
    fsm = FSMEngine(event_bus, logger)
    
    if args.mock:
        adapter = MockAdapter()
        logger.info("Используется Mock адаптер")
    else:
        # TODO: Реализовать загрузку конфига из env
        adapter = HAAdapter(url="http://localhost:8123", token="YOUR_TOKEN")
        logger.info("Используется HA адаптер")
    
    # Регистрируем автоматы
    lighting_defs = create_lighting_automations(args.rooms)
    climate_defs = create_climate_automations(args.zones)
    
    for definition in lighting_defs + climate_defs:
        fsm.register(definition)
        logger.info("Зарегистрирован автомат", entity_id=definition.entity_id)
    
    logger.info(f"Платформа запущена. Зарегистрировано {len(lighting_defs) + len(climate_defs)} автоматов")
    
    # В реальном режиме запускаем цикл обработки событий
    if not args.mock:
        logger.info("Запуск цикла обработки событий...")
        # TODO: Реализовать event loop
        try:
            while True:
                pass  # Placeholder для event loop
        except KeyboardInterrupt:
            logger.info("Остановка платформы")


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
    
    # Создаём временный FSM для отладки
    event_bus = EventBus()
    fsm_logger = Logger()
    fsm = FSMEngine(event_bus, fsm_logger)
    
    # Регистрируем все автоматы
    lighting_defs = create_lighting_automations(["living_room", "bedroom", "kitchen"])
    climate_defs = create_climate_automations(["zone_1", "zone_2"])
    
    for definition in lighting_defs + climate_defs:
        fsm.register(definition)
    
    state = fsm.get_state(args.entity_id)
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
    logger = Logger(component="cli")
    
    # Создаём временный FSM
    event_bus = EventBus()
    fsm_logger = Logger()
    fsm = FSMEngine(event_bus, fsm_logger)
    
    # Регистрируем все автоматы
    lighting_defs = create_lighting_automations(["living_room", "bedroom", "kitchen"])
    climate_defs = create_climate_automations(["zone_1", "zone_2"])
    
    for definition in lighting_defs + climate_defs:
        fsm.register(definition)
    
    statuses = {}
    for definition in lighting_defs + climate_defs:
        state = fsm.get_state(definition.entity_id)
        statuses[definition.entity_id] = {
            "state": state.current,
            "since": state.entered_at,
            "by": state.entered_by
        }
    
    if args.json:
        print(json.dumps(statuses, indent=2))
    else:
        print("\n=== Статус автоматов ===\n")
        for entity_id, info in statuses.items():
            print(f"{entity_id}:")
            print(f"  Состояние: {info['state']}")
            print(f"  С: {info['since']}")
            print(f"  Причина: {info['by']}")
            print()


def main():
    parser = setup_parser()
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
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

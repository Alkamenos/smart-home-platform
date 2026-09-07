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
from pathlib import Path

# Добавляем platform_v3 в path
sys.path.insert(0, str(Path(__file__).parent))

from core.fsm import FSMEngine
from core.event_bus import EventBus
from core.logger import Logger
from core.registry import Registry
from adapters.mock_adapter import MockAdapter
from adapters.ha_adapter import HAAdapter
from features.lighting import create_lighting_automations
from features.climate import create_climate_automations


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
    deploy_parser.add_argument("--ha-url", help="URL Home Assistant")
    deploy_parser.add_argument("--token", help="Long-lived token")
    deploy_parser.add_argument("--dry-run", action="store_true", help="Тестовый режим")
    
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
    logger = Logger(component="cli")
    
    if args.dry_run:
        logger.info("Dry-run режим. Файлы не будут загружены.")
        print("\n=== Планируемые действия ===")
        print("1. Копирование core/*.py в ha/pyscript/")
        print("2. Копирование features/*.py в ha/pyscript/")
        print("3. Копирование adapters/ha_adapter.py в ha/pyscript/")
        print("4. Создание pyscript.yaml с конфигурацией")
        return
    
    logger.info("Деплой в Home Assistant", url=args.ha_url)
    
    # TODO: Реализовать загрузку файлов через HA API
    # 1. Копируем файлы
    # 2. Создаём конфигурацию
    # 3. Перезагружаем PyScript
    
    print("Деплой завершён!")


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

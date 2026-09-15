# !/usr/bin/env python3
"""
Phase 1 Fix Script - Critical bug fixes for Smart Home Platform

Usage:
    python apply_phase1_fixes.py [--dry-run] [--repo-path /path/to/repo]

What it does:
    1. Unifies entity_id format in FSMFactory (__ -> _)
    2. Adds motion_sensor to night_light behavior in manifest
    3. Integrates EventRouter into bootstrap.py
"""

import argparse
import os
import sys
import subprocess

# ============================================================
# CONFIGURATION: Exact replacement rules
# ============================================================

FIXES = {
    # Fix 1: FSMFactory entity_id format
    "src/smart_home/core/fsm_factory.py": [
        {
            "old": '        # Формат: {device_id}__{template_name}_{priority}',
            "new": '        # Формат: {device_id}_{template_name}_{priority}',
            "description": "Update comment about entity_id format",
        },
        {
            "old": '        new_entity_id = f"{device_id}__{template_name}_{behavior_priority}"',
            "new": '        new_entity_id = f"{device_id}_{template_name}_{behavior_priority}"',
            "description": "Fix entity_id format from __ to _",
        },
    ],

    # Fix 2: Manifest - add motion_sensor to night_light
    "examples/instances/leonids_house/manifest.yaml": [
        {
            "old": '        schedule: "23:00-07:00"  # Активен только ночью',
            "new": '        schedule: "23:00-07:00"  # Активен только ночью\n        motion_sensor: binary_sensor.kitchen_motion',
            "description": "Add motion_sensor to night_light behavior",
        },
    ],

    # Fix 3: Bootstrap - integrate EventRouter
    "src/smart_home/bootstrap.py": [
        # Add imports
        {
            "old": "from smart_home.core.middleware import ManualLockoutMiddleware\nfrom smart_home.core.models.manifest import Manifest, load_manifest",
            "new": "from smart_home.core.middleware import ManualLockoutMiddleware\nfrom smart_home.adapters.ha_adapter import HAAdapter\nfrom smart_home.core.event_router import EventRouter\nfrom smart_home.core.models.manifest import Manifest, load_manifest",
            "description": "Add EventRouter and HAAdapter imports",
        },
        {
            "old": "from __future__ import annotations\n\nfrom dataclasses import dataclass",
            "new": "from __future__ import annotations\n\nimport os\nfrom dataclasses import dataclass\nfrom typing import Any",
            "description": "Add os and typing imports",
        },
        # Update PlatformContext
        {
            "old": "    adapter: MockAdapter\n    dispatcher: CommandDispatcher\n\n\ndef bootstrap_platform",
            "new": "    adapter: Any  # HAAdapter or MockAdapter\n    dispatcher: CommandDispatcher\n    event_router: EventRouter\n\n\ndef bootstrap_platform",
            "description": "Add event_router to PlatformContext",
        },
        {
            "old": "        adapter: HAAdapter (MockAdapter for tests) for calling services.\n        dispatcher: CommandDispatcher with middleware chain.\n    \"\"\"",
            "new": "        adapter: HAAdapter or MockAdapter for calling services.\n        dispatcher: CommandDispatcher with middleware chain.\n        event_router: EventRouter for routing sensor events to FSMs.\n    \"\"\"",
            "description": "Update PlatformContext docstring",
        },
        # Replace MockAdapter with HAAdapter + EventRouter
        {
            "old": """    # 4. Create ControlTracker
    control_tracker = ControlTracker(history_size=100)

    # 5. Create HAAdapter (MockAdapter for tests)
    adapter = MockAdapter()

    # 6. Create CommandDispatcher with empty middleware list
    dispatcher = CommandDispatcher(ha_adapter=adapter, middlewares=[])""",
            "new": """    # 4. Create ControlTracker
    control_tracker = ControlTracker(history_size=100)

    # 5. Create EventRouter
    event_router = EventRouter(manifest=manifest, engine=fsm)

    # 6. Create HAAdapter with EventRouter
    ws_url = os.environ.get("HA_WEBSOCKET_URL", "ws://localhost:8123/api/websocket")
    ha_token = os.environ.get("HA_TOKEN")

    adapter = HAAdapter(
        mode="websocket",
        engine=fsm,
        event_router=event_router,
        ws_url=ws_url,
        token=ha_token,
    )

    # 7. Create CommandDispatcher with empty middleware list
    dispatcher = CommandDispatcher(ha_adapter=adapter, middlewares=[])""",
            "description": "Replace MockAdapter with HAAdapter + EventRouter",
        },
        # Fix step numbering
        {
            "old": "    # 7. Create ManualLockoutMiddleware with automation_rules and ControlTracker",
            "new": "    # 8. Create ManualLockoutMiddleware with automation_rules and ControlTracker",
            "description": "Fix step numbering (7 -> 8)",
        },
        {
            "old": "    # 8. Add middleware to dispatcher",
            "new": "    # 9. Add middleware to dispatcher",
            "description": "Fix step numbering (8 -> 9)",
        },
        {
            "old": "    # 9. Return PlatformContext with all components",
            "new": "    # 10. Return PlatformContext with all components",
            "description": "Fix step numbering (9 -> 10)",
        },
        # Update docstring numbering
        {
            "old": """    5. Creates HAAdapter (MockAdapter for tests)
    6. Creates CommandDispatcher with empty middleware list
    7. Creates ManualLockoutMiddleware with automation_rules and ControlTracker
    8. Adds middleware to dispatcher via add_middleware()
    9. Returns PlatformContext with all components""",
            "new": """    5. Creates EventRouter
    6. Creates HAAdapter with EventRouter
    7. Creates CommandDispatcher with empty middleware list
    8. Creates ManualLockoutMiddleware with automation_rules and ControlTracker
    9. Adds middleware to dispatcher via add_middleware()
    10. Returns PlatformContext with all components""",
            "description": "Update docstring step numbering",
        },
        # Add event_router to return
        {
            "old": "        adapter=adapter,\n        dispatcher=dispatcher,\n    )",
            "new": "        adapter=adapter,\n        dispatcher=dispatcher,\n        event_router=event_router,\n    )",
            "description": "Add event_router to PlatformContext return",
        },
    ],
}


# ============================================================
# FUNCTIONS
# ============================================================

def check_python_syntax(filepath: str) -> tuple[bool, str]:
    """Check Python file syntax."""
    if not filepath.endswith('.py'):
        return True, "Skipped (not Python)"
    result = subprocess.run(
        [sys.executable, '-m', 'py_compile', filepath],
        capture_output=True, text=True
    )
    return result.returncode == 0, result.stderr


def apply_fixes(repo_path: str, dry_run: bool = False) -> bool:
    """Apply all fixes to the repository."""
    all_success = True

    print("=" * 70)
    print("🔧 Phase 1 Fix Script")
    print("=" * 70)
    print()

    for rel_path, fixes in FIXES.items():
        filepath = os.path.join(repo_path, rel_path)

        if not os.path.exists(filepath):
            print(f"❌ Файл не найден: {rel_path}")
            all_success = False
            continue

        print(f"📄 {rel_path}")

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        file_changed = False

        for fix in fixes:
            if fix["old"] in content:
                if dry_run:
                    print(f"  🔍 [DRY-RUN] Будет заменено: {fix['description']}")
                else:
                    content = content.replace(fix["old"], fix["new"])
                    file_changed = True
                    print(f"  ✅ {fix['description']}")
            elif fix["new"] in content:
                print(f"  ⚠️  Уже применено: {fix['description']}")
            else:
                print(f"  ❌ Не найдено: {fix['description']}")
                print(f"     Ожидалось: '{fix['old'][:60]}...'")
                all_success = False

        if file_changed and not dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

        # Check syntax
        syntax_ok, syntax_msg = check_python_syntax(filepath)
        if not syntax_ok:
            print(f"  ❌ Ошибка синтаксиса: {syntax_msg}")
            all_success = False
        else:
            print(f"  ✅ Синтаксис корректен")

        print()

    return all_success


def main():
    parser = argparse.ArgumentParser(description="Apply Phase 1 critical fixes")
    parser.add_argument('--repo-path', default='.', help="Path to repository root")
    parser.add_argument('--dry-run', action='store_true', help="Preview changes without applying")
    args = parser.parse_args()

    success = apply_fixes(args.repo_path, dry_run=args.dry_run)

    print("=" * 70)
    if success:
        print("✅ Все исправления применены успешно!")
        print()
        print("📊 Следующие шаги:")
        print("  1. Запусти тесты:  pytest tests/ -v")
        print("  2. Закоммить изменения:")
        print("     git add -A")
        print("     git commit -m 'fix(phase1): resolve critical routing bugs'")
    else:
        print("❌ Некоторые исправления не были применены")
        print("   Проверь сообщения выше")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Автозамена артефактов копирования в pyscript-файлах.
Делает backup .bak перед изменением.
Использование: python3 tools/fix_artifacts.py [--apply] [--dry-run]
"""
import argparse
import os
import re
import shutil
from pathlib import Path

PYSCRIPT_DIR = Path("/config/.platform/ha/pyscript")

# Паттерны замен: (regex, replacement)
PATTERNS = [
    # Декоративные заголовки ==== -> комментарий
    (re.compile(r"^={3,}.*$"), r"# \g<0>"),
    # Сломанные ключевые слова
    (re.compile(r"\bret urn\b"), "return"),
    (re.compile(r"\bretur n\b"), "return"),
    # Пробелы внутри строковых литералов "xxx " -> "xxx"
    (re.compile(r'"([^"]*?)\s+"'), r'"\1"'),
    # Пропущенное подчеркивание в именах функций
    (re.compile(r"\blg_num\("), "_lg_num("),
    (re.compile(r"\blg_state\("), "_lg_state("),
    (re.compile(r"\blg_attr\("), "_lg_attr("),
    (re.compile(r"\blg_vlight_entity\("), "_lg_vlight_entity("),
    # Пропущенное подчеркивание в переменных
    (re.compile(r"\bVENT_BOOST_START\b"), "_VENT_BOOST_START"),
    (re.compile(r"\bVLIGHT_SYNC_GUARD\b"), "_VLIGHT_SYNC_GUARD"),
    # from future -> from __future__
    (re.compile(r"^from future\b", re.MULTILINE), "from __future__"),
    # service.call( "input_boolean ",  "turn " -> service.call("input_boolean", "turn_
    (re.compile(r'"input_boolean\s*"\s*,\s*"turn\s*"\s*\+\s*want'),
     r'"input_boolean", "turn_" + want'),
]

def fix_file(path: Path, apply: bool) -> list:
    original = path.read_text(encoding="utf-8")
    text = original
    changes = []
    
    for pattern, replacement in PATTERNS:
        new_text, n = pattern.subn(replacement, text)
        if n > 0:
            changes.append(f"  - {pattern.pattern!r} -> {replacement!r} ({n} раз)")
            text = new_text
    
    if not changes:
        return []
    
    if apply:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")
        return [f"✅ {path.name} (backup: {backup.name})"] + changes
    else:
        return [f"🔍 {path.name} (dry-run)"] + changes

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Применить изменения")
    p.add_argument("--dir", default=str(PYSCRIPT_DIR))
    args = p.parse_args()
    
    root = Path(args.dir)
    if not root.exists():
        print(f"❌ Директория не найдена: {root}")
        return
    
    files = sorted(root.glob("*.py"))
    print(f"📁 Найдено .py файлов: {len(files)}")
    print(f"🎯 Режим: {'APPLY' if args.apply else 'DRY-RUN'}\n")
    
    total_changes = 0
    for f in files:
        changes = fix_file(f, args.apply)
        if changes:
            for line in changes:
                print(line)
            print()
            total_changes += 1
    
    print("=" * 50)
    print(f"Изменено файлов: {total_changes}/{len(files)}")
    if not args.apply and total_changes > 0:
        print("\n💡 Запусти с --apply чтобы применить изменения")

if __name__ == "__main__":
    main()
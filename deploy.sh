#!/bin/bash
# Склеить pyscript файлы в один manifest_loader.py
set -e

SRC_DIR="/config/.platform/ha/pyscript"
OUT="/config/pyscript/manifest_loader.py"

echo "Склейка pyscript файлов..."

cat > "$OUT" << 'EOF'
# AUTO-GENERATED — не редактировать вручную
# Source: .platform/ha/pyscript/*.py
# Generated: $(date)
EOF

for f in "$SRC_DIR"/*.py; do
    echo "# === $(basename "$f") ===" >> "$OUT"
    cat "$f" >> "$OUT"
    echo "" >> "$OUT"
done

echo "Сгенерирован: $OUT ($(wc -l < "$OUT") строк)"

# Проверка синтаксиса
python3 -m py_compile "$OUT" && echo "SYNTAX OK" || { echo "SYNTAX ERROR"; exit 1; }

# Перезагрузка pyscript
echo "Перезагрузка pyscript..."
# curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" ... (если нужен REST API)

echo "Готово"
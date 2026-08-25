#!/bin/bash
# Генерация всех дашбордов по порядку
set -e
MANIFEST="${1:-instances/leonid_house/manifest.yaml}"
echo "=== Генерация дашбордов из $MANIFEST ==="
python3 tools/gen_dashboard_home.py --manifest "$MANIFEST"
python3 tools/gen_dashboard_settings.py --manifest "$MANIFEST"
python3 tools/gen_dashboard_admin.py --manifest "$MANIFEST"
echo "=== Готово ==="

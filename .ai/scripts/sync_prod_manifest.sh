#!/usr/bin/env bash
#
#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
#
# Синхронизация эталона манифеста с боевым (правило владельца 2026-10-14).
#
# Боевой манифест живёт в томе и в git не хранится (deploy/docker/config под
# .gitignore). Эталон в git — instances/leonids_house_prod/manifest.yaml; из него
# засевается пустой том при развёртывании. Если их не синхронизировать, при
# развёртывании на пустом томе поднимается старая конфигурация, а правки из
# интерфейса в git не попадают (BACKLOG B46).
#
# Поэтому правило: после каждой правки боевого манифеста (в том числе через
# веб-интерфейс) эталон приводится к боевому — этой командой.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

LIVE="deploy/docker/config/manifest.yaml"
REF="instances/leonids_house_prod/manifest.yaml"

if [[ ! -f "$LIVE" ]]; then
    echo "❌ Боевой манифест не найден: $LIVE"
    echo "   Синхронизировать нечего. На этой машине нет боевого тома?"
    exit 1
fi

if [[ ! -f "$REF" ]]; then
    echo "❌ Эталон не найден: $REF"
    exit 1
fi

if cmp -s "$LIVE" "$REF"; then
    echo "✅ Эталон уже совпадает с боевым манифестом"
    exit 0
fi

cp "$LIVE" "$REF"
echo "🔄 Эталон обновлён: $REF"
echo "   Изменения (нужно закоммитить):"
git diff --stat -- "$REF" | sed 's/^/   /'

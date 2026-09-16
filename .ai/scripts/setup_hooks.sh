#!/usr/bin/env bash
#
#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
#

# Однократный вызов: подключает .githooks/ как hooks-директорию
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"

git config core.hooksPath .githooks
chmod +x "$ROOT/.githooks/pre-commit"
chmod +x "$ROOT/.ai/scripts/run_checks.sh" 2>/dev/null || true

echo "✓ Git hooks активированы (core.hooksPath = .githooks)"

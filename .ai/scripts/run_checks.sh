#!/bin/bash
#
#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
#

# =============================================================================
# Quality checks script for Smart Home Platform
# =============================================================================
#
# 🤖 AI INSTRUCTIONS:
# Запускай этот скрипт ПОСЛЕ каждого изменения кода ПЕРЕД коммитом:
#
#     ./.ai/scripts/run_checks.sh
#
# Если скрипт завершается с ошибкой (exit code 1) — НЕ КОММИТЬ!
# Сначала исправь все проблемы, которые он показывает.
#
# Для авто-исправления форматирования и импортов:
#     ruff check --fix src/ tests/
#     ruff format src/ tests/
#
# ⛔ ЗАПРЕЩЕНО ИЗМЕНЯТЬ .gitignore:
# Этот файл управляется централизованно через шаблон.
# Если ты случайно изменил .gitignore — восстанови его командой:
#     cp .ai/templates/qwen.gitignore.fix .gitignore
#     git add .gitignore
#
# =============================================================================

set -e  # Exit on first error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "=================================="
echo "🏠 Smart Home Platform Quality Checks"
echo "=================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

FAILED=0

info()  { echo -e "${GREEN}[pre-commit]${NC} $*"; }
warn()  { echo -e "${YELLOW}[pre-commit]${NC} $*"; }
fail()  { echo -e "${RED}[pre-commit]${NC} $*"; exit 1; }


# Check all required tools first
echo "0️⃣  Проверка наличия инструментов..."
MISSING_TOOLS=()

REQUIRED_TOOLS=("pytest" "mypy" "ruff" "interrogate" "pre-commit")

for tool in "${REQUIRED_TOOLS[@]}"; do
    if ! command -v "$tool" &> /dev/null; then
        MISSING_TOOLS+=("$tool")
    fi
done

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo -e "${RED}❌ Отсутствуют инструменты: ${MISSING_TOOLS[*]}${NC}"
    echo ""
    echo -e "${BLUE}Установи все зависимости одной командой:${NC}"
    echo ""
    echo "    pip install -e \".[dev]\""
    echo ""
    exit 1
fi

echo -e "${GREEN}✅ Все инструменты установлены${NC}"
echo ""

# ──────────────────────────────────────────────
# 0. Проверка: .gitignore не был изменён
# ──────────────────────────────────────────────
GITIGNORE_FIX="$ROOT/.ai/templates/qwen.gitignore.fix"

if [[ -f "$GITIGNORE_FIX" ]]; then
    if ! diff -q "$GITIGNORE_FIX" "$ROOT/.gitignore" >/dev/null 2>&1; then
        fail ".gitignore был изменён! Это запрещено.

⛔ Восстанови .gitignore из шаблона:
   cp .ai/templates/qwen.gitignore.fix .gitignore
   git add .gitignore

Затем запусти проверки снова."
    fi
else
    warn "qwen.gitignore.fix не найден — пропускаю проверку .gitignore"
fi

echo -e "${GREEN}✅ .gitignore не изменён${NC}"
echo ""
#
## 1. Tests
#
# Блок был закомментирован с 2026-09-21 (36c710f "fix: disable pre-push tests"),
# при том что .githooks/pre-push вызывает только этот скрипт и подписан
# «тесты + линтер + покрытие». Скрипт завершался с кодом 0, не выполнив ни
# одного теста (спека 009, US3).
#
# Состав набора задаётся в pyproject.toml; здесь он не переопределяется.
# Браузерные тесты (tests/test_webui_playwright.py, 25 шт.) исключены из общего
# прогона — playwright sync API держит running event loop и ломает
# последующие async-тесты (Known Issue #13). Это объявленное исключение:
# запускается отдельной командой `make test-browser`.
echo "1️⃣  Running tests..."
# Вывод сохраняется во временный файл, а код возврата pytest проверяется
# отдельно: в конвейере `pytest | tail` статус берётся от последней команды,
# то есть от `tail`, который завершается успехом всегда. С таким видом падение
# тестов печатало FAILED и рапортовало «Tests passed» с кодом 0.
TEST_OUTPUT="$(mktemp)"
if pytest -q --no-cov -p no:cacheprovider > "$TEST_OUTPUT" 2>&1; then
    tail -3 "$TEST_OUTPUT"
    echo -e "${GREEN}✅ Tests passed${NC}"
else
    tail -30 "$TEST_OUTPUT"
    echo -e "${RED}❌ Tests failed${NC}"
    FAILED=1
fi
rm -f "$TEST_OUTPUT"
echo ""

echo "1️⃣b Browser tests (declared exclusion — run separately, see note)"
echo -e "${BLUE}   Not part of this run: tests/test_webui_playwright.py${NC}"
echo -e "${BLUE}   Reason: playwright sync API holds a running event loop (Known Issue #13)${NC}"
echo -e "${BLUE}   Run with: make test-browser${NC}"
echo ""

# 2. Type checking
echo "2️⃣  Type checking..."
# Команда обязана совпадать с Makefile (`type-check`) и CI (`ci.yml`) — это
# `mypy src/`, который читает pyproject.toml (там strict = true).
#
# Раньше здесь стояло `mypy src/ --strict --ignore-missing-imports`, и это был
# ложный зелёный свет: --ignore-missing-imports превращает ненайденный импорт
# в тишину, а модуль без типов становится Any — вместе с ним исчезают и любые
# обращения к его атрибутам. Проверено инъекцией файла с несуществующим
# импортом: с флагом «Success: no issues found», без него — «Found 1 error».
# То есть скрипт мог отметить успехом код, который CI отвергнет. С этим же
# флагом молча проходила бы и нехватка зависимости в образе — см. Known Issue
# про отсутствующий `cryptography`.
if mypy src/ 2>&1; then
    echo -e "${GREEN}✅ Type checking passed${NC}"
else
    echo -e "${RED}❌ Type checking failed${NC}"
    FAILED=1
fi
echo ""

# 3. Linting & formatting with Ruff
echo "3️⃣  Linting (ruff check)..."
if ruff check src/ tests/ 2>&1; then
    echo -e "${GREEN}✅ Linting passed${NC}"
else
    echo -e "${YELLOW}⚠️  Linting issues found${NC}"
    echo -e "${BLUE}   Исправь автоматически: ruff check --fix src/ tests/${NC}"
    FAILED=1
fi
echo ""

# 4. Formatting with Ruff
echo "4️⃣  Formatting (ruff format)..."
if ruff format --check src/ tests/ 2>&1; then
    echo -e "${GREEN}✅ Formatting passed${NC}"
else
    echo -e "${YELLOW}⚠️  Formatting issues found${NC}"
    echo -e "${BLUE}   Исправь автоматически: ruff format src/ tests/${NC}"
    FAILED=1
fi
echo ""

# 4. Pre commit check
echo "4️⃣  Pre-commit checking..."
if pre-commit run --all-files 2>&1; then
    echo -e "${GREEN}✅ Pre-commit check passed${NC}"
else
    echo -e "${YELLOW}⚠️  Pre-commit check issues found${NC}"
    echo -e "${BLUE}   Исправь перед комитом"
    FAILED=1
fi
echo ""

# 5. Documentation coverage
echo "5️⃣  Documentation coverage..."
if interrogate src/ -vv 2>&1; then
    echo -e "${GREEN}✅ Documentation coverage OK${NC}"
else
    echo -e "${YELLOW}⚠️  Missing docstrings${NC}"
    echo -e "${BLUE}   Добавь docstrings к публичным функциям и классам${NC}"
fi
echo ""

# ──────────────────────────────────────────────
# 6. Финальная проверка: .gitignore не в staged
# ──────────────────────────────────────────────
if git diff --cached --name-only | grep -q '^\.gitignore$'; then
    fail ".gitignore находится в staged (готов к коммиту)! Это запрещено.

⛔ Убери .gitignore из индекса:
   git restore --staged .gitignore

Или восстанови шаблон, если ты его менял:
   cp .ai/templates/qwen.gitignore.fix .gitignore
   git restore --staged .gitignore
"
fi

echo ""

echo "=================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
    echo "✅ Можно коммитить изменения."
    exit 0
else
    echo -e "${RED}❌ Some checks failed. Fix before committing.${NC}"
    echo ""
    echo -e "${YELLOW}💡 Quick fix commands:${NC}"
    echo "   ruff check --fix src/ tests/     # Исправить линтинг"
    echo "   ruff format src/ tests/          # Исправить форматирование"
    echo ""
    exit 1
fi

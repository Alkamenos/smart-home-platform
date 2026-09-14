#!/bin/bash
# Quality checks script for Smart Home Platform
# Run after every significant change

set -e  # Exit on first error

echo "=================================="
echo "🏥 Smart Home Platform Quality Checks"
echo "=================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

FAILED=0

# Function to check if command exists
check_command() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${RED}❌ '$1' не установлен!${NC}"
        echo -e "${BLUE}   Установи: pip install -e \".[dev]\"${NC}"
        echo ""
        exit 1
    fi
}

# Check all required tools first
echo "0️⃣  Проверка наличия инструментов..."
MISSING_TOOLS=()

for tool in pytest mypy ruff black isort interrogate; do
    if ! command -v $tool &> /dev/null; then
        MISSING_TOOLS+=($tool)
    fi
done

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo -e "${RED}❌ Отсутствуют инструменты: ${MISSING_TOOLS[*]}${NC}"
    echo ""
    echo -e "${BLUE}Установи все зависимости одной командой:${NC}"
    echo ""
    echo "    pip install -e \".[dev]\""
    echo ""
    echo -e "${YELLOW}Или установи только нужные инструменты:${NC}"
    echo ""
    echo "    pip install mypy ruff black isort interrogate"
    echo ""
    exit 1
fi

echo -e "${GREEN}✅ Все инструменты установлены${NC}"
echo ""

echo "1️⃣  Running tests..."
if pytest tests/ -v --cov=src --cov-report=term-missing --cov-fail-under=80 2>&1; then
    echo -e "${GREEN}✅ Tests passed${NC}"
else
    echo -e "${RED}❌ Tests failed${NC}"
    FAILED=1
fi
echo ""

echo "2️⃣  Type checking..."
if mypy src/ --strict --ignore-missing-imports 2>&1; then
    echo -e "${GREEN}✅ Type checking passed${NC}"
else
    echo -e "${RED}❌ Type checking failed${NC}"
    FAILED=1
fi
echo ""

echo "3️⃣  Linting..."
if ruff check src/ tests/ 2>&1; then
    echo -e "${GREEN}✅ Linting passed${NC}"
else
    echo -e "${YELLOW}⚠️  Linting warnings${NC}"
    echo -e "${BLUE}   Исправь: ruff check --fix src/ tests/${NC}"
fi
echo ""

echo "4️⃣  Formatting check..."
if black --check src/ tests/ 2>&1; then
    echo -e "${GREEN}✅ Formatting OK${NC}"
else
    echo -e "${YELLOW}⚠️  Formatting issues${NC}"
    echo -e "${BLUE}   Исправь: black src/ tests/${NC}"
fi
echo ""

echo "5️⃣  Import sorting..."
if isort --check-only src/ tests/ 2>&1; then
    echo -e "${GREEN}✅ Import sorting OK${NC}"
else
    echo -e "${YELLOW}⚠️  Import sorting issues${NC}"
    echo -e "${BLUE}   Исправь: isort src/ tests/${NC}"
fi
echo ""

echo "6️⃣  Documentation coverage..."
if interrogate src/ -vv 2>&1; then
    echo -e "${GREEN}✅ Documentation coverage OK${NC}"
else
    echo -e "${YELLOW}⚠️  Missing docstrings${NC}"
    echo -e "${BLUE}   Добавь docstrings к публичным функциям${NC}"
fi
echo ""

echo "=================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All critical checks passed!${NC}"
    echo "Можно коммитить изменения."
    exit 0
else
    echo -e "${RED}❌ Some checks failed. Fix before committing.${NC}"
    exit 1
fi

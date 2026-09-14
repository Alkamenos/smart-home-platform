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
NC='\033[0m' # No Color

FAILED=0

echo "1️⃣  Running tests..."
if pytest tests/ -v --cov=src --cov-report=term-missing --cov-fail-under=80; then
    echo -e "${GREEN}✅ Tests passed${NC}"
else
    echo -e "${RED}❌ Tests failed${NC}"
    FAILED=1
fi
echo ""

echo "2️⃣  Type checking..."
if mypy src/ --strict; then
    echo -e "${GREEN}✅ Type checking passed${NC}"
else
    echo -e "${RED}❌ Type checking failed${NC}"
    FAILED=1
fi
echo ""

echo "3️⃣  Linting..."
if ruff check src/ tests/; then
    echo -e "${GREEN}✅ Linting passed${NC}"
else
    echo -e "${YELLOW}⚠️  Linting warnings (fix if possible)${NC}"
fi
echo ""

echo "4️⃣  Formatting check..."
if black --check src/ tests/; then
    echo -e "${GREEN}✅ Formatting OK${NC}"
else
    echo -e "${YELLOW}⚠️  Formatting issues (run 'black src/ tests/' to fix)${NC}"
fi
echo ""

echo "5️⃣  Import sorting..."
if isort --check-only src/ tests/; then
    echo -e "${GREEN}✅ Import sorting OK${NC}"
else
    echo -e "${YELLOW}⚠️  Import sorting issues (run 'isort src/ tests/' to fix)${NC}"
fi
echo ""

echo "6️⃣  Documentation coverage..."
if interrogate src/ -vv; then
    echo -e "${GREEN}✅ Documentation coverage OK${NC}"
else
    echo -e "${YELLOW}⚠️  Missing docstrings (add to public functions)${NC}"
fi
echo ""

echo "=================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All critical checks passed!${NC}"
    echo "You can commit your changes."
else
    echo -e "${RED}❌ Some checks failed. Fix before committing.${NC}"
    exit 1
fi

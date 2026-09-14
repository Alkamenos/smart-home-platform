#!/bin/bash
# Run mock server for Smart Home FSM Platform

set -e

echo "🚀 Starting Mock Server..."

# Default port
PORT=${1:-8080}

# Activate virtual environment if exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run mock adapter
python -c "
from smart_home.adapters.mock_adapter import MockAdapter
import asyncio

async def run_mock():
    adapter = MockAdapter()
    print(f'Mock server running on port ${PORT}')
    await adapter.start_server(host='0.0.0.0', port=${PORT})

asyncio.run(run_mock())
"

echo "✅ Mock server stopped"

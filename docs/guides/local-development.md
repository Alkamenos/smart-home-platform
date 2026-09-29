# 🛠 Local Development

## Prerequisites

```bash
# Install Python 3.10+
python --version  # Should be 3.10 or higher

# Install dependencies
pip install -e ".[dev]"
```

## Running Tests

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_fsm.py -v

# Run tests with live reload (using pytest-watch)
ptw --runner "pytest -x"

# Run tests with freezegun for time-based tests
pytest tests/test_scheduler.py -v  # freezegun is auto-loaded in tests
```

## Example Test with Freezegun

```python
from freezegun import freeze_time
import pytest


@pytest.mark.asyncio
@freeze_time("2024-01-15 10:30:00")
async def test_timeout_transition():
    """Test that timeout transitions occur at the right time."""
    engine = FSMEngine()
    # ... setup FSM ...

    # Trigger initial state
    await engine.trigger("sensor_1", "motion_detected")

    # Fast-forward time by 5 minutes
    with freeze_time("2024-01-15 10:35:00"):
        # Timeout should have fired
        state = engine.get_state("sensor_1")
        assert state.current_state == "timeout_pending"
```

## Linting and Code Quality

```bash
# Run linter (ruff)
make lint

# Type checking with mypy
mypy src/

# Format code
ruff format src/ tests/

# Run all project checks (required before every commit)
.ai/scripts/run_checks.sh
```

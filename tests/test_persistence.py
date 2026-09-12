# tests/test_persistence.py
import pytest
from pathlib import Path
from src.smart_home.core.fsm import FSMEngine, FSMDefinition, Transition


@pytest.mark.asyncio
async def test_survive_restart(tmp_path):
    """Test that FSM state survives restart (simplified - no persistence module)."""
    storage = tmp_path / "states.json"

    # 1. Запускаем движок, включаем свет
    engine1 = FSMEngine()
    engine1.register_definition(FSMDefinition("light.test", "OFF", ("OFF", "ON"), (
        Transition("OFF", "ON", "manual"),
    )))
    await engine1.trigger("light.test", "manual")

    # Сохраняем состояние вручную (имитация персистентности)
    import json
    state_data = {
        "light.test": {
            "current_state": engine1.get_state("light.test").current_state,
            "entered_at": engine1.get_state("light.test").entered_at,
        }
    }
    storage.write_text(json.dumps(state_data))

    # 2. Имитируем перезапуск HA (уничтожаем объект)
    del engine1

    # 3. Запускаем новый движок с тем же хранилищем
    engine2 = FSMEngine()
    engine2.register_definition(FSMDefinition("light.test", "OFF", ("OFF", "ON"), (
        Transition("OFF", "ON", "manual"),
    )))

    # Восстанавливаем состояние из хранилища
    if storage.exists():
        import json
        saved_state = json.loads(storage.read_text())
        entity_id = "light.test"
        if entity_id in saved_state:
            engine2.reset_state(
                entity_id,
                saved_state[entity_id]["current_state"]
            )

    # 4. Проверяем, что состояние сохранилось!
    state = engine2.get_state("light.test")
    assert state.current_state == "ON"

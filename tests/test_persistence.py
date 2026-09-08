# tests/test_persistence.py
import pytest
from pathlib import Path
from smart_home.core.fsm import FSMEngine, FSMDefinition, Transition, FSMPersistence


@pytest.mark.asyncio
async def test_survive_restart(tmp_path):
    storage = tmp_path / "states.json"

    # 1. Запускаем движок, включаем свет
    engine1 = FSMEngine(persistence=FSMPersistence(storage))
    engine1.register_definition(FSMDefinition("light.test", "OFF", ("OFF", "ON"), (
        Transition("OFF", "ON", "manual", timeout_sec=60),
    )))
    await engine1.trigger("light.test", "manual")

    # 2. Имитируем перезапуск HA (уничтожаем объект)
    del engine1

    # 3. Запускаем новый движок с тем же хранилищем
    engine2 = FSMEngine(persistence=FSMPersistence(storage))
    engine2.register_definition(FSMDefinition("light.test", "OFF", ("OFF", "ON"), (
        Transition("OFF", "ON", "manual", timeout_sec=60),
    )))

    # 4. Проверяем, что состояние сохранилось!
    state = engine2.get_state("light.test")
    assert state.current_state == "ON"
    # И таймер можно запланировать заново, зная entered_at

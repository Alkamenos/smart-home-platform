"""Генератор src/features/CONTRACT.yaml из кода. Запуск: python /tmp/gen_contract.py"""

import json
import pathlib
import sys
from typing import Any

import yaml

from core.action_handlers import register_all_actions
from core.events.event_router import EventRouter
from core.guards.builtin import REGISTERED_GUARDS
from core.registry import Registry


NO = "НЕТ ПРОИСХОДИТЕЛЯ"

CONTRACT_PATH = pathlib.Path("src/features/CONTRACT.yaml")


def _existing_params() -> dict[str, dict[str, Any]]:
    """Читает объявления параметров из текущего контракта.

    Параметры вносятся вручную: у них нет первоисточника в коде, который
    генератор умеет обходить. Раньше генератор их просто не выводил, и любой
    запуск «освежал» контракт удалением всех объявлений — форма правки
    теряла поля (Known Issue #72).

    Args:
        None.

    Returns:
        Словарь ``имя шаблона`` → описания параметров.
    """
    if not CONTRACT_PATH.exists():
        return {}
    current = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8")) or {}
    found: dict[str, dict[str, Any]] = {}
    for name, spec in (current.get("templates") or {}).items():
        params = (spec or {}).get("params")
        if params:
            found[name] = params
    return found


def _yaml_str(value: Any) -> str:
    """Оформляет значение как строку YAML в двойных кавычках.

    Args:
        value: Значение.

    Returns:
        Строковый литерал YAML. JSON-экранирование совместимо с YAML: оба
        используют одинаковые обозначения управляющих последовательностей.
    """
    return json.dumps(str(value), ensure_ascii=False)


GAPS = {
    "lighting": [
        "motion_cleared публикуется платформой, но перехода по нему нет — "
        "движение кончилось, свет горит до таймаута. Это сценарий «свет с "
        "задержкой», а не дефект; отдельная задача на выбор поведения.",
        "manual_switch_on и manual_switch_off нигде не порождаются. Ручной путь "
        "управления устройством в платформе отсутствует как класс (пункт 3 "
        "веб-плана), поэтому и manual_override не имеет источника.",
    ],
    "night_light": [
        "schedule_end не порождается — расписание не выключает ночной свет.",
        "У состояния ON_NIGHT нет guard'а на ночь, поэтому оно достижимо и "
        "днём через motion_detected.",
    ],
    "climate_control": [
        "Платформа публикует temperature_changed, шаблон слушает "
        "temperature_low, temperature_high и temperature_reached — имена не "
        "совпадают, событие не приходит никогда.",
        "У переходов нет guard'ов и порогов. Даже после исправления имён любое "
        "изменение температуры включало бы обогрев, а возврат к норме "
        "выключал бы. Порог должен стать параметром поведения.",
    ],
    "humidity_ventilation": [
        "Имя guard'а содержит 60, хотя значение порога берётся из параметра "
        "поведения humidity_threshold. Расхождение осталось только в имени: на "
        "решение оно не влияет (движок кладёт параметры поведения в контекст "
        "условия), но читающий контракт видит «60» и считает порог зашитым.",
    ],
    "generic_cover": [
        "Ни одного из семи действий в реестре нет — шаблон неисполним целиком. "
        "Вне объёма варианта (a).",
    ],
    "generic_switch": [
        "Все три действия в реестре отсутствуют — шаблон неисполним целиком. "
        "Вне объёма варианта (a).",
    ],
    "smart_lock": [
        "Ни одного из шести действий в реестре нет — шаблон неисполним целиком. "
        "Для замков осознанно не сделано: удалённой отпирающей команде не "
        "доверяем.",
    ],
    "speed_control": [
        "Ни одного из пяти действий в реестре нет — шаблон неисполним целиком. "
        "Вне объёма варианта (a).",
    ],
}
IN_MANIFEST = {
    "lighting": ["kitchen", "living_room", "bedroom", "bathroom"],
    "night_light": ["kitchen", "living_room", "bedroom", "bathroom"],
    "climate_control": ["kitchen", "living_room"],
    "humidity_ventilation": ["bathroom"],
    "generic_cover": [],
    "generic_switch": [],
    "smart_lock": [],
    "speed_control": [],
}
HEADER = """# Контракт шаблонов поведения
#
# Файл сгенерирован: правьте шаблоны и реестр, затем перегенерируйте, иначе
# tests/contract/test_template_contract.py упадёт. Разделы `gaps` заполняются
# руками — они не выводятся из кода.
#
# Зачем он нужен: платформа публикует события датчиков, но из них шаблоны
# слушают единицы, а триггеры шаблонов порождаются ещё реже. По этой таблице
# веб-интерфейс должен строить форму поведения из того, что платформа правда
# выполнит, и не предлагать пользователю недостижимого.
"""


def uniq(items):
    out = []
    for x in items:
        if x and x not in out:
            out.append(x)
    return out


registry = Registry()
register_all_actions(registry)
registered = sorted(registry.list_actions())
router_events = {e for evs in EventRouter.SENSOR_EVENT_MAP.values() for e in evs}

lines = [HEADER, "sensor_events:"]
for k, v in EventRouter.SENSOR_EVENT_MAP.items():
    lines.append(f"  {k}: [{', '.join(v)}]")
lines += [
    "",
    "engine_events:",
    "  # События, которые порождает сам движок, а не внешний источник.",
    "  timeout: таймер взводится по исходящим переходам состояния с триггером timeout.",
    "",
    "registered_actions:  # реестр после register_all_actions",
]
lines += [f"  - {a}" for a in registered]
lines += ["", "registered_guards:  # реестр после register_all_guards"]
lines += [f"  - {g}" for g in sorted(REGISTERED_GUARDS)]

listened: set[str] = set()
for path in sorted(pathlib.Path("src/features").glob("*.yaml")):
    if path.stem == "CONTRACT":
        continue
    tpl = yaml.safe_load(path.read_text(encoding="utf-8"))
    listened.update(uniq([t.get("trigger") for t in (tpl.get("transitions") or [])]))
uncovered = sorted(router_events - listened)
lines += [
    "",
    "uncovered_platform_events:",
    "  # События, которые платформа публикует, но ни один шаблон не слушает.",
]
lines += [f"  - {e}" for e in uncovered]
lines += ["", "templates:"]

existing = _existing_params()

for path in sorted(pathlib.Path("src/features").glob("*.yaml")):
    name = path.stem
    if name == "CONTRACT":
        continue
    tpl = yaml.safe_load(path.read_text(encoding="utf-8"))
    acts = uniq([t.get("action") for t in tpl.get("transitions", [])])
    guards = uniq([t.get("guard") for t in tpl.get("transitions", [])])
    trigs = uniq([t.get("trigger") for t in tpl.get("transitions", [])])
    reachable = all(a in registered for a in acts) and bool(acts)
    lines.append(f"  {name}:")
    lines.append(f"    reachable: {str(reachable).lower()}")
    rooms = IN_MANIFEST.get(name, [])
    lines.append(f"    in_manifest: [{', '.join(rooms)}]")
    lines.append(f"    actions: [{', '.join(acts)}]")
    lines.append(f"    guards: [{', '.join(guards)}]")
    lines.append("    triggers:")
    unproduced = []
    for trig in trigs:
        if trig in router_events:
            src = "sensor"
        elif trig == "timeout":
            src = "engine"
        else:
            src = NO
            unproduced.append(trig)
        lines.append(f"      {trig}: {src}")
    lines.append(f"    unproduced_triggers: [{', '.join(unproduced)}]")
    lines.append("    gaps:")
    for gap in GAPS.get(name, []):
        lines.append(f"      - {gap}")
    # Объявления параметров переносятся из текущего контракта, а не
    # придумываются здесь: их пишет человек, и потерять их молча нельзя.
    if existing.get(name):
        lines.append("    params:")
        for param_name, spec in existing[name].items():
            spec = spec or {}
            lines.append(f"      {param_name}:")
            lines.append(f"        type: {spec.get('type', 'int')}")
            lines.append(f"        range: {_yaml_str(spec.get('range', ''))}")
            lines.append(f"        effective: {str(bool(spec.get('effective'))).lower()}")
            lines.append(f"        note: {_yaml_str(spec.get('note', ''))}")

# Путь вывода можно задать аргументом: иначе проверка, что регенерация ничего
# не теряет, вынуждена была бы переписывать файл в дереве.
target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else CONTRACT_PATH
target.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"записано: {target}")
print("сгенерировано, строк:", len(lines))

"""Генератор src/features/CONTRACT.yaml из кода.

Запуск: ``python tools/gen_template_contract.py`` — перезаписать контракт;
``python tools/gen_template_contract.py --check`` — только проверить, что файл
совпадает с кодом (код возврата 1, если устарел). Проверка ничего не пишет: так
её можно ставить в CI и не бояться, что она затрёт ручные правки.
"""

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
PLATFORM = "platform"

#: События, которые порождает сама платформа, а не датчик и не движок. Смену
#: глобального переключателя вентиляции (выключатель владельца, фиче-флаг, сезон,
#: проветривание, вытяжка) шлёт HAAdapter через EventRouter.route_settings_change:
#: автомат вентиляции ждёт показания датчика, и решение владельца без этого
#: события не доходило бы до него.
PLATFORM_EVENTS: dict[str, str] = {
    "settings_changed": (
        "смена глобального переключателя вентиляции; шлёт HAAdapter через "
        "EventRouter.route_settings_change"
    ),
    "device_state_diverged": (
        "прибор разошёлся с решением; шлёт сторож платформы "
        "(services/watchdog.py, DEVICE_DIVERGED_TRIGGER)"
    ),
    "sleep_started": "модификатор «мы спим» включился; шлёт контейнер (modifier events)",
    "sunset_started": "солнце ушло за горизонт; шлёт контейнер по состоянию sun.sun",
    "sunrise_started": "солнце взошло; шлёт контейнер по состоянию sun.sun",
    "day_started": "начался день по утреннему времени дома; шлёт дневной цикл",
    "quiet_hours_started": "начались тихие часы по времени дома; шлёт дневной цикл",
    "manual_switch_on": (
        "человек включил прибор; шлёт HAAdapter через _route_manual_event "
        "(приложение и автоматизация/кнопка, B94) и интерфейс платформы "
        "(_MANUAL_FSM_EVENTS)"
    ),
    "manual_switch_off": (
        "человек выключил прибор; шлёт HAAdapter через _route_manual_event и "
        "интерфейс платформы (_MANUAL_FSM_EVENTS)"
    ),
}

#: Эталонный манифест дома: по нему считается, где какой шаблон используется.
MANIFEST_PATH = pathlib.Path("instances/leonids_house_prod/manifest.yaml")


def _instantiated_places() -> dict[str, list[str]]:
    """Шаблон → места манифеста, где он используется приборами.

    Раньше список мест был зашит в генератор (`kitchen`, `living_room`, …) и
    разошёлся с домом: контракт утверждал, что шаблон работает в комнате,
    которой нет. Теперь он считается по поведениям приборов манифеста.

    Returns:
        Словарь ``имя шаблона`` → отсортированные идентификаторы мест.
    """
    if not MANIFEST_PATH.exists():
        return {}
    from core.models.manifest import load_manifest

    manifest = load_manifest(str(MANIFEST_PATH))
    found: dict[str, list[str]] = {}
    for place in manifest.all_places:
        for device in getattr(place, "devices", []) or []:
            for behavior in device.behaviors:
                found.setdefault(behavior.template, []).append(place.id)
    return {name: sorted(set(ids)) for name, ids in found.items()}


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
    "deco_light": [
        "События заката и рассвета порождает адаптер по состоянию sun.sun, а не "
        "роутер: солнце не входит в манифест и в подписку, поэтому в карте "
        "SENSOR_EVENT_MAP его нет. Шаблон слушает то, чего роутер не публикует, "
        "и это нормально ровно до тех пор, пока события доставляет контейнер.",
        "Включение по датчику освещённости не сделано: датчик сломан и ждёт "
        "замены (B31). Солнце уходит, а в доме ещё светло — при замене датчика "
        "для вечернего света это разные триггеры, и подменять один другим нельзя.",
    ],
    "lighting": [
        "motion_cleared публикуется платформой, но перехода по нему нет — "
        "движение кончилось, свет горит до таймаута. Это сценарий «свет с "
        "задержкой», а не дефект; отдельная задача на выбор поведения.",
        "manual_switch_on и manual_switch_off доставляют HAAdapter "
        "(_route_manual_event: действие из приложения и автоматизация или кнопка, "
        "B94) и интерфейс платформы (_MANUAL_FSM_EVENTS). manual_override "
        "объявлен, но источника в проде не имеет.",
        "device_state_diverged порождает сторож платформы: он читает фактическое "
        "состояние прибора и, если оно противоречит решению, автомат повторяет "
        "решение.",
    ],
    "night_light": [
        "schedule_end не порождается — расписание не выключает ночной свет.",
        "У состояния ON_NIGHT нет guard'а на ночь, поэтому оно достижимо и "
        "днём через motion_detected.",
    ],
    "climate_control": [
        "Условие «греть» составное (may_heat), потому что движок допускает на "
        "переход ровно одно имя guard'а: перечислить проверки по отдельности "
        "шаблон не может, и менять это — значит менять структуру FSMDefinition "
        "(конституция I — только по явному согласованию).",
        "Целевая температура берётся из automation_rules.climate.setpoint_entity, "
        "а не из параметра target_temp шаблона: уставку ведёт Home Assistant, и "
        "вторая копия числа разошлась бы с первой (FR-001 спеки 011).",
    ],
    "humidity_ventilation": [
        "Имя guard'а содержит 60, хотя значение порога берётся из параметра "
        "поведения humidity_threshold. Расхождение осталось только в имени: на "
        "решение оно не влияет (движок кладёт параметры поведения в контекст "
        "условия), но читающий контракт видит «60» и считает порог зашитым.",
    ],
    "ventilation_modes": [
        "Один шаблон обслуживает и рекуператор, и вытяжку: роль устройства "
        "задаётся параметром ventilation_role. Разделить их отдельными "
        "шаблонами значило бы дублировать условие остановки и таймеры; движок "
        "допускает на переход ровно одно имя guard'а (конституция I).",
        "Ночью скорость равна минимуму (speed_min), а не режим: отдельного "
        "ночного режима нет, и параметры mode_night/mode_exhaust из "
        "data-model.md §5 удалены как не имеющие силы (вытяжка — отдельный "
        "прибор без режимов).",
        "Приток по дельте «комната − улица» отменён (уточнение владельца "
        "2026-10-12, research.md D22): остаются только «Рекуперация» и «Приток "
        "MAX» при жаре выше потолка комфорта. Параметры mode_supply, "
        "supply_delta_threshold, speed_delta_gain, speed_night_max и "
        "delta_deadband удалены как инертные.",
    ],
    "cover_modes": [
        "Позицию прибора платформа не отслеживает: она просит открыть или "
        "закрыть, а состояние шторы в Home Assistant не читает. Поэтому в CLOSED "
        "автомат уверен по собственной команде, а не по прибору; ручное движение "
        "человеком автоматику не отменяет (ручного пути в платформе пока нет — "
        "тот же пробел, что и у света).",
        "Решение принимается только по флагам дома и модификатору «мы спим»: "
        "часов платформа не считает, поэтому «ночь» задаёт владелец сущностью "
        "sleep_modifier, а не расписание в коде.",
        "Смену флагов дома доносит HAAdapter (route_settings_change), а первый "
        "пересмотр делается при подключении: без него штора не приняла бы "
        "решение до первого переключения флага, которого может не быть часами.",
        "Второй триггер — device_state_diverged: сторож платформы видит, что "
        "положение прибора противоречит решению, и автомат повторяет решение. "
        "Команда идёт общим путём (посредник и блокировка человека), поэтому "
        "штору, которую человек только что тронул, повтор не тронет.",
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
HEADER = """# Контракт шаблонов поведения
#
# Файл сгенерирован: правьте шаблоны и реестр, затем перегенерируйте, иначе
# tests/contract/test_template_contract.py упадёт. Разделы `gaps` заполняются
# руками (они живут в tools/gen_template_contract.py), а `params` переносятся из
# этого файла. Проверить расхождение без перезаписи:
#   python tools/gen_template_contract.py --check
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
    "platform_events:",
    "  # События, которые порождает платформа, а не датчик и не движок.",
]
lines += [f"  {name}: {note}" for name, note in PLATFORM_EVENTS.items()]
lines += [
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
instantiated = _instantiated_places()

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
    rooms = instantiated.get(name, [])
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
        elif trig in PLATFORM_EVENTS:
            src = PLATFORM
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
args = [value for value in sys.argv[1:] if not value.startswith("--")]
check_only = "--check" in sys.argv[1:]
target = pathlib.Path(args[0]) if args else CONTRACT_PATH
rendered = "\n".join(lines) + "\n"

if check_only:
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if current != rendered:
        print(
            f"контракт устарел: {target}. Перегенерируйте без --check и проверьте "
            f"диф: разделы gaps и params пишутся руками"
        )
        sys.exit(1)
    print(f"контракт совпадает с кодом: {target}")
    sys.exit(0)

target.write_text(rendered, encoding="utf-8")
print(f"записано: {target}")
print("сгенерировано, строк:", len(lines))

"""Добавляет раздел params в CONTRACT.yaml: тип, диапазон, действенность."""

import pathlib
import re


# Код, исполняемый в горячем пути: только там параметр имеет силу.
HOT = ["src/core/action_handlers.py", "src/core/guards/builtin.py", "src/core/fsm/factory.py"]


def read_in_hot_path(param: str) -> bool:
    for rel in HOT:
        text = pathlib.Path(rel).read_text(encoding="utf-8")
        if f'"{param}"' in text:
            return True
    return False


PARAMS = {
    "lighting": [
        ("brightness", "int", "0-255", "Яркость включения; уходит в команду HA."),
        (
            "motion_timeout_sec",
            "int",
            "30-3600",
            "Задержка выключения. Переопределяет timeout_sec только у переходов с "
            "триггером timeout (factory.py:_timeout_from_params); у остальных "
            "переходов timeout_sec — верхняя граница ожидания, и подменять её неверно.",
        ),
    ],
    "night_light": [
        ("brightness", "int", "0-255", "Ночная яркость; уходит в команду HA."),
        (
            "schedule",
            "str",
            "ЧЧ:ММ-ЧЧ:ММ",
            "Окно ночного режима. Сейчас ИНЕРТЕН: читается только валидатором.",
        ),
    ],
    "deco_light": [
        (
            "off_by",
            "str",
            "sleep|sunrise",
            "Когда гаснет вечерний свет. `sleep` — по модификатору «мы спим» "
            "(гирлянда на террасе), `sunrise` — по рассвету (ночное освещение). "
            "Читают условия stops_on_sleep и stops_on_sunrise; без значения "
            "работает только выключение по рассвету.",
        ),
    ],
    "climate_control": [
        (
            "target_temp",
            "float",
            "5-35",
            "Целевая температура в градусах. Уходит в команду "
            "climate.set_temperature кондиционера (action_handlers.py:ac_cool_on); "
            "для обогрева цель берётся из automation_rules.climate, а не отсюда.",
        ),
        (
            "hysteresis",
            "float",
            "0-2",
            "Ширина мёртвой зоны обогревателя, °C. Читает условие may_heat "
            "(guards/builtin.py:_hysteresis_value); по умолчанию 0.5.",
        ),
        (
            "run_minutes",
            "float",
            "1-180",
            "На сколько минут включается обогреватель через его таймер. "
            "Читает действие heater_timer_on; по умолчанию 15 минут.",
        ),
        (
            "heater_timer",
            "str",
            "entity_id",
            "Сущность таймера обогревателя (number.*_countdown). Читает "
            "heater_timer_on; без неё обогреватель включается напрямую, и "
            "защиты от перегрева при отказе датчика нет.",
        ),
        (
            "managed_by_hardware",
            "bool",
            "true/false",
            "В комнате стоит штатный термостат; платформа обогревателем здесь "
            "не управляет (guards/builtin.py:make_may_heat).",
        ),
    ],
    "humidity_ventilation": [
        (
            "humidity_threshold",
            "float",
            "0-100",
            "Порог включения вентиляции; "
            "читается guard'ом — единственный параметр этого шаблона с силой.",
        ),
    ],
}

path = pathlib.Path("src/features/CONTRACT.yaml")
lines = path.read_text(encoding="utf-8").split("\n")
out = []
i = 0
while i < len(lines):
    line = lines[i]
    out.append(line)
    m = re.match(r"^  (\w[\w_]*):$", line)
    if m and m.group(1) in PARAMS:
        # вставляем раздел сразу после строк reachable/in_manifest — проще после
        # блока triggers/gaps шаблона; ищем конец блока шаблона
        j = i + 1
        while j < len(lines) and not re.match(r"^  \w[\w_]*:$", lines[j]):
            j += 1
        out.extend(lines[i + 1 : j])
        out.append("    params:")
        for name, typ, rng, note in PARAMS[m.group(1)]:
            effective = read_in_hot_path(name)
            out.append(f"      {name}:")
            out.append(f"        type: {typ}")
            out.append(f'        range: "{rng}"')
            out.append(f"        effective: {str(effective).lower()}")
            out.append(f'        note: "{note}"')
        i = j
        continue
    i += 1

path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("раздел params добавлен")

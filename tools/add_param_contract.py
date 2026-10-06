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
            "Задержка выключения. Сейчас ИНЕРТЕН: "
            "таймаут берётся из YAML шаблона (factory.py:227), параметр не участвует.",
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
    "climate_control": [
        (
            "target_temp",
            "float",
            "5-35",
            "Целевая температура. ИНЕРТЕН: читается только валидатором.",
        ),
        ("hysteresis", "float", "0-5", "Гистерезис. ИНЕРТЕН: читается только валидатором."),
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
            out.append(f"        range: {rng}")
            out.append(f"        effective: {str(effective).lower()}")
            out.append(f"        note: {note}")
        i = j
        continue
    i += 1

path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("раздел params добавлен")

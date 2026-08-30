#!/usr/bin/env python3
"""UI-артефакт освещения: блоки карточки из подключённых фич."""
from features.lighting.schema import _feats_of
from features.lighting import caps as CAPS  # noqa: F401


def _title(t):
    return {"type": "custom:mushroom-title-card", "title": t}


def _grid(cards, cols):
    return {"type": "grid", "columns": cols, "square": False, "cards": cards}


def _sel(e, n):
    return {"type": "custom:mushroom-select-card", "entity": e, "name": n}


def _num(e, n):
    return {"type": "custom:mushroom-number-card", "entity": e, "name": n}


def _bool(e, n):
    return {"type": "custom:mushroom-entity-card", "entity": e, "name": n}


def ui_schedule(g, gid):
    return [
        {"type": "conditional",
         "conditions": [{"entity": "input_select.light_%s_on" % gid, "state": "Время"}],
         "card": {"type": "entities", "entities": [
             {"entity": "input_datetime.light_%s_on_time" % gid, "name": "Включить в"}]}},
        {"type": "conditional",
         "conditions": [{"entity": "input_select.light_%s_off" % gid, "state": "Время"}],
         "card": {"type": "entities", "entities": [
             {"entity": "input_datetime.light_%s_off_time" % gid, "name": "Выключить в"},
             {"entity": "input_datetime.light_%s_off_end_time" % gid, "name": "Конец окна"}]}},
    ]


def ui_motion(g, gid):
    mo = _feats_of(g).get("motion") or {}
    mode_sel = "input_select.light_%s_motion_mode" % gid
    cards = [_title("📡 Движение"),
             _grid([_sel("input_select.light_%s_motion_sensor" % gid, "Датчик"),
                    _sel(mode_sel, "Режим")], 2),
             _grid([_bool("input_boolean.light_%s_motion" % gid, "Учитывать"),
                    _bool("input_boolean.light_%s_motion_day" % gid, "Включать днём")], 2)]
    if mo.get("no_night_auto"):
        cards.append({"type": "conditional",
                      "conditions": [{"entity": mode_sel, "state": "Включать и выключать"}],
                      "card": _bool(mo["no_night_auto"], "Ночью авто — выкл")})
    if mo.get("timeouts") == "own":
        cards.append(_grid([_num("input_number.light_%s_motion_day_min" % gid, "Таймаут день"),
                            _num("input_number.light_%s_motion_night_min" % gid, "Таймаут ночь")], 2))
    # Ручной приоритет
    respect_entity = "input_boolean.light_%s_manual_respect" % gid
    cards.append(_bool(respect_entity, "Учитывать ручное управление"))
    cards.append({
        "type": "conditional",
        "conditions": [{"entity": respect_entity, "state": "on"}],
        "card": {"type": "vertical-stack", "cards": [
            _grid([_num("input_number.light_%s_manual_off_min" % gid, "Пауза после ручного выкл, мин"),
                   _num("input_number.light_%s_manual_on_min" % gid, "Пауза после ручного вкл, мин")], 2)
        ]}
    })
    return cards


def ui_nightlight(g, gid):
    caps = CAPS.group_caps(g)
    nl_on = "input_boolean.feature_%s_nightlight" % gid
    inner = [_grid([_num("input_number.light_%s_nightlight_brightness" % gid, "Яркость"),
                    _num("input_number.light_%s_nightlight_off_min" % gid, "Таймаут, мин")], 2)]
    if caps.get("rgb"):
        inner.append(_grid([_num("input_number.light_%s_nightlight_r" % gid, "R"),
                            _num("input_number.light_%s_nightlight_g" % gid, "G"),
                            _num("input_number.light_%s_nightlight_b" % gid, "B")], 3))
    return [
        _title("🌙 Ночник"),
        _bool(nl_on, "Включён"),
        {"type": "conditional",
         "conditions": [{"entity": nl_on, "state": "on"}],
         "card": {"type": "vertical-stack", "cards": inner}},
    ]


def ui_party(g, gid):
    return [_title("🎉 Вечеринка"),
            _sel("input_select.light_%s_party_role" % gid, "Роль в вечеринке")]


def ui_dusk(g, gid):
    return [_title("🌇 Темнота"),
            _bool("input_boolean.light_%s_require_dark" % gid, "Ждать темноты")]


def ui_ct(g, gid):
    return [_title("🌡️ Цвет. температура"),
            _bool("input_boolean.light_%s_ct_follow" % gid, "Следовать глобальной")]


def ui_imitation(g, gid):
    return [_title("🎭 Имитация"),
            _bool("input_boolean.light_%s_imitation" % gid, "Участвовать")]


ALWAYS = {"party"}
FEATURE_UI = {"party": ui_party, "dusk": ui_dusk, "ct": ui_ct, "imitation": ui_imitation,
              "schedule": ui_schedule, "motion": ui_motion, "nightlight": ui_nightlight}
FEATURE_ORDER = ["party", "schedule", "dusk", "motion", "nightlight", "ct", "imitation"]


def group_feature_blocks(g, gid):
    feats = _feats_of(g)
    out = []
    for fname in FEATURE_ORDER:
        if fname in feats or fname in ALWAYS:
            out += FEATURE_UI[fname](g, gid)
    return out

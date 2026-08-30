#!/usr/bin/env python3
"""UI-артефакт фичи covers: карточки настроек для дашборда."""

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

def _info(e, n):
    return {"type": "custom:mushroom-template-card", "entity": e, "content": "{{ states(entity) }}", "name": n}


def cover_card(c, defaults):
    """Карточка одной шторы."""
    cid = str(c.get("id"))
    name = c.get("name", cid)
    
    cards = [
        _title("🪟 " + name),
        # Тумблер автоматики
        _bool("input_boolean.cover_%s_auto" % cid, "Автоматика"),
        # Грид: Закрытие + Открытие
        _grid([
            _sel("input_select.cover_%s_close" % cid, "Закрытие"),
            _sel("input_select.cover_%s_open" % cid, "Открытие")
        ], 2),
        # Время закрытия (условно)
        {"type": "conditional",
         "conditions": [{"entity": "input_select.cover_%s_close" % cid, "state": "Время"}],
         "card": {"type": "entities", "entities": [
             {"entity": "input_datetime.cover_%s_close_time" % cid, "name": "Время закрытия"}
         ]}},
        # Время открытия (условно)
        {"type": "conditional",
         "conditions": [{"entity": "input_select.cover_%s_open" % cid, "state": "Время"}],
         "card": {"type": "entities", "entities": [
             {"entity": "input_datetime.cover_%s_open_time" % cid, "name": "Время открытия"}
         ]}},
    ]
    
    # Если дверь — добавляем away_closed_pct и fire_safety настройки
    if c.get("door"):
        cards.append(_num("input_number.cover_%s_away_closed_pct" % cid, "Закрывать ушедших, %"))
        cards.append(_bool("input_boolean.cover_%s_fire_safety" % cid, "Пожарная безопасность"))
        cards.append({
            "type": "conditional",
            "conditions": [{"entity": "input_boolean.cover_%s_fire_safety" % cid, "state": "on"}],
            "card": {
                "type": "entities",
                "entities": [
                    {"entity": "input_number.cover_%s_fire_safety_min_pct" % cid, "name": "Мин. открытие, %"}
                ]
            }
        })
    
    # Информационное поле: текущее положение
    cover_entity = c.get("cover")
    cards.append({
        "type": "custom:mushroom-template-card",
        "entity": cover_entity,
        "content": "{{ state_attr(entity, 'current_position') | default('нет данных') }}%",
        "name": "Положение"
    })
    
    return {"type": "custom:vertical-stack-in-card", "cards": cards}


def covers_global_card():
    """Глобальная карточка настроек штор."""
    return {
        "type": "custom:vertical-stack-in-card",
        "cards": [
            _title("🪟 Шторы — глобальные настройки"),
            _grid([
                _bool("input_boolean.dogs_home", "Собаки дома"),
                _bool("input_boolean.feature_covers", "Автоматика штор"),
                _bool("input_boolean.covers_shadow_mode", "Shadow режим")
            ], 2)
        ]
    }


def generate_covers_ui(cfg):
    """Генерация UI для всех штор."""
    if not cfg or not cfg.get("enabled", True):
        return []
    
    out = [covers_global_card()]
    
    defaults = cfg.get("defaults", {"open_time": "08:00", "close_time": "00:00"})
    covers = cfg.get("covers", [])
    
    for c in covers:
        out.append(cover_card(c, defaults))
    
    return out

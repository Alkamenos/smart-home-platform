#!/usr/bin/env python3
"""Билдеры helper-entries (input_*)."""
def num(i, name, mn, mx, step, init, icon):
    return {"id": i, "type": "input_number/create", "name": name,
            "min": mn, "max": mx, "step": step, "initial": init, "icon": icon}

def bool_(i, name, init, icon):
    return {"id": i, "type": "input_boolean/create", "name": name,
            "initial": init, "icon": icon}

def dt(i, name, init, icon):
    return {"id": i, "type": "input_datetime/create", "name": name,
            "has_date": False, "has_time": True, "initial": init, "icon": icon}

def sel(i, name, options, init, icon):
    return {"id": i, "type": "input_select/create", "name": name,
            "options": options, "initial": init, "icon": icon}

def txt(i, name, initial="", max=100, icon="mdi:text"):
    """input_text helper."""
    return {
        "type": "input_text/create",
        "name": name,
        "initial": initial,
        "max": max,
        "icon": icon,
    }

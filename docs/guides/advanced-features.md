# 🧩 Advanced Features

## Manual Override Protection

Store context in State to detect manual overrides:

```python
def manual_override_guard(ctx: dict) -> bool:
    """Prevent auto-off if user manually turned on light."""
    import time

    manual_at = ctx.get("context", {}).get("manual_override_at", 0)
    if manual_at and (time.time() - manual_at) < 3600:
        return False  # Block transition for 1 hour
    return True


engine.register_guard("no_manual_override", manual_override_guard)
```

## Debounce Protection

Prevents rapid state changes:

```yaml
entity_id: binary_sensor.noisy_sensor
debounce_sec: 2.0  # Ignore events within 2 seconds
```

## Timeout Chains

Create complex timeout sequences:

```yaml
transitions:
  - from_state: active
    to_state: dimmed
    trigger: timeout
    timeout_sec: 300
    action: dim_lights

  - from_state: dimmed
    to_state: off
    trigger: timeout
    timeout_sec: 300
    action: turn_off_lights
```

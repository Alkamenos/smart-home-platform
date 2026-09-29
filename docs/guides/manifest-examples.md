# 📋 Example Manifest Configurations

The platform supports various home configurations. Complete working example:

- [`instances/leonids_house/manifest.yaml`](../../instances/leonids_house/manifest.yaml) — полноценный пример манифеста (комнаты, сенсоры, устройства, приоритеты)
- [`tests/fixtures/valid_manifest.yaml`](../../tests/fixtures/valid_manifest.yaml) — минимальный валидный манифест из тестов

## Example: Studio Apartment with Night Light Composition

```yaml
devices:
  - type: light_motion
    id: light.main_room
    name: Main Room Light
    room: main_room
    behaviors:
      # Night mode: dim light (priority 20)
      - template: night_light
        priority: 20
        params:
          brightness: 15
          schedule: "23:00-07:00"
      # Day mode: bright motion-activated light (priority 10)
      - template: lighting
        priority: 10
        params:
          motion_sensor: binary_sensor.main_room_motion
          motion_timeout_sec: 180
          schedule: "07:00-23:00"
          brightness: 255
```

**How it works:**
- At night (23:00-07:00), motion triggers dim light (brightness=15) via `night_light` behavior
- During day (07:00-23:00), motion triggers bright light (brightness=255) via `lighting` behavior
- Higher priority (20 > 10) ensures night mode overrides day mode when both are active

## Example: Middleware Configuration

```yaml
automation_rules:
  # Global lockout: block automation for 60 min after manual control
  global_manual_lockout_min: 60

  # Domain-specific overrides
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 90
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
```

**How middleware works:**
- When user manually controls a device, automation is blocked for the configured duration
- Prevents automation from fighting with user preferences
- Different domains can have different lockout durations

## Example: Migration-Aware Manifest

```yaml
instance:
  id: my_house
  name: My House
  owner: John
  created_at: '2024-01-15'

version: 1  # Automatically managed by migration system

devices:
  - type: light_motion
    id: light.kitchen
    # ... device config
```

**Migration system:**
- Old manifests without `version` field are automatically updated
- New migrations are discovered and applied sequentially
- Ensures backward compatibility across platform versions

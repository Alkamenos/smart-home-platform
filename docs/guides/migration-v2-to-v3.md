# 🔄 Migration Guide: v2.x → v3.0.0

This section helps you migrate your existing v2.x configurations to v3.0.0.

## Automatic Migrations

The platform includes an automatic migration system that updates legacy manifests:

- Manifests without `version` field are automatically updated to the latest schema
- Old configuration structures are transformed to match v3 requirements
- Migration scripts run on platform startup

## Manual Changes Required

### 1. Behavior Templates

**Before (v2.x):**
```yaml
behaviors:
  - template: lighting
    entity_id: light.kitchen  # Hardcoded entity_id
    params:
      motion_sensor: binary_sensor.kitchen_motion
```

**After (v3.0.0):**
```yaml
devices:
  - type: light_motion
    id: light.kitchen  # entity_id moved to device level
    behaviors:
      - template: lighting
        priority: 10  # Priority is now required
        params:
          motion_sensor: binary_sensor.kitchen_motion
```

### 2. Middleware Configuration

**Before (v2.x):**
```yaml
manual_lockout_min: 60
```

**After (v3.0.0):**
```yaml
automation_rules:
  global_manual_lockout_min: 60
  lighting:
    manual_lockout_min: 60
  climate:
    manual_lockout_min: 90
```

### 3. Priority Assignment

All behaviors must now have explicit priority values:

| Priority | Use Case | Example |
|----------|----------|---------|
| 20+ | Critical/Safety | Emergency override, fire alarm |
| 20 | Night Light | Dim lighting during night hours |
| 10 | Standard Motion | Regular motion-activated lighting |
| 1-9 | Background | Environmental control, ventilation |

### 4. Device-Level Sensors

Sensors can now be defined at device level instead of behavior level:

```yaml
devices:
  - type: light_motion
    id: light.kitchen
    sensors:
      motion: binary_sensor.kitchen_motion
      brightness: sensor.kitchen_lux
    behaviors:
      - template: lighting
        priority: 10
```

## Testing Your Migration

1. Run validation tests before starting:
   ```bash
   pytest tests/test_manifest_validator.py -v
   ```

2. Check health after startup (Web UI must be running):
   ```bash
   curl http://localhost:8000/health
   ```

3. Review logs for any migration warnings

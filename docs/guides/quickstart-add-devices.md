# 🚀 Quick Start: Adding Devices from Home Assistant

## Bulk Import Workflow

The platform supports three approaches to add 200+ devices from Home Assistant into your manifest:

### 1. **CLI Interactive Mode (Recommended)**

Step-by-step interactive selection with room assignment:

```bash
python -m smart_home.cli.main bulk-import interactive \
  --manifest instances/leonids_house/manifest.yaml

# Interactive prompts:
# 1. For each device:
#    - Add to manifest? [y/n]
#    - Choose room (from existing or create new)
#    - Use suggested behavior template? [y/n]
# 2. Preview changes (dry-run)
# 3. Confirm and apply
```

**Features:**
- ✓ Device-by-device selection
- ✓ **Change room for any device** before applying
- ✓ Choose or create new rooms
- ✓ Accept/reject suggested behavior templates
- ✓ Preview before applying
- ✓ Automatic backup

### 2. **CLI Auto-Apply (Fast Bulk Import)**

For quick bulk import with auto-detection:

```bash
# Scan and display all devices
python -m smart_home.cli.main bulk-import discover \
  --manifest instances/leonids_house/manifest.yaml

# Dry-run: see what would be added
python -m smart_home.cli.main bulk-import apply \
  --manifest instances/leonids_house/manifest.yaml \
  --dry-run \
  --auto-apply-lighting \
  --auto-apply-climate

# Actually apply
python -m smart_home.cli.main bulk-import apply \
  --manifest instances/leonids_house/manifest.yaml \
  --auto-apply-lighting \
  --auto-apply-climate
```

### 3. **Web UI (Interactive - Recommended for visual users)**

```bash
# Start the web UI (runs on http://localhost:8000)
make run-webui

# Then navigate to: http://localhost:8000/discovery
```

**Features:**
- ✓ Visual device list with filtering
- ✓ **Click on "Комната: X" to change room for each device**
- ✓ Pagination (25 devices per page)
- ✓ Filter by domain/category/area
- ✓ Search by entity_id
- ✓ Preview selected devices
- ✓ Dry-run before applying
- ✓ Automatic backup

**Workflow:**
1. Open http://localhost:8000/discovery
2. Click "Сканировать" (Scan) to discover devices
3. Select devices by clicking on them
4. For each device, click room name to change it (or create new)
5. Click "Тестовый запуск" (Dry-run) to preview
6. Click "Применить" (Apply) to save to manifest

### 4. **Programmatic API**

```python
from src.adapters.ha_adapter import HAAdapter
from src.core.discovery.discovery_service import DeviceDiscoveryService
from src.core.discovery.models import BulkApplyRequest

# Initialize
adapter = HAAdapter(mode="websocket", ...)
discovery = DeviceDiscoveryService(adapter)

# Scan devices with auto-classification
result = await discovery.scan_devices(
    filter_category="lighting",  # optional: filter by category
    filter_area="kitchen"         # optional: filter by area
)

# Apply devices to manifest
request = BulkApplyRequest(
    include_all=False,
    include_categories=["lighting", "climate_control"],
    auto_apply_lighting=True,
    auto_apply_climate=True,
    exclude_entities=["light.do_not_touch"]
)
await discovery.bulk_apply(request, manifest_path="instances/leonids_house/manifest.yaml")
```

## How Device Classification Works

The platform automatically classifies 200+ device types:

| Domain | Category | Auto-Applied Behavior | Notes |
|--------|----------|----------------------|-------|
| `light` | `lighting` | `lighting` + `night_light` | Motion + schedule |
| `switch` | `lighting` or `switch_control` | depends on attributes | Name-based heuristics |
| `climate` | `climate_control` | `climate_control` | Temperature management |
| `fan` | `ventilation` | `humidity_ventilation` or `speed_control` | Humidity vs speed |
| `cover` | `cover_control` | `generic_cover` | Blinds, garage doors, etc |
| `lock` | `security` | `smart_lock` | Door locks with timeout |
| `binary_sensor` | `motion_sensor`, `door_sensor`, etc | (added to sensors) | Assigned to room |
| `sensor` | `temperature_sensor`, `humidity_sensor` | (added to sensors) | Assigned to room |

## Available Behavior Templates

The platform includes these ready-to-use FSM templates:

| Template | Domain | Use Case | States |
|----------|--------|----------|--------|
| `lighting` | light | Motion-activated with schedule | OFF, ON_MOTION, ON_MANUAL |
| `night_light` | light | Dim light during night hours | OFF, DIM, BRIGHT |
| `climate_control` | climate | Temperature management | IDLE, HEATING, COOLING |
| `humidity_ventilation` | fan | Humidity-controlled extraction | OFF, ON_HUMIDITY, MANUAL |
| `speed_control` | fan | Variable speed fans | OFF, LOW, MEDIUM, HIGH |
| `generic_switch` | switch | Simple on/off automation | OFF, ON, MANUAL_OVERRIDE |
| `generic_cover` | cover | Blinds, gates, garage doors | CLOSED, OPENING, OPEN, CLOSING |
| `smart_lock` | lock | Smart door locks | LOCKED, UNLOCKED, JAMMED |

## Manifest Structure After Import

```yaml
instance:
  id: leonids_house
  name: Leonid's House

version: 1

rooms:
  - id: kitchen
    name: Kitchen
    sensors:
      motion: binary_sensor.kitchen_motion    # Auto-discovered
      temperature: sensor.kitchen_temp
      humidity: sensor.kitchen_humidity
    devices:
      - id: light.kitchen
        type: light
        behaviors:
          - template: lighting                 # Auto-selected
            priority: 10                       # Auto-assigned
            params:
              motion_timeout_sec: 180
              brightness: 255
          - template: night_light
            priority: 20
            params:
              brightness: 15
              schedule: "23:00-07:00"
      - id: climate.kitchen
        type: climate
        behaviors:
          - template: climate_control
            priority: 15
            params:
              target_temp: 22.0

automation_rules:
  global_manual_lockout_min: 60
  lighting:
    motion_enabled: true
    schedule_enabled: true
```

## Next Steps After Import

1. **Review & Adjust**
   - Check device assignments in manifest
   - Adjust room assignments if needed
   - Modify behavior parameters

2. **Hot-Reload**
   - Changes are applied immediately
   - No restart required
   - FSMs are re-registered on manifest save

3. **Validate**
   - Run `pytest tests/test_manifest_validator.py -v` to check validator rules
   - Or start the Web UI — the manifest is validated on startup

4. **Export & Visualize**
   - Generate FSM diagrams: `shp export-fsm instances/leonids_house/manifest.yaml`

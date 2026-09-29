# Device Import Specification

**Version:** 1.0
**Status:** Active
**Last Updated:** 2026-09-29

## Overview

This specification defines the process for bulk importing 200+ devices from Home Assistant into the Smart Home FSM Platform. It covers device discovery, automatic classification, room assignment, and FSM behavior template application.

## Goals

- **Zero-Setup Automation**: Import devices with minimal user interaction
- **Intelligent Classification**: Automatically determine device type and suggested behavior
- **Flexible Room Assignment**: Map devices to HA areas or allow manual room selection
- **Minimal FSM Generation**: Apply simple, production-ready FSM templates automatically
- **Safety First**: Dry-run and backup before applying changes

## 1. Device Discovery Phase

### 1.1 Scanning Home Assistant

**Input:**
- HA WebSocket connection or Pyscript adapter
- Optional filter: domain, area, device name

**Process:**
1. Connect to HA (WebSocket or Pyscript)
2. Retrieve all entity states via `get_states()` API
3. Filter out system entities (automation, script, scene, zone, etc.)
4. Extract metadata: entity_id, domain, friendly_name, area_id, attributes

**Output:**
```python
@dataclass
class DiscoveredDevice:
    entity_id: str  # e.g., "light.kitchen"
    domain: str  # e.g., "light"
    name: str  # Display name
    friendly_name: str | None  # HA friendly name
    area_id: str | None  # HA area (room)
    state: str  # Current state
    attributes: dict  # HA attributes
    category: DeviceCategory  # Inferred category
    suggested_behavior: str | None  # Recommended FSM template
    auto_apply: bool  # Should be auto-imported
```

### 1.2 Filtering System Entities

**Excluded Domains:**
```python
SYSTEM_DOMAINS = {
    "automation",
    "script",
    "scene",
    "zone",
    "person",
    "sun",
    "weather",
    "device_tracker",
    "group",
    "input_boolean",
    "input_text",
    "input_number",
    "input_select",
    "input_datetime",
    "timer",
    "counter",
    "update",
    "persistent_notification",
    "hacs",
}
```

## 2. Device Classification Phase

### 2.1 Classification Algorithm

**Inputs:**
- entity_id: string (e.g., "light.kitchen_main")
- domain: string (e.g., "light")
- attributes: dict (friendly_name, device_class, etc.)

**Process:**
```
1. Check domain-to-category mapping
2. Apply device_class heuristics
3. Use name-based patterns for ambiguous types
4. Return (category, suggested_behavior, auto_apply_flag)
```

### 2.2 Device Categories

| Category | Domain | Suggested Behavior | Auto-Apply |
|----------|--------|-------------------|-----------|
| `lighting` | light | lighting + night_light | ✓ |
| `switch_lighting` | switch | lighting | ~ (name heuristic) |
| `switch_automation` | switch | (generic) | ✗ |
| `climate_control` | climate | climate_control | ✓ |
| `ventilation` | fan | humidity_ventilation | ✓ |
| `cooling` | fan | speed_control | ✓ |
| `motion_sensor` | binary_sensor | (not automated) | ✗ |
| `door_sensor` | binary_sensor | (not automated) | ✗ |
| `temperature_sensor` | sensor | (not automated) | ✗ |
| `humidity_sensor` | sensor | (not automated) | ✗ |
| `generic` | other | (generic) | ✗ |

### 2.3 Name-Based Heuristics

For ambiguous cases, use entity_id patterns:

```python
if "motion" in entity_id.lower():
    return DeviceCategory.MOTION_SENSOR

if "temp" in entity_id.lower():
    return DeviceCategory.TEMPERATURE_SENSOR

if "humid" in entity_id.lower():
    return DeviceCategory.HUMIDITY_SENSOR

if "door" in entity_id.lower() or "contact" in entity_id.lower():
    return DeviceCategory.DOOR_SENSOR

if domain == "switch":
    if "light" in entity_id.lower():
        return DeviceCategory.SWITCH_LIGHTING
    else:
        return DeviceCategory.SWITCH_AUTOMATION
```

## 3. Room Assignment Phase

### 3.1 Room Mapping Strategy

**Auto-Detection (used in discover/apply):**
1. Use HA `area_id` from entity attributes
2. Extract room from entity_id pattern (e.g., "light.**kitchen**_main" → "kitchen")
3. Fallback to "unassigned"

**Logic:**
```python
def get_room_id(device: DiscoveredDevice) -> str:
    # 1. HA area_id
    if device.area_id:
        return device.area_id

    # 2. Extract from entity_id
    parts = device.entity_id.split("_")
    if len(parts) >= 2:
        candidate = parts[-2]  # e.g., "light.kitchen_main" → "kitchen"
        if is_valid_room_name(candidate):
            return candidate

    # 3. Default
    return "unassigned"
```

### 3.2 Interactive Room Assignment (Recommended)

In **interactive mode**, user can assign any device to any room:

```
📦 light.garage_remote
   Category: lighting
   Suggested room: garage

   Available rooms:
     1. kitchen
     2. bedroom
     3. living_room
     4. garage (suggested)
     5. <enter new room name>

   Choose room [1-5]: 1  # User selects "kitchen" instead!
```

**Interactive options:**
- Select from existing rooms
- Create new room on the fly
- Override auto-detected room
- Create room hierarchy by name (e.g., "kitchen_pantry")

## 4. FSM Behavior Application Phase

### 4.1 Behavior Template Selection

**Lighting Devices:**
- Primary: `lighting` (motion-based, priority 10)
- Secondary: `night_light` (schedule-based dim, priority 20)
- Params: brightness, motion_timeout_sec, schedule

**Climate Devices:**
- Primary: `climate_control` (temperature target, priority 15)
- Params: target_temp, hysteresis, modes

**Ventilation Devices:**
- Primary: `humidity_ventilation` (humidity threshold, priority 5)
- Params: humidity_threshold, timeout_sec

**Generic Devices:**
- No auto-apply, manual configuration required

### 4.2 Default Parameter Assignment

**Lighting:**
```yaml
brightness: 255          # Full brightness
motion_timeout_sec: 180  # 3 minutes
schedule: "07:00-23:00"  # Day time
```

**Climate:**
```yaml
target_temp: 22.0
hysteresis: 0.5
modes: ["heat", "cool", "auto"]
```

**Ventilation:**
```yaml
humidity_threshold: 65
timeout_sec: 1800  # 30 minutes
```

## 5. Manifest Application Phase

### 5.1 Room Creation

If room doesn't exist in manifest:

```yaml
rooms:
  - id: kitchen
    name: Kitchen              # Auto-titlecase from id
    sensors: {}
    devices: []
```

### 5.2 Device Addition

**For Sensors (add to room.sensors):**
```yaml
sensors:
  motion: binary_sensor.kitchen_motion
  temperature: sensor.kitchen_temperature
  humidity: sensor.kitchen_humidity
```

**For Actuators (add to room.devices):**
```yaml
devices:
  - id: light.kitchen
    type: light
    behaviors:
      - template: lighting
        priority: 10
        params:
          brightness: 255
          motion_timeout_sec: 180
      - template: night_light
        priority: 20
        params:
          brightness: 15
          schedule: "23:00-07:00"
```

### 5.3 Deduplication

Before adding device, check if it already exists:
- Match by entity_id (exact)
- Skip if already in manifest
- Warn in logs if found elsewhere

## 6. Safety Mechanisms

### 6.1 Backup Strategy

Before modifying manifest:
```
manifest.yaml.bak.20260929_143000
manifest.yaml.bak.20260929_142500
manifest.yaml.bak.20260929_142000
```

Keep last 3 backups, auto-cleanup older ones.

### 6.2 Dry-Run Mode

Print what would be added without modifying:
```
Would add 42 devices:
  - light.kitchen → kitchen (lighting + night_light)
  - light.bedroom → bedroom (lighting + night_light)
  - climate.living_room → living_room (climate_control)
  ...
```

### 6.3 Validation

Before applying changes, validate manifest:
- Check Pydantic schema
- Verify all referenced sensors exist in rooms
- Check template names are valid
- Warn about missing behavior files

## 7. API Specifications

### 7.1 DeviceDiscoveryService

```python
class DeviceDiscoveryService:
    async def scan_devices(
        self,
        page: int = 1,
        page_size: int = 25,
        filter_domain: str | None = None,
        filter_category: str | None = None,
        filter_area: str | None = None,
    ) -> dict:
        """Scan with pagination and filtering."""

    async def bulk_apply(self, request: BulkApplyRequest, manifest_path: str) -> dict:
        """Apply all matching devices in bulk."""

    async def apply_selective(
        self, selections: list[dict], manifest_path: str, dry_run: bool = False
    ) -> dict:
        """Apply user-selected devices."""
```

### 7.2 DeviceClassifier

```python
class DeviceClassifier:
    def classify(
        self, entity_id: str, domain: str, attributes: dict
    ) -> tuple[DeviceCategory, str | None, bool]:
        """Return (category, suggested_behavior, auto_apply)."""

    def extract_room_name(self, entity_id: str) -> str:
        """Extract room from entity_id pattern."""

    def get_auto_apply_count(self, devices: list[DiscoveredDevice]) -> dict:
        """Return statistics: auto_apply_count by category."""
```

## 8. User Workflows

### 8.1 CLI Workflow

#### Interactive Mode (Recommended for flexibility)

```bash
python -m smart_home.cli.main bulk-import interactive \
  --manifest instances/leonids_house/manifest.yaml
```

**Flow:**
1. Scans all devices from HA
2. For each device, interactively asks:
   - "Add to manifest? [y/n]"
   - "Choose room: 1) kitchen 2) bedroom 3) <new room>"
   - "Use suggested behavior? [y/n]"
3. Shows preview (dry-run) of changes
4. Asks for confirmation: "Apply changes? [y/n]"
5. Creates backup and applies

**User can:**
- ✓ Skip unwanted devices
- ✓ **Assign any device to any room** (even create new rooms on the fly)
- ✓ Accept or reject suggested behaviors
- ✓ Preview before applying

#### Auto-Apply Mode (Fast bulk import)

```bash
# 1. Discover
python -m smart_home.cli.main bulk-import discover \
  --manifest instances/leonids_house/manifest.yaml

# Output: Displays paginated device list with classifications

# 2. Dry-run
python -m smart_home.cli.main bulk-import apply \
  --manifest instances/leonids_house/manifest.yaml \
  --dry-run \
  --auto-apply-lighting \
  --auto-apply-climate

# Output: Shows what would be added

# 3. Apply
python -m smart_home.cli.main bulk-import apply \
  --manifest instances/leonids_house/manifest.yaml \
  --auto-apply-lighting \
  --auto-apply-climate

# Output: "Added 42 devices. Backup: manifest.yaml.bak.20260929_143000"
```

### 8.2 Web UI Workflow

**URL:** `http://localhost:8000/discovery`

**Step-by-step:**

1. **Scan Devices** (Click "Сканировать" button)
   - System retrieves all devices from HA
   - Displays total count, auto-apply stats

2. **Browse & Filter**
   - Left sidebar: filter by domain/category/search
   - Pagination: 25 devices per page
   - Each device card shows:
     - Device name and entity_id
     - Category (lighting, climate, motion, etc)
     - Domain (light, switch, sensor, etc)
     - Current state
     - Auto-apply indicator (✅ or ⚠️)

3. **Select Devices**
   - Click device card to select/deselect
   - Checkboxes on left for multiple selection
   - Quick buttons: "Выбрать все" (Select all), "Очистить" (Clear), "Только авто" (Auto-apply only)

4. **Assign Rooms** (THE KEY FEATURE!)
   - Right panel shows "Предпросмотр" (Preview) of selected devices
   - For each device, click on room name to open modal
   - **Modal options:**
     - List of existing rooms (from manifest)
     - Input field to create new room
   - User can assign any device to any room
   - Room list updates as new rooms are added

5. **Preview & Apply**
   - "Тестовый запуск" (Dry-run): shows what would be added
   - "Применить" (Apply): saves to manifest with backup
   - Status messages show success/errors

**Example:**
```
Device: light.bedroom_pendant
Suggested room: bedroom
User clicks: "bedroom" → Modal appears
Options:
  ○ kitchen
  ○ living_room
  ○ bedroom (selected)
  ○ [new room input]
User selects: kitchen ✓
Device reassigned to kitchen
```

### 8.3 Programmatic Workflow

```python
# Initialize
adapter = HAAdapter(...)
discovery = DeviceDiscoveryService(adapter)

# Scan
result = await discovery.scan_devices()
print(f"Found {result['total']} devices")

# Dry-run
request = BulkApplyRequest(auto_apply_lighting=True, auto_apply_climate=True)
dry_result = await discovery.bulk_apply(request, manifest_path)
print(f"Would add {dry_result['dry_run']}")

# Apply
actual_result = await discovery.bulk_apply(request, manifest_path)
print(f"Added {actual_result['devices_added']} devices")
```

## 9. Error Handling

| Error | Cause | Recovery |
|-------|-------|----------|
| HA connection failed | WebSocket/Pyscript unavailable | Show error, retry options |
| Invalid manifest path | File doesn't exist | Exit with error message |
| Manifest validation error | Pydantic schema violation | Show validation errors, don't apply |
| Device already exists | Entity_id already in manifest | Skip, warn in logs |
| Behavior template not found | Template file missing | Warn, don't apply to device |
| Backup failed | Write permission issue | Exit before modifying manifest |

## 10. Testing Strategy

### 10.1 Unit Tests

- DeviceClassifier: test all device types
- Room extraction: test entity_id patterns
- Parameter defaults: test for each behavior template
- Deduplication: test that existing devices are skipped

### 10.2 Integration Tests

- End-to-end: discover → classify → apply (dry-run + actual)
- Manifest validation: ensure output is valid YAML
- Idempotency: applying twice should not duplicate devices
- Rollback: restore from backup and verify

### 10.3 Manual Tests

- Scan a real HA instance with 200+ devices
- Verify classifications are reasonable
- Apply and check FSMs are created correctly
- Verify hot-reload works

## 11. Future Enhancements

- [ ] Custom behavior templates per category
- [ ] AI-based behavior suggestion (based on device history)
- [ ] Batch parameter editing
- [ ] Device grouping (e.g., "all kitchen lights")
- [ ] Template migration for v2→v3 manifests
- [ ] Sensor linking (auto-connect motion to lights)

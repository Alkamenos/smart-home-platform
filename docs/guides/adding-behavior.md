# 🔧 How to Add New Behavior

Follow these steps to add a new behavior template to the Smart Home Platform:

## Step 1: Create YAML Template in `src/features/`

Create a new YAML file (e.g., `src/features/my_new_behavior.yaml`) that defines your FSM:

```yaml
# src/features/my_new_behavior.yaml - ABSTRACT TEMPLATE
#
# EXPECTED PARAMETERS in params (from manifest):
#   - my_param: type - Description of parameter
#
# EXAMPLE USAGE in manifest.yaml:
#   devices:
#     - type: my_device
#       id: my_device_id
#       behaviors:
#         - template: my_new_behavior
#           priority: 15
#           params:
#             my_param: value

initial_state: "OFF"
debounce_sec: 0.5

states:
  - "OFF"
  - "ON"

transitions:
  - from_state: "OFF"
    to_state: "ON"
    trigger: "my_trigger"
    action: "my_action"
```

**Key Points:**
- Do NOT hardcode `entity_id` - it will be injected from the manifest
- Add comments explaining expected parameters
- Include an example usage in comments

## Step 2: Define Action Handlers in Python

Create action handler functions that return `CommandIntent`:

```python
# In your actions module or initialization code
from core import CommandIntent


async def my_action(state, context: dict) -> CommandIntent:
    """My custom action handler."""
    entity_id = context.get("entity_id", "default_entity")
    brightness = context.get("params", {}).get("brightness", 255)

    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data={"brightness": brightness},
        priority=context.get("priority", 10),
        source="my_new_behavior",
    )


# Register with the engine
engine.register_action("my_action", my_action)
```

**Key Points:**
- Actions receive both `state` and `context` arguments
- Return `CommandIntent` instead of calling HA directly
- Use `context.get("entity_id")` for the target device
- Set appropriate `priority` in the intent

## Step 3: Add Behavior to Manifest with Priority

Edit your instance manifest (e.g., `instances/my_house/manifest.yaml`):

```yaml
devices:
  - type: my_device_type
    id: my_device_id
    name: My Device
    room: my_room
    behaviors:
      - template: my_new_behavior
        priority: 15  # Choose priority based on importance
        params:
          my_param: value
          brightness: 100
```

**Priority Guidelines:**
| Priority | Use Case |
|----------|----------|
| 20+ | Critical/Safety (emergency override) |
| 20 | Night Light (blocks standard lighting) |
| 10 | Standard Motion Lighting |
| 1-9 | Background/Environmental control |

## Step 4: Test Your Behavior

Run tests to verify your behavior works correctly:

```bash
# Run all tests
pytest

# Run specific scenario test
pytest tests/test_fsm_factory.py -v

# Run kitchen demo
python fsm_demo/kitchen_demo.py
```

## Complete Example: Adding a "Party Mode" Behavior

**1. Create `src/features/party_mode.yaml`:**
```yaml
# Party mode - colorful lighting for parties
initial_state: "OFF"
states: ["OFF", "PARTY"]
transitions:
  - from_state: "OFF"
    to_state: "PARTY"
    trigger: "party_start"
    action: "start_party_lights"
  - from_state: "PARTY"
    to_state: "OFF"
    trigger: "party_end"
    action: "stop_party_lights"
```

**2. Create action handlers:**
```python
async def start_party_lights(state, context: dict) -> CommandIntent:
    return CommandIntent(
        device_id=context["entity_id"],
        domain="light",
        service="turn_on",
        data={"effect": "colorloop", "brightness": 200},
        priority=5,  # Low priority, easily overridden
        source="party_mode",
    )
```

**3. Add to manifest:**
```yaml
behaviors:
  - template: party_mode
    priority: 5
    params:
      colors: ["red", "blue", "green"]
```

## Step 1: Define Your FSM in YAML

Create a file `config/smart_home/kitchen_motion.yaml`:

```yaml
entity_id: binary_sensor.kitchen_motion
initial_state: idle
states:
  - idle
  - active
  - timeout_pending
debounce_sec: 2.0

transitions:
  # Motion detected: idle -> active
  - from_state: idle
    to_state: active
    trigger: motion_detected
    action: turn_on_kitchen_light

  # No motion for 5 minutes: active -> timeout_pending
  - from_state: active
    to_state: timeout_pending
    trigger: timeout
    timeout_sec: 300
    action: dim_kitchen_light

  # Motion during timeout: reset timer
  - from_state: timeout_pending
    to_state: active
    trigger: motion_detected
    action: brighten_kitchen_light

  # Timeout expires: timeout_pending -> idle
  - from_state: timeout_pending
    to_state: idle
    trigger: timeout
    timeout_sec: 300
    action: turn_off_kitchen_light
```

## Step 2: Register Guard and Action Functions

In your initialization code (`smart_home_bridge.py`):

```python
from core import FSMEngine
from adapters.ha_adapter import HAAdapter

# Initialize engine and adapter
engine = FSMEngine()
adapter = HAAdapter(mode="pyscript", engine=engine, hass=hass)


# Register action functions
async def turn_on_kitchen_light(ctx: dict) -> bool:
    """Turn on kitchen light when motion detected."""
    return await adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id="light.kitchen",
        data={"brightness": 255},
        trace_id=ctx.get("trace_id"),
    )


async def turn_off_kitchen_light(ctx: dict) -> bool:
    """Turn off kitchen light when no motion."""
    return await adapter.call_service(
        domain="light",
        service="turn_off",
        entity_id="light.kitchen",
        trace_id=ctx.get("trace_id"),
    )


async def dim_kitchen_light(ctx: dict) -> bool:
    """Dim lights when entering timeout state."""
    return await adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id="light.kitchen",
        data={"brightness": 50},
        trace_id=ctx.get("trace_id"),
    )


# Register actions with engine
engine.register_action("turn_on_kitchen_light", turn_on_kitchen_light)
engine.register_action("turn_off_kitchen_light", turn_off_kitchen_light)
engine.register_action("dim_kitchen_light", dim_kitchen_light)


# Optional: Register guard functions
def is_night_time(ctx: dict) -> bool:
    """Only allow automation at night."""
    from datetime import datetime

    hour = datetime.now().hour
    return hour < 7 or hour > 22


engine.register_guard("is_night_time", is_night_time)
```

## Step 3: Wire Up State Change Handlers

In Pyscript (`/config/pyscript/smart_home_bridge.py`):

```python
@state_trigger("binary_sensor.kitchen_motion")
def kitchen_motion_changed(value=None, old_value=None):
    """Handle motion sensor state changes."""
    if value == "on" and old_value == "off":
        adapter.on_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="on",
            old_state="off",
            context={},
        )
```

## Step 4: Load FSM Definitions

```python
from core import DefinitionLoader

loader = DefinitionLoader(registry=registry, engine=engine)
loader.load_definitions("/config/smart_home/")
```

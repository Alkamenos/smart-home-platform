# Smart Home Platform - Web UI Specification

## Overview
The Web UI is a FastAPI + HTMX + Jinja2 application that allows users to edit smart home FSM manifests without manual YAML editing. The UI provides visual management of rooms, devices, behaviors, and their configurations.

## Architecture

### Technology Stack
- **Backend:** FastAPI (Python web framework)
- **Frontend:** HTMX (for dynamic updates), Bootstrap 5 (styling), Jinja2 (templating)
- **Storage:** YAML files with in-memory manifest store and undo support
- **Template Discovery:** Auto-loads FSM templates from `src/features/*.yaml`

### Core Components
1. **ManifestStore** (`src/webui/app.py`) - In-memory manifest with save/undo
2. **TemplateLoader** (`src/webui/template_loader.py`) - FSM template parser
3. **Routes** (`src/webui/routes.py`) - API endpoints for manifest management
4. **Templates** (`src/webui/templates/`) - HTML/HTMX UI components

---

## User Stories

### US-001: View Smart Home Configuration
**As a** home automation user  
**I want to** see my entire smart home configuration (rooms, devices, behaviors)  
**So that** I can understand the current setup and plan modifications  

**Acceptance Criteria:**
- [ ] Index page `/` displays all rooms from manifest
- [ ] Each room shows its devices with their type and name
- [ ] Devices display their configured behaviors
- [ ] Page loads within 2 seconds
- [ ] Layout is responsive on mobile/tablet/desktop
- [ ] Room cards have distinct visual styling with background color/border

**Example Flow:**
1. User opens `http://localhost:8125/`
2. Sees list of rooms (e.g., "Kitchen", "Bedroom", "Living Room")
3. Each room card shows devices: "light.kitchen" (Light), "fan.bedroom" (Ventilation), etc.
4. Under each device: behaviors like "lighting (priority 10)", "night_light (priority 20)"

---

### US-002: Move Device Between Rooms
**As a** home automation user  
**I want to** move a device to a different room without deleting and recreating it  
**So that** I can reorganize my smart home when devices physically move  

**Acceptance Criteria:**
- [ ] Device edit form has a "Room" dropdown selector
- [ ] Dropdown shows all available rooms with device count: "Kitchen (5 devices)"
- [ ] Current room is pre-selected
- [ ] Clicking "Save Device" moves device to selected room
- [ ] Old room's device list updates immediately
- [ ] New room receives the device with all behaviors intact
- [ ] Manifest file is saved with the change

**Example Flow:**
1. User clicks "Edit" on "light.kitchen"
2. Form opens showing current room: "Kitchen" selected
3. User changes room to "Living Room"
4. User clicks "Save Device"
5. Device now appears in Living Room, removed from Kitchen

---

### US-003: Add Device to Room
**As a** home automation user  
**I want to** add a new device to a specific room from within that room's card  
**So that** I can quickly add discovered devices without navigating away  

**Acceptance Criteria:**
- [ ] Each room card has an "Add Device" button in its footer
- [ ] Clicking "Add Device" opens the device form with room pre-selected
- [ ] Form title shows "Add Device" (not "Edit Device")
- [ ] Device fields are empty and ready for input
- [ ] Saving adds device to the selected room in manifest

**Example Flow:**
1. User sees room card "Kitchen"
2. Clicks "Add Device" button at bottom of card
3. Device form opens with room pre-selected to "Kitchen"
4. User enters device ID, type, name, behaviors
5. Clicks "Save Device"
6. Device appears in Kitchen room card

---

### US-004: Configure Device Behaviors
**As a** home automation user  
**I want to** add/edit/remove behaviors on a device with a dropdown selector instead of typing template names  
**So that** I can configure behaviors without remembering template names or syntax  

**Acceptance Criteria:**
- [ ] Device form has "Behaviors" section listing all behaviors
- [ ] "Add Behavior" button creates new behavior item
- [ ] Each behavior item shows:
  - [ ] Template dropdown (populated from available FSM templates)
  - [ ] Priority input field (1-100)
  - [ ] Remove button
  - [ ] Collapsible "Show Parameters" section
- [ ] Template dropdown only shows valid templates from `src/features/`
- [ ] Removing a behavior removes the item from the form
- [ ] Empty behaviors are not saved to manifest

**Example Flow:**
1. User edits device "light.kitchen"
2. Sees "Behaviors" section with existing behaviors
3. Clicks "Add Behavior"
4. New behavior item appears with empty template dropdown
5. User selects "lighting" from dropdown
6. User enters priority "10"
7. Clicks "Show Parameters" to expand parameters section

---

### US-005: Edit Behavior Parameters
**As a** home automation user  
**I want to** view and edit behavior parameters with proper validation hints  
**So that** I can configure behavior-specific settings correctly  

**Acceptance Criteria:**
- [ ] Each behavior has collapsible "Show Parameters" section
- [ ] Parameters section shows current parameters as JSON
- [ ] Parameters can be edited in a textarea as JSON
- [ ] JSON validation happens on save (reject invalid JSON)
- [ ] Save error message clearly indicates JSON syntax error
- [ ] Parameters include hints/examples from template documentation
- [ ] Common parameter names are auto-populated (future enhancement)

**Example Flow:**
1. User expands "Show Parameters" for "lighting" behavior
2. Sees current params: `{"motion_sensor": "binary_sensor.kitchen", "motion_timeout_sec": 300}`
3. Edits brightness value: `{"motion_sensor": "...", "brightness": 200}`
4. Saves device
5. Parameters are validated and saved to manifest

---

### US-006: Load FSM Templates Dynamically
**As a** backend system  
**I want to** automatically discover and load FSM templates from `src/features/*.yaml`  
**So that** template list stays in sync without manual updates  

**Acceptance Criteria:**
- [ ] TemplateLoader scans `src/features/` directory on app startup
- [ ] All `.yaml` files are loaded as FSM templates
- [ ] Template metadata is extracted: name, initial_state, states
- [ ] Template parameters are parsed from YAML comments
- [ ] Templates are accessible via `/api/templates` endpoint
- [ ] Individual template info available at `/api/templates/{template_name}`
- [ ] Invalid templates don't crash app (logged as warning)

**Example Flow:**
1. App starts, TemplateLoader runs
2. Finds 8 templates: lighting, climate_control, night_light, etc.
3. Parses each template's YAML structure
4. GET `/api/templates` returns list of all templates with metadata
5. Device form populates dropdown with template names

---

### US-007: Save Manifest Changes
**As a** home automation user  
**I want to** save my changes to the manifest YAML file with backup  
**So that** my configuration is persisted and I can undo if needed  

**Acceptance Criteria:**
- [ ] "Save Device" button saves device changes to manifest
- [ ] Manifest is written to YAML file
- [ ] Backup file is created before saving: `manifest.yaml.bak`
- [ ] Backup preserves the previous saved state
- [ ] Success message shows "Device saved successfully"
- [ ] Failure message shows error details (e.g., validation error)
- [ ] User can undo changes via "Undo" button (future)

**Example Flow:**
1. User edits device and clicks "Save Device"
2. Device form closes, page shows success toast
3. Manifest file is updated on disk
4. Previous state saved to `manifest.yaml.bak`
5. Dashboard refreshes to show new configuration

---

### US-008: View FSM State Diagrams
**As a** home automation user  
**I want to** visualize the state machine behavior of a device's FSM  
**So that** I can understand state transitions and priorities  

**Acceptance Criteria:**
- [ ] Dashboard includes FSM diagram for each device
- [ ] Diagram shows all states and transitions
- [ ] Each behavior's instance shown as separate machine
- [ ] Transitions labeled with trigger, guard, priority
- [ ] Mermaid state diagram format used for rendering
- [ ] Single-behavior devices show friendly device name
- [ ] Multi-behavior devices use sanitized IDs to avoid Mermaid conflicts

**Example Flow:**
1. User opens dashboard
2. Clicks "View FSM" for "light.kitchen"
3. Diagram displays showing:
   - Initial state transitions for each behavior
   - States (OFF, ON_MOTION, ON_SCHEDULE, etc.)
   - Transition labels with guards (motion, schedule, manual)

---

### US-009: Validate Manifest Structure
**As a** system  
**I want to** validate all manifest data against Pydantic schemas  
**So that** invalid configurations are rejected with clear error messages  

**Acceptance Criteria:**
- [ ] All manifest data validated against ManifestModel
- [ ] Room IDs must be unique within manifest
- [ ] Device IDs must be unique within a room
- [ ] Behavior template must exist in available templates
- [ ] Priority must be integer 1-100
- [ ] Parameters must be valid JSON object
- [ ] Error messages indicate which field failed and why

**Example Flow:**
1. User tries to save device with invalid priority "abc"
2. Form validation shows error: "Priority must be integer between 1-100"
3. User tries to save with non-existent template "lighting_invalid"
4. Form shows error: "Template 'lighting_invalid' not found"
5. User corrects and saves successfully

---

### US-010: Health Check Endpoint
**As a** monitoring system  
**I want to** check if the Web UI service is running  
**So that** I can alert if the service is down  

**Acceptance Criteria:**
- [ ] GET `/health` endpoint always returns 200 OK
- [ ] Response includes status: "healthy"
- [ ] Response time < 100ms
- [ ] No authentication required

---

## API Endpoints Reference

### Manifest Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Index page - show all rooms and devices |
| GET | `/dashboard` | Dashboard with FSM diagrams |
| POST | `/devices/save` | Save device configuration |
| GET | `/devices/{room_index}/{device_id}/edit` | Load device edit form |
| GET | `/rooms/{room_index}/edit` | Load room edit form |
| POST | `/save` | Save full manifest |
| POST | `/undo` | Undo last changes |

### Template APIs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/templates` | List all available FSM templates |
| GET | `/api/templates/{template_name}` | Get template details with parameters |

### FSM Visualization
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/fsm/{device_id}/diagram` | Get Mermaid state diagram for device |

### Health & Discovery
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/discovery` | Device discovery page |
| GET | `/api/devices/discover` | Discover devices from Home Assistant |

---

## Template System

### Template File Format
FSM templates are YAML files in `src/features/*.yaml` with this structure:

```yaml
initial_state: idle
states:
  idle:
    # state definition
  active:
    # state definition
transitions:
  # transitions...

# ОЖИДАЕМЫЕ ПАРАМЕТРЫ / EXPECTED PARAMETERS
# - motion_sensor: str - ID датчика движения (example: "binary_sensor.kitchen_motion")
# - motion_timeout_sec: integer - Таймаут сенсора в секундах (default: 300, example: 600)
```

### Parameter Parsing
Parameters are extracted from comments following the format:
```
- param_name: type - Description (optional: default, example: "value")
```

Supported types: `str`, `integer`, `number`, `boolean`, `list`, `object`

---

## Error Handling

### HTTP Status Codes
- **200 OK** - Successful operation
- **400 Bad Request** - Invalid input (e.g., invalid JSON)
- **404 Not Found** - Resource not found (device, room, template)
- **422 Unprocessable Entity** - Validation error (e.g., missing required field)
- **500 Internal Server Error** - Unexpected error

### Error Response Format
```json
{
  "error": "Device not found",
  "details": "No device with ID 'light.invalid' in room 0"
}
```

---

## UI/UX Guidelines

### Visual Hierarchy
- Room cards: primary containers
- Device cards: within room cards
- Behavior items: compact with collapsible details
- Form sections: grouped with clear labels

### Responsive Design
- Mobile (< 768px): Single column layout, compact buttons
- Tablet (768px - 1024px): Two column layout
- Desktop (> 1024px): Three column layout with sidebar

### Accessibility
- All form inputs have associated labels
- Buttons have clear text labels, not just icons
- Modals have dismiss buttons
- Focus management on modal open/close
- Color not used as only indicator

### User Feedback
- Toast notifications for success/error messages
- Loading spinners for async operations
- Disabled buttons while loading
- Clear error messages with actionable guidance

---

## Testing Requirements

### Unit Tests
- TemplateLoader correctly parses all template files
- ManifestStore save/load/undo operations
- Parameter extraction from YAML comments
- Validation of device/room/behavior data

### Integration Tests
- Full flow: add device → add behavior → save manifest
- Room selector updates on device move
- FSM diagram generation for all template types
- API endpoints return correct responses

### E2E Tests (Browser)
- User can add device with all behaviors
- Room selector changes and persists
- Template dropdown populated from API
- Parameter editing with JSON validation
- Mobile responsive layout functions

### Coverage Requirements
- **Minimum:** 80% for new code
- **Critical paths:** 95% (device save, manifest persistence)
- **Template loading:** 100%

---

## Performance Requirements

- Index page loads in < 2 seconds
- Device form opens in < 500ms
- Template API response < 100ms
- FSM diagram generation < 1 second
- Manifest file save < 500ms

---

## Future Enhancements

1. **Parameter Form Generator** - Auto-generate form fields based on parameter types instead of JSON textarea
2. **Behavior Templates Preview** - Show FSM diagram when selecting template
3. **Batch Device Operations** - Add multiple devices at once
4. **Device Search/Filter** - Find devices by ID or type
5. **Manifest Validation Report** - Show all issues before saving
6. **Real-time Collaboration** - Multiple users editing same manifest
7. **Home Assistant Live Sync** - Sync device states from HA
8. **Behavior Testing** - Simulate events and see state transitions

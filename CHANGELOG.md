# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- reorganize project structure with proper entry points

## [3.0.0] - 2024-09-14

### Major Release: FSM Engine v3

This major release introduces significant architectural improvements and new capabilities for smart home automation.

#### Added

**FSM Engine v3**
- Immutable state machines using dataclasses for thread-safe FSM definitions
- Enhanced state transition logic with guard conditions
- Timeout transitions with automatic state changes after delay
- Debounce protection to prevent rapid state bouncing

**EventRouter Integration**
- Sensor-to-FSM mapping for flexible event routing
- Entity resolution from device configurations
- Support for multiple sensor types per device

**Behavior Composition with Priorities**
- Multiple behaviors per device with priority-based conflict resolution
- Template-based behavior definitions in YAML
- Priority levels: Critical/Safety (20+), Night Light (20), Standard Motion (10), Background (1-9)
- Dynamic behavior activation based on schedules and conditions

**Middleware System**
- Global rules applied to all commands automatically
- ManualLockoutMiddleware for preventing automation conflicts
- Domain-specific middleware configuration
- Configurable lockout durations per device type

**State Persistence**
- JSON-based state storage for FSM states
- Graceful shutdown with state preservation
- State restoration on platform restart
- Concurrent access handling with proper locking

**Pydantic v2 Validation**
- Strict schema validation for manifest configurations
- Automatic migration support for legacy manifests
- Type-safe configuration models
- Comprehensive error reporting for invalid configurations

**src Layout Consolidation**
- Reorganized project structure with proper entry points
- Clean separation between core, adapters, CLI, and dashboard components
- Improved package distribution and import paths

#### Changed

**Architecture Improvements**
- CommandDispatcher with priority-based command resolution
- EventBus for async event distribution with trace context
- Scheduler for timer management with graceful cancellation
- Registry for guard/action function registration

**Configuration**
- Manifest versioning with automatic migrations
- Device-level sensor configuration
- Behavior parameters injected at runtime
- YAML-based FSM definitions

**Error Handling**
- Service call failures no longer crash the FSM engine
- Exponential backoff for connection reconnection
- End-to-end tracing with trace_id for debugging

#### Technical Details

**Core Components**
- `FSMEngine` - State machine execution engine
- `EventBus` - Event distribution system
- `Scheduler` - Timer and timeout management
- `Registry` - Guard and action function registry
- `CommandDispatcher` - Priority-based command resolution
- `EventRouter` - Sensor-to-FSM mapping
- `DefinitionLoader` - YAML definition loader

**Adapters**
- `HAAdapter` - Home Assistant integration (Pyscript/WebSocket modes)
- `MockAdapter` - Mock adapter for testing

**CLI Commands**
- `validate` - Validate manifest configurations
- `doctor` - Health check and diagnostics
- `health` - Platform status monitoring

#### Migration Notes

For users migrating from v2.x to v3.0.0:
- Manifest files without `version` field are automatically updated
- Old-style entity_id in behavior templates should be removed (injected automatically)
- Priority values should be assigned to behaviors (default: 10)
- Middleware configuration moved to `automation_rules` section

See MIGRATION_GUIDE.md for detailed migration instructions.

---

## [2.0.0] - Previous Release

*Note: Detailed changelog for v2.0.0 available in git history*

# Sample Plugin for Smart Home Platform

This is an example plugin demonstrating how to extend the Smart Home Platform with custom behaviors.

## Features

- **Party Mode Behavior**: Automatically manages lighting and music during parties
  - Activates in the evening
  - Enables colorful lighting scenes
  - Adjusts music volume based on noise level
  - Winds down when party ends

## Installation

### Development Mode

```bash
cd examples/sample_plugin
pip install -e .
```

### Production Mode

```bash
pip install sample-plugin
```

## Usage

Once installed, the plugin will be automatically discovered by the Smart Home Platform on startup. No additional configuration is required.

The `party_mode` behavior will be available for use in your FSM definitions:

```yaml
fsm_definitions:
  party_controller:
    extends: party_mode  # Reference the plugin behavior
```

## Creating Your Own Plugins

1. Create a class implementing the required interface (BehaviorPlugin, MiddlewarePlugin, or AdapterPlugin)
2. Register it in `pyproject.toml` under the appropriate entry point group
3. Install your package
4. The platform will automatically discover and load your plugin

See `behavior.py` for a complete example.

## License

MIT License

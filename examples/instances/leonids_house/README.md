# Leonid's House Instance

This is an example instance configuration for the Smart Home FSM Platform.

## Structure

```
leonids_house/
└── manifest.yaml    # Main configuration file
```

## Usage

To use this instance:

```bash
# Run platform with this manifest
smart-home run -m examples/instances/leonids_house/manifest.yaml

# Validate manifest
smart-home validate -m examples/instances/leonids_house/manifest.yaml

# List devices
smart-home list-devices -m examples/instances/leonids_house/manifest.yaml
```

## Features

This instance demonstrates:
- Multiple zones (rooms)
- Various device types (lights, sensors, switches)
- Behavior templates from the `features/` directory
- Entity mappings for Home Assistant integration

## Migration

If you're migrating from an older version, place your old manifest in this directory and run:

```bash
smart-home manifest migrate -i old_manifest.yaml -o manifest_v3.yaml
```

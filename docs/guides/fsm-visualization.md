# 🎨 FSM Visualization

The platform includes a powerful FSM visualization tool that generates diagrams from your manifest configurations.

## Using the export-fsm Command

```bash
# Export all FSMs from manifest to Mermaid format
shp export-fsm instances/leonids_house/manifest.yaml

# Export to Graphviz DOT format
shp export-fsm instances/leonids_house/manifest.yaml --format graphviz

# Export only specific device
shp export-fsm instances/leonids_house/manifest.yaml --device light.kitchen

# Save output to file
shp export-fsm instances/leonids_house/manifest.yaml -o output_fsm.md
```

## Command Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--format` | `-f` | Output format: `mermaid` or `graphviz` | `mermaid` |
| `--device` | `-d` | Filter by device ID (e.g., `light.kitchen`) | All devices |
| `--output` | `-o` | Output file path | stdout |

## Example Output (Mermaid)

```mermaid
stateDiagram-v2
    title Smart Home FSM Overview

    subgraph light_kitchen_lighting_10
        direction TB
        note right of OFF: light.kitchen
        [*] --> OFF
        OFF --> ON_MOTION: motion_detected
        ON_MOTION --> OFF: no_motion_timeout
    end
```

## Rendering Diagrams

**Mermaid:**
- GitHub/GitLab: Paste into markdown files (`.md`)
- Mermaid Live Editor: https://mermaid.live
- VS Code: Install "Markdown Preview Mermaid Support" extension

**Graphviz:**
- Convert to PNG: `dot -Tpng output.dot -o fsm.png`
- Online viewer: https://edotor.net

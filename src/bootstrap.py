"""
Bootstrap module for Smart Home Platform.

This module provides the bootstrap_platform() function that initializes
all platform components using the DI Container.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from core.container import Container, PlatformContext


def bootstrap_platform(manifest_path: str) -> PlatformContext:
    """
    Bootstrap the smart home platform using DI Container.

    Args:
        manifest_path: Path to the manifest YAML file.

    Returns:
        PlatformContext with all initialized components.
    """
    container = Container(manifest_path=manifest_path)
    return container.build()


if __name__ == "__main__":
    # Example usage
    import sys

    manifest_path = sys.argv[1] if len(sys.argv) > 1 else "instances/leonids_house/manifest.yaml"

    ctx = bootstrap_platform(manifest_path)
    print("Platform bootstrapped successfully!")
    print(f"  Instance: {ctx.manifest.instance.name}")
    print(f"  Devices: {len(ctx.manifest.devices)}")
    print(f"  Zones: {len(ctx.manifest.zones)}")
    print(f"  Lighting lockout: {ctx.manifest.automation_rules.lighting.manual_lockout_min} min")
    print(f"  Climate lockout: {ctx.manifest.automation_rules.climate.manual_lockout_min} min")
    print(
        f"  Ventilation lockout: {ctx.manifest.automation_rules.ventilation.manual_lockout_min} min"
    )
    print(f"  Global lockout: {ctx.manifest.automation_rules.global_manual_lockout_min} min")

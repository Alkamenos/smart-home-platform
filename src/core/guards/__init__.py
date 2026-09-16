"""Guards module for smart home platform."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from .schedule_guard import is_within_schedule


__all__ = ["is_within_schedule"]

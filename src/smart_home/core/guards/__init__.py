"""Guards module for smart home platform."""

from .schedule_guard import is_within_schedule

__all__ = ["is_within_schedule"]

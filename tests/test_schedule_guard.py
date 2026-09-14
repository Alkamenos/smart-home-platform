"""Tests for schedule guard functionality."""

import pytest
from datetime import datetime
from freezegun import freeze_time

from smart_home.core.guards.schedule_guard import is_within_schedule


class TestScheduleGuard:
    """Tests for is_within_schedule guard function."""

    def test_no_schedule_always_active(self):
        """Test that without schedule, guard returns True (always active)."""
        ctx = {"params": {}}
        assert is_within_schedule(ctx) is True
        
        ctx_empty = {}
        assert is_within_schedule(ctx_empty) is True

    def test_normal_schedule_within_range(self):
        """Test normal schedule (no midnight crossing) within range."""
        # Schedule: 09:00-17:00 (working hours)
        ctx = {"params": {"schedule": "09:00-17:00"}}
        
        with freeze_time("2024-01-01 12:00:00"):
            assert is_within_schedule(ctx) is True
        
        with freeze_time("2024-01-01 09:00:00"):
            assert is_within_schedule(ctx) is True
            
        with freeze_time("2024-01-01 17:00:00"):
            assert is_within_schedule(ctx) is True

    def test_normal_schedule_outside_range(self):
        """Test normal schedule (no midnight crossing) outside range."""
        # Schedule: 09:00-17:00 (working hours)
        ctx = {"params": {"schedule": "09:00-17:00"}}
        
        with freeze_time("2024-01-01 08:59:59"):
            assert is_within_schedule(ctx) is False
        
        with freeze_time("2024-01-01 17:00:01"):
            assert is_within_schedule(ctx) is False
            
        with freeze_time("2024-01-01 23:00:00"):
            assert is_within_schedule(ctx) is False

    def test_midnight_crossing_schedule_day_time(self):
        """Test schedule with midnight crossing (23:00-07:00) during day - should block."""
        # Schedule: 23:00-07:00 (night time)
        ctx = {"params": {"schedule": "23:00-07:00"}}
        
        # At 12:00 (day) - should be OUTSIDE schedule (blocked)
        with freeze_time("2024-01-01 12:00:00"):
            assert is_within_schedule(ctx) is False
    
    def test_midnight_crossing_schedule_night_time(self):
        """Test schedule with midnight crossing (23:00-07:00) during night - should allow."""
        # Schedule: 23:00-07:00 (night time)
        ctx = {"params": {"schedule": "23:00-07:00"}}
        
        # At 02:00 (night) - should be INSIDE schedule (allowed)
        with freeze_time("2024-01-01 02:00:00"):
            assert is_within_schedule(ctx) is True
        
        # At 23:30 (night) - should be INSIDE schedule (allowed)
        with freeze_time("2024-01-01 23:30:00"):
            assert is_within_schedule(ctx) is True
        
        # At 06:59 (night) - should be INSIDE schedule (allowed)
        with freeze_time("2024-01-01 06:59:59"):
            assert is_within_schedule(ctx) is True

    def test_midnight_crossing_boundary_times(self):
        """Test boundary times for midnight crossing schedule."""
        ctx = {"params": {"schedule": "23:00-07:00"}}
        
        # Exactly at start (23:00) - should be inside
        with freeze_time("2024-01-01 23:00:00"):
            assert is_within_schedule(ctx) is True
        
        # Exactly at end (07:00) - should be inside
        with freeze_time("2024-01-01 07:00:00"):
            assert is_within_schedule(ctx) is True
        
        # Just before start (22:59) - should be outside
        with freeze_time("2024-01-01 22:59:59"):
            assert is_within_schedule(ctx) is False
        
        # Just after end (07:01) - should be outside
        with freeze_time("2024-01-01 07:01:00"):
            assert is_within_schedule(ctx) is False

    def test_evening_to_morning_schedule(self):
        """Test evening to morning schedule (e.g., 18:00-06:00)."""
        ctx = {"params": {"schedule": "18:00-06:00"}}
        
        # During evening/night - should be inside
        with freeze_time("2024-01-01 20:00:00"):
            assert is_within_schedule(ctx) is True
        
        with freeze_time("2024-01-01 03:00:00"):
            assert is_within_schedule(ctx) is True
        
        # During day - should be outside
        with freeze_time("2024-01-01 12:00:00"):
            assert is_within_schedule(ctx) is False
        
        with freeze_time("2024-01-01 10:00:00"):
            assert is_within_schedule(ctx) is False

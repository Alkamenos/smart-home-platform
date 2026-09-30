"""Tests for MockAdapter lifecycle (start/stop) — BACKLOG Q7.

Проверяет, что ``run_platform()`` работает в mock-режиме без ``HA_TOKEN``:
``ctx.adapter.start()`` и ``PlatformContext.shutdown()`` (→ ``adapter.stop()``)
не падают с ``AttributeError`` (Known Issue #14).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from unittest.mock import patch

from adapters.mock_adapter import MockAdapter


class TestMockAdapterLifecycle:
    """Test MockAdapter start/stop lifecycle (async no-op)."""

    async def test_start_should_not_raise_when_called_first_time(self):
        """start() should complete without errors on first call."""
        adapter = MockAdapter()

        await adapter.start()

        assert adapter._started is True

    async def test_stop_should_not_raise_when_called_without_start(self):
        """stop() should be safe without a prior start()."""
        adapter = MockAdapter()

        await adapter.stop()

        assert adapter._started is False

    async def test_start_should_be_idempotent_when_called_twice(self):
        """Repeated start() calls should be ignored."""
        adapter = MockAdapter()

        await adapter.start()
        await adapter.start()

        assert adapter._started is True

    async def test_stop_should_be_idempotent_when_called_twice(self):
        """Repeated stop() calls should be ignored."""
        adapter = MockAdapter()

        await adapter.start()
        await adapter.stop()
        await adapter.stop()

        assert adapter._started is False

    async def test_lifecycle_should_cycle_when_start_stop_start(self):
        """Adapter should be restartable after stop()."""
        adapter = MockAdapter()

        await adapter.start()
        await adapter.stop()
        await adapter.start()

        assert adapter._started is True

    async def test_stop_should_reset_state_when_called_after_clear(self):
        """clear() must not affect the started flag."""
        adapter = MockAdapter()
        await adapter.start()

        adapter.clear()
        await adapter.stop()

        assert adapter._started is False


class TestMockAdapterContainerIntegration:
    """Test that Container + PlatformContext work in mock mode (no HA_TOKEN)."""

    async def test_platform_context_should_start_and_shutdown_when_no_ha_token(self):
        """ctx.adapter.start() + ctx.shutdown() must not raise without HA_TOKEN."""
        from core.container import Container

        manifest_path = os.path.join(
            os.path.dirname(__file__), "..", "instances", "leonids_house", "manifest.yaml"
        )
        with patch.dict(os.environ, {"HA_TOKEN": ""}, clear=False):
            container = Container(manifest_path=manifest_path)
            ctx = container.build()

            await ctx.adapter.start()
            assert ctx.adapter._started is True

            await ctx.shutdown()
            assert ctx.adapter._started is False

    async def test_shutdown_should_be_idempotent_when_called_twice(self):
        """PlatformContext.shutdown() must be safe to repeat in mock mode."""
        from core.container import Container

        manifest_path = os.path.join(
            os.path.dirname(__file__), "..", "instances", "leonids_house", "manifest.yaml"
        )
        with patch.dict(os.environ, {"HA_TOKEN": ""}, clear=False):
            container = Container(manifest_path=manifest_path)
            ctx = container.build()

            await ctx.shutdown()
            await ctx.shutdown()

            assert ctx.adapter._started is False

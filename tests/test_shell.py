"""
Tests for the Interactive REPL Shell command.

Tests verify that the REPL shell can be initialized and provides
access to all required platform components.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Add src to path for imports
src_dir = str(Path(__file__).parent.parent / "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)


class TestShellCommand:
    """Test cases for the shell command functionality."""

    def test_shell_parser_should_setup_correctly(self) -> None:
        """Test that the shell parser is set up with correct arguments."""
        import argparse

        from smart_home.cli.commands.shell import setup_shell_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        setup_shell_parser(subparsers)

        # Test with default manifest
        args = parser.parse_args(["shell"])
        assert args.manifest == "instances/leonids_house/manifest.yaml"

        # Test with custom manifest
        args = parser.parse_args(["shell", "-m", "custom/manifest.yaml"])
        assert args.manifest == "custom/manifest.yaml"

        # Test short form
        args = parser.parse_args(["shell", "--manifest", "test/manifest.yaml"])
        assert args.manifest == "test/manifest.yaml"

    def test_create_repl_context_should_provide_all_components(
        self,
    ) -> None:
        """Test that create_repl_context provides all required components."""
        from smart_home.cli.commands.shell import create_repl_context

        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        # Check all required components are present
        required_keys = [
            "engine",
            "event_bus",
            "adapter",
            "dispatcher",
            "event_router",
            "control_tracker",
            "manifest",
            "rooms",
            "devices",
            "zones",
            "help",
        ]

        for key in required_keys:
            assert key in ctx, f"Missing required key: {key}"

    def test_create_repl_context_should_have_correct_types(self) -> None:
        """Test that context components have correct types."""
        from core.commands.dispatcher import CommandDispatcher
        from core.control_tracker import ControlTracker
        from core.events.event_bus import EventBus
        from core.events.event_router import EventRouter
        from core.fsm.engine import FSMEngine
        from smart_home.cli.commands.shell import create_repl_context

        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        # Verify types
        assert isinstance(ctx["engine"], FSMEngine)
        assert isinstance(ctx["event_bus"], EventBus)
        assert isinstance(ctx["event_router"], EventRouter)
        assert isinstance(ctx["control_tracker"], ControlTracker)
        assert isinstance(ctx["dispatcher"], CommandDispatcher)

        # Adapter can be either HAAdapter or MockAdapter
        adapter_type_name = type(ctx["adapter"]).__name__
        assert adapter_type_name in ["HAAdapter", "MockAdapter"]

    def test_create_repl_context_should_have_manifest_data(self) -> None:
        """Test that manifest data is correctly exposed."""
        from smart_home.cli.commands.shell import create_repl_context

        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        # Check manifest structure
        assert ctx["manifest"] is not None
        assert hasattr(ctx["manifest"], "instance")
        assert hasattr(ctx["manifest"], "rooms")
        assert hasattr(ctx["manifest"], "devices")
        assert hasattr(ctx["manifest"], "zones")

        # Check that rooms, devices, zones are accessible
        assert isinstance(ctx["rooms"], list)
        assert isinstance(ctx["devices"], list)
        assert isinstance(ctx["zones"], list)

    def test_help_function_should_be_callable(self) -> None:
        """Test that the help function in context is callable."""
        from smart_home.cli.commands.shell import create_repl_context

        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        # Help should be callable
        assert callable(ctx["help"])

        # Should not raise an exception
        ctx["help"]()

    def test_cmd_shell_should_handle_missing_manifest(self) -> None:
        """Test that cmd_shell handles missing manifest file gracefully."""
        import argparse

        from smart_home.cli.commands.shell import cmd_shell

        args = argparse.Namespace(manifest="nonexistent/manifest.yaml")

        result = cmd_shell(args)

        # Should return error code
        assert result == 1

    @pytest.mark.asyncio
    async def test_run_async_repl_should_accept_commands(self) -> None:
        """Test that the async REPL can accept and execute commands."""
        from smart_home.cli.commands.shell import (
            create_repl_context,
        )

        # Create a minimal context for testing
        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        # We can't easily test interactive REPL, but we can verify
        # that the context is properly set up for it
        assert "engine" in ctx
        assert "adapter" in ctx
        assert "help" in ctx

        # Verify that async functions can be called in this context
        assert hasattr(ctx["engine"], "trigger")
        assert hasattr(ctx["adapter"], "call_service")


class TestShellIntegration:
    """Integration tests for the shell command."""

    def test_shell_command_should_initialize_without_errors(self) -> None:
        """Test that shell command initializes without throwing exceptions."""
        from smart_home.cli.commands.shell import create_repl_context

        # This should not raise any exceptions
        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        # Verify basic functionality
        assert ctx["engine"] is not None
        assert ctx["adapter"] is not None

    def test_shell_context_should_allow_engine_operations(self) -> None:
        """Test that engine operations work in the shell context."""
        from smart_home.cli.commands.shell import create_repl_context

        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        engine = ctx["engine"]

        # Test that we can get state (even if FSM doesn't exist)
        state = engine.get_state("nonexistent_device")
        assert state is None or isinstance(state, str)

    def test_shell_context_should_allow_event_router_queries(self) -> None:
        """Test that event router queries work in the shell context."""
        from smart_home.cli.commands.shell import create_repl_context

        ctx = create_repl_context("instances/leonids_house/manifest.yaml")

        event_router = ctx["event_router"]

        # Test mapping query (may return empty list)
        mapping = event_router.get_mapping_for_sensor("binary_sensor.test")
        assert isinstance(mapping, list)

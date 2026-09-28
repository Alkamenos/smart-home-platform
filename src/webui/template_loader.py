"""FSM template loader and parser for Web UI."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


class TemplateParameter:
    """FSM template parameter definition."""

    def __init__(
        self,
        name: str,
        param_type: str,
        description: str = "",
        required: bool = True,
        default: Any = None,
        example: str | None = None,
    ) -> None:
        """Initialize parameter.

        Args:
            name: Parameter name.
            param_type: Parameter type (string, number, integer, boolean, etc).
            description: Human-readable description.
            required: Whether parameter is required.
            default: Default value if not provided.
            example: Example value.
        """
        self.name = name
        self.param_type = param_type
        self.description = description
        self.required = required
        self.default = default
        self.example = example

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "type": self.param_type,
            "description": self.description,
            "required": self.required,
        }
        if self.default is not None:
            result["default"] = self.default
        if self.example is not None:
            result["example"] = self.example
        return result


class FSMTemplate:
    """FSM template with metadata and parameters."""

    def __init__(
        self,
        name: str,
        path: Path,
        description: str = "",
        initial_state: str = "",
        states: list[str] | None = None,
        parameters: dict[str, TemplateParameter] | None = None,
    ) -> None:
        """Initialize template.

        Args:
            name: Template name (filename without .yaml).
            path: Path to template YAML file.
            description: Template description.
            initial_state: Initial FSM state.
            states: Available FSM states.
            parameters: Parameter definitions.
        """
        self.name = name
        self.path = path
        self.description = description
        self.initial_state = initial_state
        self.states = states or []
        self.parameters = parameters or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "initial_state": self.initial_state,
            "states": self.states,
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
        }


class TemplateLoader:
    """Loads and parses FSM templates from features directory."""

    def __init__(self, features_dir: Path | str | None = None) -> None:
        """Initialize loader.

        Args:
            features_dir: Path to features directory. If None, uses default.
        """
        if features_dir is None:
            self.features_dir = Path(__file__).parent.parent / "features"
        else:
            self.features_dir = Path(features_dir)

        if not self.features_dir.exists():
            logger.warning(f"Features directory not found: {self.features_dir}")

    def load_all(self) -> dict[str, FSMTemplate]:
        """Load all templates from features directory.

        Returns:
            Dictionary mapping template name to FSMTemplate object.
        """
        templates: dict[str, FSMTemplate] = {}

        if not self.features_dir.exists():
            logger.warning(f"Features directory does not exist: {self.features_dir}")
            return templates

        for yaml_file in sorted(self.features_dir.glob("*.yaml")):
            template_name = yaml_file.stem
            try:
                template = self._load_template(yaml_file)
                if template:
                    templates[template_name] = template
                    logger.debug(f"Loaded template: {template_name}")
            except Exception as e:
                logger.error(f"Failed to load template {yaml_file}: {e}")

        return templates

    def _load_template(self, path: Path) -> FSMTemplate | None:
        """Load and parse a single template.

        Args:
            path: Path to template YAML file.

        Returns:
            FSMTemplate object or None if parsing fails.
        """
        try:
            with open(path) as f:
                content = f.read()

            # Parse YAML to get metadata
            yaml_data = yaml.safe_load(content)
            if not yaml_data:
                return None

            template_name = path.stem

            # Extract YAML metadata
            initial_state = yaml_data.get("initial_state", "")
            states = yaml_data.get("states", [])

            # Extract description and parameters from comments
            description, parameters = self._extract_metadata_from_comments(content)

            template = FSMTemplate(
                name=template_name,
                path=path,
                description=description,
                initial_state=initial_state,
                states=states,
                parameters=parameters,
            )

            return template
        except Exception as e:
            logger.error(f"Error loading template {path}: {e}")
            return None

    @staticmethod
    def _extract_metadata_from_comments(content: str) -> tuple[str, dict[str, TemplateParameter]]:
        """Extract description and parameters from YAML comments.

        Args:
            content: Raw YAML file content.

        Returns:
            Tuple of (description, parameters_dict).
        """
        lines = content.split("\n")
        description_lines = []
        parameters: dict[str, TemplateParameter] = {}

        # Two-pass approach:
        # 1. Extract description (first comment block before ПАРАМЕТРЫ)
        # 2. Extract parameters (lines starting with "-" between ПАРАМЕТРЫ and ПРИМЕР)

        in_params_section = False
        current_param: dict[str, str] | None = None

        for line in lines:
            # Stop processing at non-comment lines
            if not line.strip().startswith("#"):
                if current_param:
                    param = TemplateLoader._create_parameter(current_param)
                    if param:
                        parameters[param.name] = param
                    current_param = None
                if not in_params_section and not description_lines:
                    break
                continue

            # Remove comment marker and get text
            comment_text = line.lstrip("#").strip()

            # Skip empty comment lines
            if not comment_text:
                continue

            # Detect section markers
            is_params_marker = (
                "ПАРАМЕТРЫ" in comment_text or "PARAMETERS" in comment_text
            ) and "ПРИМЕР" not in comment_text
            is_example_marker = "ПРИМЕР" in comment_text or "EXAMPLE" in comment_text

            if is_params_marker:
                # Entering parameters section
                in_params_section = True
                continue

            if is_example_marker:
                # Exiting parameters section
                if current_param:
                    param = TemplateLoader._create_parameter(current_param)
                    if param:
                        parameters[param.name] = param
                    current_param = None
                in_params_section = False
                continue

            if in_params_section:
                # Parse parameters
                if comment_text.startswith("-"):
                    # New parameter definition
                    if current_param:
                        param = TemplateLoader._create_parameter(current_param)
                        if param:
                            parameters[param.name] = param

                    current_param = {"line": comment_text}
                elif current_param is not None:
                    # Continue parameter description
                    if "description" not in current_param:
                        current_param["description"] = comment_text
                    else:
                        current_param["description"] += " " + comment_text
            else:
                # Collect description lines before ПАРАМЕТРЫ
                if not description_lines and "ПАРАМЕТРЫ" not in comment_text:
                    description_lines.append(comment_text)
                elif description_lines and not in_params_section:
                    # Only continue adding description if we haven't hit ПАРАМЕТРЫ yet
                    description_lines.append(comment_text)

        # Save last parameter if any
        if current_param:
            param = TemplateLoader._create_parameter(current_param)
            if param:
                parameters[param.name] = param

        # Combine description lines, stop at first paragraph break
        description_text = []
        for line in description_lines:
            if not line:
                break
            description_text.append(line)

        description = " ".join(description_text).strip()
        return description, parameters

    @staticmethod
    def _create_parameter(param_dict: dict[str, str]) -> TemplateParameter | None:
        """Create TemplateParameter from parsed comment dictionary.

        Args:
            param_dict: Dictionary with parameter metadata.

        Returns:
            TemplateParameter object or None.
        """
        line = param_dict.get("line", "")
        description = param_dict.get("description", "")

        # Parse: "- name: str - Description (optional: default, example: value)"
        pattern = r"-\s*(\w+):\s*(\w+)\s*(?:-\s*(.*))?$"
        match = re.match(pattern, line)

        if not match:
            return None

        name = match.group(1)
        param_type = match.group(2)
        details = match.group(3) or description

        # Extract default and example from details
        default = None
        example = None

        # Look for "(optional: default_value)"
        default_match = re.search(r"\(optional:\s*([^,)]+)", details)
        if default_match:
            default_str = default_match.group(1).strip()
            # Try to convert to appropriate type
            if param_type == "integer":
                try:
                    default = int(default_str)
                except ValueError:
                    default = default_str
            elif param_type in ("number", "float"):
                try:
                    default = float(default_str)
                except ValueError:
                    default = default_str
            else:
                default = default_str

        # Look for "example: value"
        example_match = re.search(r"example:\s*([^\)]+)", details)
        if example_match:
            example = example_match.group(1).strip()

        required = "(optional" not in details

        return TemplateParameter(
            name=name,
            param_type=param_type,
            description=description or details,
            required=required,
            default=default,
            example=example,
        )


def get_template_loader(features_dir: Path | str | None = None) -> TemplateLoader:
    """Get a template loader instance.

    Args:
        features_dir: Optional custom features directory path.

    Returns:
        TemplateLoader instance.
    """
    return TemplateLoader(features_dir)

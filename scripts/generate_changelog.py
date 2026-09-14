#!/usr/bin/env python3
"""
Changelog generator for Smart Home FSM Platform.

Parses conventional commits and generates CHANGELOG.md in Keep a Changelog format.

Usage:
    python scripts/generate_changelog.py [--version VERSION] [--output OUTPUT]
"""

import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional


# Conventional commit types mapping to changelog sections
COMMIT_TYPE_MAP = {
    "feat": "Added",
    "fix": "Fixed",
    "refactor": "Changed",
    "docs": "Documentation",
    "test": "Testing",
    "chore": "Maintenance",
    "ci": "CI/CD",
    "perf": "Performance",
    "style": "Style",
}

# Commit type descriptions for changelog
TYPE_DESCRIPTIONS = {
    "feat": "Новые функции",
    "fix": "Исправления",
    "refactor": "Рефакторинг",
    "docs": "Документация",
    "test": "Тесты",
    "chore": "Обслуживание",
    "ci": "CI/CD",
    "perf": "Производительность",
    "style": "Стиль кода",
}


def get_git_log(from_tag: Optional[str] = None) -> list[str]:
    """Get git log with conventional commit messages."""
    cmd = ["git", "log", "--pretty=format:%s", "--no-merges"]
    if from_tag:
        cmd.insert(2, f"{from_tag}..HEAD")
    
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip().split("\n") if result.stdout.strip() else []


def parse_commit_message(message: str) -> tuple[Optional[str], str]:
    """
    Parse conventional commit message.
    
    Returns:
        Tuple of (commit_type, description) or (None, message) if not conventional.
    """
    pattern = r"^(feat|fix|refactor|docs|test|chore|ci|perf|style)(?:\(([^)]+)\))?:\s*(.+)"
    match = re.match(pattern, message.strip())
    
    if match:
        commit_type = match.group(1)
        scope = match.group(2)
        description = match.group(3)
        
        # Include scope if present
        if scope:
            description = f"{scope}: {description}"
        
        return commit_type, description
    
    return None, message


def group_commits_by_type(commits: list[str]) -> dict[str, list[str]]:
    """Group commits by their conventional commit type."""
    grouped: dict[str, list[str]] = defaultdict(list)
    uncategorized: list[str] = []
    
    for commit in commits:
        commit_type, description = parse_commit_message(commit)
        
        if commit_type and commit_type in COMMIT_TYPE_MAP:
            grouped[COMMIT_TYPE_MAP[commit_type]].append(description)
        else:
            uncategorized.append(commit)
    
    # Add uncategorized commits to a separate section
    if uncategorized:
        grouped["Other"] = uncategorized
    
    return grouped


def generate_changelog_section(
    version: str,
    date_str: str,
    commits: list[str],
    is_unreleased: bool = False,
) -> str:
    """Generate a changelog section for a specific version."""
    lines: list[str] = []
    
    if is_unreleased:
        lines.append("## [Unreleased]")
        lines.append("")
    else:
        lines.append(f"## [{version}] - {date_str}")
        lines.append("")
    
    grouped = group_commits_by_type(commits)
    
    # Order sections logically
    section_order = ["Added", "Fixed", "Changed", "Documentation", "Testing", "Maintenance", "Other"]
    
    for section in section_order:
        if section in grouped and grouped[section]:
            lines.append(f"### {section}")
            lines.append("")
            for item in sorted(set(grouped[section])):
                lines.append(f"- {item}")
            lines.append("")
    
    return "\n".join(lines)


def read_existing_changelog(path: Path) -> tuple[str, str]:
    """
    Read existing changelog and split into header and versions.
    
    Returns:
        Tuple of (header, versions_content)
    """
    if not path.exists():
        return "# Changelog\n\nAll notable changes to this project will be documented in this file.\n\nThe format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),\nand this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n\n", ""
    
    content = path.read_text(encoding="utf-8")
    
    # Find the first version section
    match = re.search(r"\n## \[", content)
    if match:
        header = content[: match.start() + 1]
        versions = content[match.start() + 1 :]
    else:
        header = content
        versions = ""
    
    return header, versions


def get_last_version_tag() -> Optional[str]:
    """Get the last version tag from git."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() if result.stdout.strip() else None
    except subprocess.CalledProcessError:
        return None


def generate_changelog(
    output_path: Path,
    version: Optional[str] = None,
    include_unreleased: bool = True,
) -> None:
    """Generate complete changelog."""
    header = (
        "# Changelog\n\n"
        "All notable changes to this project will be documented in this file.\n\n"
        "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),\n"
        "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n\n"
    )
    
    # Get commits since last tag (unreleased)
    last_tag = get_last_version_tag()
    unreleased_commits = get_git_log(last_tag) if last_tag else get_git_log()
    
    changelog_parts: list[str] = [header]
    
    # Add Unreleased section
    if include_unreleased and unreleased_commits:
        unreleased_section = generate_changelog_section(
            version="Unreleased",
            date_str="",
            commits=unreleased_commits,
            is_unreleased=True,
        )
        changelog_parts.append(unreleased_section)
    
    # Add existing versions
    existing_header, existing_versions = read_existing_changelog(output_path)
    if existing_versions:
        # Remove any existing Unreleased section from existing versions
        existing_versions = re.sub(
            r"\n## \[Unreleased\].*?(?=\n## \[|\Z)",
            "",
            existing_versions,
            flags=re.DOTALL,
        )
        changelog_parts.append(existing_versions.strip())
    
    # Write changelog
    output_path.write_text("\n".join(changelog_parts) + "\n", encoding="utf-8")
    print(f"✅ Changelog generated: {output_path}")


def main() -> int:
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate CHANGELOG.md from conventional commits"
    )
    parser.add_argument(
        "--version",
        "-v",
        type=str,
        help="Version number for the release (e.g., 3.0.0)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("CHANGELOG.md"),
        help="Output file path (default: CHANGELOG.md)",
    )
    parser.add_argument(
        "--no-unreleased",
        action="store_true",
        help="Don't include Unreleased section",
    )
    
    args = parser.parse_args()
    
    try:
        generate_changelog(
            output_path=args.output,
            version=args.version,
            include_unreleased=not args.no_unreleased,
        )
        return 0
    except subprocess.CalledProcessError as e:
        print(f"❌ Git error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

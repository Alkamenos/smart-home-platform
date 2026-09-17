#!/usr/bin/env python3
"""
Sync script: Generate human-readable ROADMAP.md from .ai/03_ROADMAP.md
AND auto-update task status based on code files presence.

Usage:
    python .ai/scripts/sync_roadmap.py [--check-only] [--auto-update]

Input:  .ai/03_ROADMAP.md (machine-readable)
Output: ROADMAP.md (human-readable with Mermaid diagrams)

Options:
    --check-only   Check if ROADMAP is in sync with code, exit 1 if not
    --auto-update  Auto-update ROADMAP based on code files presence
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path


def parse_roadmap(content: str) -> list[tuple[str, str, list[str]]]:
    """
    Parse machine-readable roadmap into sections.

    Returns:
        List of (section_name, status, items) tuples
    """
    lines = content.split("\n")

    sections = []
    current_section = None
    current_status = None
    current_items = []

    for line in lines:
        # Detect section header (## Phase X: Name [STATUS])
        if line.startswith("## "):
            if current_section:
                sections.append((current_section, current_status, current_items))

            header = line[3:].strip()

            # Extract status from [STATUS]
            status_match = re.search(r"\[(.+?)\]", header)
            if status_match:
                current_status = status_match.group(1).upper()
                current_section = re.sub(r"\s*\[.+?\]", "", header).strip()
            else:
                current_section = header
                current_status = "UNKNOWN"

            current_items = []

        # Collect items (tasks, debt, etc.)
        elif line.startswith("- [") and current_section:
            current_items.append(line.strip())
        elif line.startswith("### ") and current_section:
            # Sub-sections (like "High Priority" in Technical Debt)
            current_items.append(line.strip())
        elif line.strip() and current_section and not line.startswith("#"):
            # Other content (descriptions, etc.)
            if line.strip().startswith("-"):
                current_items.append(line.strip())

    if current_section:
        sections.append((current_section, current_status, current_items))

    return sections


def sanitize_task_name(name: str) -> str:
    """
    Sanitize task name for Mermaid.
    Remove characters that can break Mermaid syntax.
    """
    # Remove colons, replace with dash
    name = name.replace(":", "-")
    # Remove square brackets
    name = name.replace("[", "").replace("]", "")
    # Remove multiple spaces
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def generate_mermaid(sections: list[tuple[str, str, list[str]]]) -> str:
    """Generate Mermaid gantt chart from sections."""
    lines = [
        "```mermaid",
        "gantt",
        "    title Development Timeline",
        "    dateFormat YYYY-MM-DD",
        "",
    ]

    # Start date for roadmap
    base_date = datetime(2026, 9, 5)
    phase_counter = 0

    for section, status, _items in sections:
        # Skip non-phase sections
        if "Phase" not in section:
            continue

        phase_counter += 1

        # Determine status for gantt
        if "COMPLETED" in status:
            gantt_status = "done"
        elif "IN PROGRESS" in status:
            gantt_status = "active"
        else:
            gantt_status = ""

        # Sanitize section name for Mermaid
        safe_section = sanitize_task_name(section)

        # Add section
        lines.append(f"    section {safe_section}")

        # Calculate dates using datetime (avoids invalid dates)
        start_date = base_date + timedelta(days=(phase_counter - 1) * 7)
        end_date = start_date + timedelta(days=5)

        # Format dates as YYYY-MM-DD
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # Build task line
        # Format: TaskName :status, id, start, end
        task_name = sanitize_task_name(section)

        if gantt_status:
            task_line = f"    {task_name} :{gantt_status}, p{phase_counter}, {start_str}, {end_str}"
        else:
            # For planned tasks, don't specify status
            task_line = f"    {task_name} :p{phase_counter}, {start_str}, {end_str}"

        lines.append(task_line)
        lines.append("")

    lines.append("```")
    return "\n".join(lines)


def format_section_header(section: str, status: str) -> str:
    """Format section header with emoji based on status."""
    # Determine emoji based on status
    if "COMPLETED" in status:
        emoji = "✅"
    elif "IN PROGRESS" in status:
        emoji = "🔄"
    elif "PLANNED" in status:
        emoji = "📋"
    elif "FUTURE" in status:
        emoji = "🔮"
    else:
        emoji = "📌"

    return f"## {emoji} {section}"


def format_item(item: str) -> str:
    """Format a single item (checkbox, sub-section, etc.)."""
    # Convert checkbox format
    if item.startswith("- [x]"):
        return f"- ✅ {item[6:].strip()}"
    elif item.startswith("- [ ]"):
        return f"- [ ] {item[6:].strip()}"
    elif item.startswith("### "):
        return f"\n{item}"
    else:
        return item


def generate_markdown(sections: list[tuple[str, str, list[str]]]) -> str:
    """Generate human-readable markdown from sections."""
    output = ["# 🗺 Smart Home Platform Roadmap\n"]
    output.append(
        "*Автоматически сгенерировано из `.ai/03_ROADMAP.md`. Не редактировать вручную.*\n"
    )

    # Add mermaid chart
    try:
        mermaid = generate_mermaid(sections)
        output.append(mermaid)
        output.append("")
    except Exception as e:
        # If mermaid generation fails, skip it
        output.append(f"*Mermaid diagram generation failed: {e}*\n")

    # Add sections
    for section, status, items in sections:
        # Format header
        header = format_section_header(section, status)
        output.append(header)
        output.append("")

        # Add status badge if available
        if status and status != "UNKNOWN":
            output.append(f"**Status:** {status}\n")

        # Add items
        for item in items:
            formatted = format_item(item)
            output.append(formatted)

        output.append("")

    return "\n".join(output)


def check_task_files(task_line: str) -> tuple[bool, bool]:
    """
    Check if code files exist for a task.

    Args:
        task_line: A task line from ROADMAP (e.g., "- [x] Web UI... Files: `src/webui/app.py`...")

    Returns:
        Tuple of (has_code_files, all_files_exist)
    """
    # Extract file references from the task line
    files_match = re.search(r"Files?:\s*`([^`]+)`", task_line, re.IGNORECASE)
    if not files_match:
        # No files specified, can't check
        return False, False

    files_str = files_match.group(1)
    # Split by comma or space
    files = [f.strip() for f in re.split(r"[,\s]+", files_str) if f.strip()]

    if not files:
        return False, False

    # Check if each file exists
    all_exist = True
    for file_path in files:
        # Clean up file path (remove extra backticks, quotes, etc.)
        file_path = file_path.strip("`'\"")
        if not Path(file_path).exists():
            all_exist = False
            break

    return True, all_exist


def update_roadmap_status(content: str) -> tuple[str, bool]:
    """
    Update task status in ROADMAP based on code files presence.

    Rules:
    - If all files mentioned in task exist AND task is [ ], mark as [x]
    - If task is [x] but files don't exist, keep as [x] (manual override)

    Returns:
        Tuple of (updated_content, was_updated)
    """
    lines = content.split("\n")
    updated = False
    new_lines = []

    for line in lines:
        # Only process task lines that are not yet completed
        if line.strip().startswith("- [ ]"):
            has_files, all_exist = check_task_files(line)

            if has_files and all_exist:
                # Mark task as completed
                new_line = line.replace("- [ ]", "- [x]", 1)
                new_lines.append(new_line)
                updated = True

                # Extract task name for logging
                task_name = line[6:].split("Files")[0].split("Detail")[0].strip()
                print(f"  ✅ Auto-marked as completed: {task_name[:60]}...")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    return "\n".join(new_lines), updated


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Sync ROADMAP with code files")
    parser.add_argument(
        "--check-only", action="store_true", help="Check if ROADMAP is in sync, exit 1 if not"
    )
    parser.add_argument(
        "--auto-update", action="store_true", help="Auto-update ROADMAP based on code files"
    )
    args = parser.parse_args()

    input_path = Path(".ai/03_ROADMAP.md")
    output_path = Path("ROADMAP.md")

    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return 1

    try:
        content = input_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"❌ Failed to read {input_path}: {e}")
        return 1

    try:
        # Auto-update task statuses if requested
        if args.auto_update:
            print("🔄 Checking task completion status based on code files...")
            content, was_updated = update_roadmap_status(content)
            if was_updated:
                print("✅ ROADMAP updated with completed tasks")
                # Write updated content back to source file
                input_path.write_text(content, encoding="utf-8")
            else:
                print("ℹ️  No automatic updates needed")

        sections = parse_roadmap(content)

        if not sections:
            print("❌ No sections found in roadmap")
            return 1

        # Check-only mode: verify ROADMAP is up to date
        if args.check_only:
            # Generate expected output and compare
            expected_markdown = generate_markdown(sections)

            if output_path.exists():
                actual_markdown = output_path.read_text(encoding="utf-8")
                if expected_markdown == actual_markdown:
                    print("✅ ROADMAP.md is in sync")
                    return 0
                else:
                    print("⚠️  ROADMAP.md is out of sync")
                    return 1
            else:
                print("⚠️  ROADMAP.md does not exist")
                return 1

        # Normal mode: generate/update ROADMAP.md
        markdown = generate_markdown(sections)

        output_path.write_text(markdown, encoding="utf-8")

        print(f"✅ Generated {output_path} from {input_path}")
        print(f"   Sections found: {len(sections)}")
        for section, status, items in sections:
            print(f"   - {section} [{status}]: {len(items)} items")

        return 0

    except Exception as e:
        print(f"❌ Error generating roadmap: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())

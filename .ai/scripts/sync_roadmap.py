#!/usr/bin/env python3
"""
Sync script: Generate human-readable ROADMAP.md from .ai/03_ROADMAP.md

Usage:
    python .ai/scripts/sync_roadmap.py

Input:  .ai/03_ROADMAP.md (machine-readable)
Output: ROADMAP.md (human-readable with Mermaid diagrams)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional


def parse_roadmap(content: str) -> List[Tuple[str, str, List[str]]]:
    """
    Parse machine-readable roadmap into sections.

    Returns:
        List of (section_name, status, items) tuples
    """
    lines = content.split('\n')

    sections = []
    current_section = None
    current_status = None
    current_items = []

    for line in lines:
        # Detect section header (## Phase X: Name [STATUS])
        if line.startswith('## '):
            if current_section:
                sections.append((current_section, current_status, current_items))

            header = line[3:].strip()

            # Extract status from [STATUS]
            status_match = re.search(r'\[(.+?)\]', header)
            if status_match:
                current_status = status_match.group(1).upper()
                current_section = re.sub(r'\s*\[.+?\]', '', header).strip()
            else:
                current_section = header
                current_status = 'UNKNOWN'

            current_items = []

        # Collect items (tasks, debt, etc.)
        elif line.startswith('- [') and current_section:
            current_items.append(line.strip())
        elif line.startswith('### ') and current_section:
            # Sub-sections (like "High Priority" in Technical Debt)
            current_items.append(line.strip())
        elif line.strip() and current_section and not line.startswith('#'):
            # Other content (descriptions, etc.)
            if line.strip().startswith('-'):
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
    name = name.replace(':', '-')
    # Remove square brackets
    name = name.replace('[', '').replace(']', '')
    # Remove multiple spaces
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def generate_mermaid(sections: List[Tuple[str, str, List[str]]]) -> str:
    """Generate Mermaid gantt chart from sections."""
    lines = [
        '```mermaid',
        'gantt',
        '    title Development Timeline',
        '    dateFormat YYYY-MM-DD',
        ''
    ]

    # Start date for roadmap
    base_date = datetime(2026, 9, 5)
    phase_counter = 0

    for section, status, items in sections:
        # Skip non-phase sections
        if 'Phase' not in section:
            continue

        phase_counter += 1

        # Determine status for gantt
        if 'COMPLETED' in status:
            gantt_status = 'done'
        elif 'IN PROGRESS' in status:
            gantt_status = 'active'
        else:
            gantt_status = ''

        # Sanitize section name for Mermaid
        safe_section = sanitize_task_name(section)

        # Add section
        lines.append(f'    section {safe_section}')

        # Calculate dates using datetime (avoids invalid dates)
        start_date = base_date + timedelta(days=(phase_counter - 1) * 7)
        end_date = start_date + timedelta(days=5)

        # Format dates as YYYY-MM-DD
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        # Build task line
        # Format: TaskName :status, id, start, end
        task_name = sanitize_task_name(section)

        if gantt_status:
            task_line = f'    {task_name} :{gantt_status}, p{phase_counter}, {start_str}, {end_str}'
        else:
            # For planned tasks, don't specify status
            task_line = f'    {task_name} :p{phase_counter}, {start_str}, {end_str}'

        lines.append(task_line)
        lines.append('')

    lines.append('```')
    return '\n'.join(lines)


def format_section_header(section: str, status: str) -> str:
    """Format section header with emoji based on status."""
    # Determine emoji based on status
    if 'COMPLETED' in status:
        emoji = '✅'
    elif 'IN PROGRESS' in status:
        emoji = '🔄'
    elif 'PLANNED' in status:
        emoji = '📋'
    elif 'FUTURE' in status:
        emoji = '🔮'
    else:
        emoji = '📌'

    return f'## {emoji} {section}'


def format_item(item: str) -> str:
    """Format a single item (checkbox, sub-section, etc.)."""
    # Convert checkbox format
    if item.startswith('- [x]'):
        return f'- ✅ {item[6:].strip()}'
    elif item.startswith('- [ ]'):
        return f'- [ ] {item[6:].strip()}'
    elif item.startswith('### '):
        return f'\n{item}'
    else:
        return item


def generate_markdown(sections: List[Tuple[str, str, List[str]]]) -> str:
    """Generate human-readable markdown from sections."""
    output = ['# 🗺 Smart Home Platform Roadmap\n']
    output.append('*Автоматически сгенерировано из `.ai/03_ROADMAP.md`. Не редактировать вручную.*\n')

    # Add mermaid chart
    try:
        mermaid = generate_mermaid(sections)
        output.append(mermaid)
        output.append('')
    except Exception as e:
        # If mermaid generation fails, skip it
        output.append(f'*Mermaid diagram generation failed: {e}*\n')

    # Add sections
    for section, status, items in sections:
        # Format header
        header = format_section_header(section, status)
        output.append(header)
        output.append('')

        # Add status badge if available
        if status and status != 'UNKNOWN':
            output.append(f'**Status:** {status}\n')

        # Add items
        for item in items:
            formatted = format_item(item)
            output.append(formatted)

        output.append('')

    return '\n'.join(output)


def main():
    """Main function."""
    input_path = Path('.ai/03_ROADMAP.md')
    output_path = Path('ROADMAP.md')

    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        return 1

    try:
        content = input_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"❌ Failed to read {input_path}: {e}")
        return 1

    try:
        sections = parse_roadmap(content)

        if not sections:
            print("❌ No sections found in roadmap")
            return 1

        markdown = generate_markdown(sections)

        output_path.write_text(markdown, encoding='utf-8')

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


if __name__ == '__main__':
    exit(main())

#!/bin/bash
# Generate documentation for Smart Home FSM Platform

set -e

echo "📚 Generating Documentation..."

OUTPUT_DIR=${1:-docs/generated}

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Generate API documentation using interrogate or pdoc
if command -v pdoc &> /dev/null; then
    echo "Generating API docs with pdoc..."
    pdoc --output-dir "$OUTPUT_DIR/api" src/smart_home
fi

# Generate markdown from docstrings
echo "Generating markdown documentation..."
python -c "
import os
from pathlib import Path

src_dir = Path('src/smart_home')
output_file = Path('$OUTPUT_DIR/modules.md')

with open(output_file, 'w') as f:
    f.write('# Smart Home FSM Platform Modules\n\n')
    
    for py_file in src_dir.rglob('*.py'):
        if py_file.name.startswith('_'):
            continue
            
        rel_path = py_file.relative_to(src_dir)
        f.write(f'## {rel_path}\n\n')
        
        with open(py_file) as src:
            content = src.read()
            # Extract module docstring
            if content.startswith('\"\"\"') or content.startswith(\"'''\"):
                start = 3
                end = content.find(content[:3], start)
                if end != -1:
                    docstring = content[start:end].strip()
                    f.write(f'{docstring}\n\n')
"

echo "✅ Documentation generated in $OUTPUT_DIR"

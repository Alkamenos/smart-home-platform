#!/usr/bin/env python3
"""Символьная проверка pyscript-бандла: ловит NameError-класс до деплоя.

Использование: python tools/check_bundle_symbols.py /tmp/bundle.py [--warn]
"""
import ast
import builtins
import sys

PYSCRIPT_GLOBALS = {
    "state", "service", "task", "log", "hass", "log_event", "pyscript",
    "time_trigger", "state_trigger", "event_trigger", "rpc",
    "time", "datetime", "timedelta", "json", "math", "re",
    "__file__", "__name__",
}


def collect(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    defined = set()
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        defined.add(n.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    defined.add(n.id)
        elif isinstance(node, ast.arguments):
            for a in node.args + node.posonlyargs + node.kwonlyargs:
                defined.add(a.arg)
            if node.vararg:
                defined.add(node.vararg.arg)
            if node.kwarg:
                defined.add(node.kwarg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.comprehension):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    defined.add(n.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            used.add(node.id)
    return used, defined


def main():
    path = sys.argv[1]
    warn_only = "--warn" in sys.argv
    used, defined = collect(path)
    undefined = sorted(used - defined - PYSCRIPT_GLOBALS - set(dir(builtins)))
    if undefined:
        print("UNDEFINED SYMBOLS:", ", ".join(undefined))
        if warn_only:
            print("[warn-mode] not failing")
            return 0
        return 1
    print("✅ bundle symbols OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

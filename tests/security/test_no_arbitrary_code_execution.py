"""Section 5 & 6: the application must never execute shell commands,
arbitrary Python, or dynamically-selected code derived from model/tool
input. Static AST scan across the entire shipped source tree -- covers
test_arbitrary_command_execution_blocked and test_shell_execution_not_allowed."""

from __future__ import annotations

import ast

from tests.security._paths import iter_source_files

_FORBIDDEN_CALL_NAMES = {"eval", "exec", "compile", "__import__"}
_FORBIDDEN_MODULES = {"subprocess", "pty", "commands"}
_FORBIDDEN_OS_ATTRS = {"system", "popen", "spawnl", "spawnv", "exec", "execv", "execve"}


def test_no_eval_exec_or_dynamic_import():
    offenders = []
    for path in iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _FORBIDDEN_CALL_NAMES
            ):
                offenders.append((str(path), node.func.id))
    assert offenders == [], f"Dangerous dynamic-execution call found: {offenders}"


def test_no_subprocess_or_shell_module_imported():
    offenders = []
    for path in iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _FORBIDDEN_MODULES:
                        offenders.append((str(path), alias.name))
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0] in _FORBIDDEN_MODULES
            ):
                offenders.append((str(path), node.module))
    assert offenders == [], f"Shell/subprocess module imported in application code: {offenders}"


def test_no_os_system_or_popen_call():
    offenders = []
    for path in iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _FORBIDDEN_OS_ATTRS
            ):
                offenders.append((str(path), node.func.attr))
    assert offenders == [], f"os.system/popen/exec-family call found: {offenders}"

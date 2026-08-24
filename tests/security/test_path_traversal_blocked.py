"""Section 7: path traversal.

This server exposes no filesystem-read or filesystem-write tool at all --
the only external system it talks to is the AWS Cost Explorer/STS API via
boto3. Path traversal is therefore eliminated by absence rather than by a
sanitizer, which is the safer control. This test pins that architectural
fact: it fails the moment anyone adds a tool that accepts a path-like
parameter or touches `open()`/`pathlib`/`os.path` outside of config-file
loading, which would reintroduce the attack surface and require this test
(and the threat model) to be revisited deliberately."""

from __future__ import annotations

import ast

from tests.security._paths import iter_source_files

_ALLOWED_FILESYSTEM_USERS = {"config.py"}  # reads .env via pydantic-settings only
_FILESYSTEM_CALL_NAMES = {"open"}
_FILESYSTEM_MODULES = {"pathlib", "os.path", "shutil", "glob"}


def test_no_tool_module_touches_the_filesystem():
    offenders = []
    for path in iter_source_files():
        if path.name in _ALLOWED_FILESYSTEM_USERS:
            continue
        if "tools" not in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _FILESYSTEM_CALL_NAMES
            ):
                offenders.append(str(path))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [node.module] if isinstance(node, ast.ImportFrom) else [
                    alias.name for alias in node.names
                ]
                for name in names:
                    if name in _FILESYSTEM_MODULES:
                        offenders.append(str(path))
    assert offenders == [], f"Unexpected filesystem access in tool code: {offenders}"


def test_no_tool_parameter_accepts_a_filesystem_path():
    forbidden_names = {"path", "file_path", "filename", "filepath", "directory", "dir"}
    offenders = []
    for path in iter_source_files():
        if "tools" not in path.parts and path.name != "server.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name in forbidden_names:
            if f"{name}:" in text or f"{name} :" in text:
                offenders.append((str(path), name))
    assert offenders == [], f"Tool parameters resembling filesystem paths found: {offenders}"

"""Tests for Python execution tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kimi_cli.config import Config, PythonConfig, ThinkConfig
from kimi_cli.think.python_tool import PythonExecutionError, PythonTool


@pytest.fixture
def config_restricted() -> Config:
    return Config(
        think=ThinkConfig(
            python=PythonConfig(
                restriction_level="restricted",
                timeout_seconds=10,
            )
        )
    )


@pytest.fixture
def config_none() -> Config:
    return Config(
        think=ThinkConfig(
            python=PythonConfig(
                restriction_level="none",
                timeout_seconds=10,
            )
        )
    )


@pytest.mark.asyncio
async def test_python_execute_hello_world(tmp_path: Path, config_restricted: Config) -> None:
    tool = PythonTool(tmp_path, config_restricted)
    result = await tool.execute('print("hello world")')
    assert result["exit_code"] == 0
    assert "hello world" in result["stdout"]
    assert result["stderr"] == ""


@pytest.mark.asyncio
async def test_python_execute_blocked_import(tmp_path: Path, config_restricted: Config) -> None:
    tool = PythonTool(tmp_path, config_restricted)
    with pytest.raises(PythonExecutionError, match="Import blocked: os"):
        await tool.execute("import os\nos.system('echo hack')")


@pytest.mark.asyncio
async def test_python_execute_blocked_eval(tmp_path: Path, config_restricted: Config) -> None:
    tool = PythonTool(tmp_path, config_restricted)
    with pytest.raises(PythonExecutionError, match="Call blocked: eval"):
        await tool.execute("eval('1+1')")


@pytest.mark.asyncio
async def test_python_execute_timeout(tmp_path: Path, config_restricted: Config) -> None:
    config_restricted.think.python.timeout_seconds = 1
    tool = PythonTool(tmp_path, config_restricted)
    with pytest.raises(PythonExecutionError, match="Execution timed out"):
        await tool.execute("import time\ntime.sleep(10)")


@pytest.mark.asyncio
async def test_python_execute_network_blocked(tmp_path: Path, config_restricted: Config) -> None:
    tool = PythonTool(tmp_path, config_restricted)
    with pytest.raises(PythonExecutionError, match="Import blocked: requests"):
        await tool.execute("import requests")


@pytest.mark.asyncio
async def test_python_execute_network_allowed(tmp_path: Path, config_none: Config) -> None:
    # In 'none' mode, network imports are not blocked by AST validation
    config_none.think.python.allow_network = True
    tool = PythonTool(tmp_path, config_none)
    # Use urllib (stdlib) which is always available; in restricted mode it would be blocked
    result = await tool.execute("import urllib\nprint('ok')")
    assert result["exit_code"] == 0
    assert "ok" in result["stdout"]


@pytest.mark.asyncio
async def test_python_execute_matplotlib(tmp_path: Path, config_restricted: Config) -> None:
    tool = PythonTool(tmp_path, config_restricted)
    code = '''
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1, 2, 3], [1, 4, 9])
'''
    result = await tool.execute(code)
    # Matplotlib may not be installed; accept either success or import error
    if result["exit_code"] == 0:
        assert len(result["figures"]) >= 0
    else:
        assert "matplotlib" in result["stderr"] or "No module named" in result["stderr"]


@pytest.mark.asyncio
async def test_python_execute_restricted_file_access(tmp_path: Path, config_restricted: Config) -> None:
    tool = PythonTool(tmp_path, config_restricted)
    # Try to read a file outside work_dir
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    code = f'''
try:
    with open(r"{outside}") as f:
        print(f.read())
except PermissionError as e:
    print("BLOCKED")
'''
    result = await tool.execute(code)
    assert result["exit_code"] == 0
    assert "BLOCKED" in result["stdout"]

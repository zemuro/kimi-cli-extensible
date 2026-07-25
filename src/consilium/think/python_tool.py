"""Python execution tool for Think mode."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from consilium.config import Config
from consilium.utils.logging import logger


class PythonExecutionError(Exception):
    """Python code execution failed."""


class PythonTool:
    """Execute Python code in a restricted or unrestricted environment."""

    def __init__(self, work_dir: Path, config: Config) -> None:
        self.work_dir = work_dir.resolve()
        self.cfg = config.think.python

    async def execute(self, code: str) -> dict[str, Any]:
        """Execute Python code and return results.

        Returns dict with keys:
            - stdout: str
            - stderr: str
            - exit_code: int
            - figures: list[str]  # paths to saved matplotlib figures
            - duration_ms: int
        """
        if self.cfg.restriction_level == "sandboxed":
            return await self._execute_sandboxed(code)
        elif self.cfg.restriction_level == "restricted":
            return await self._execute_restricted(code)
        else:
            return await self._execute_unrestricted(code)

    async def _execute_unrestricted(self, code: str) -> dict[str, Any]:
        """Run with full user permissions. Same risk as existing shell tool."""
        return await self._run_subprocess(code, restricted=False)

    async def _execute_restricted(self, code: str) -> dict[str, Any]:
        """Run with light restrictions: limited imports, workdir file access only."""
        self._validate_ast(code)
        return await self._run_subprocess(code, restricted=True)

    async def _execute_sandboxed(self, code: str) -> dict[str, Any]:
        """Run inside macOS sandbox-exec (Seatbelt). Falls back to restricted on non-macOS."""
        if sys.platform != "darwin":
            logger.warning("sandboxed mode only available on macOS, falling back to restricted")
            return await self._execute_restricted(code)
        return await self._run_sandboxed(code)

    def _validate_ast(self, code: str) -> None:
        """Parse AST and block dangerous imports / calls."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise PythonExecutionError(f"Syntax error: {e}") from e

        blocked_modules = {"os", "subprocess", "socket", "urllib", "http", "ftplib", "telnetlib"}
        if not self.cfg.allow_network:
            blocked_modules |= {"requests", "aiohttp", "httpx", "urllib3"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in blocked_modules:
                        raise PythonExecutionError(f"Import blocked: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root in blocked_modules:
                        raise PythonExecutionError(f"Import blocked: {node.module}")
            elif isinstance(node, ast.Call):
                # Block eval, exec, compile, __import__
                if isinstance(node.func, ast.Name) and node.func.id in {
                    "eval",
                    "exec",
                    "compile",
                    "__import__",
                }:
                    raise PythonExecutionError(f"Call blocked: {node.func.id}")

    async def _run_subprocess(self, code: str, restricted: bool) -> dict[str, Any]:
        """Run code via subprocess with optional restriction preloader."""
        import time

        start = time.monotonic()

        # Write code to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            if restricted:
                f.write(self._security_prelude())
            f.write("\n")
            f.write(self._matplotlib_prelude())
            f.write("\n")
            f.write(code)
            f.write("\n")
            f.write(self._matplotlib_postlude())
            script_path = f.name

        # Environment
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["CONSILIUM_WORK_DIR"] = str(self.work_dir)
        if restricted:
            env["CONSILIUM_PYTHON_RESTRICTED"] = "1"
            env["PYTHONPATH"] = str(self.work_dir)
            env["PYTHONNOUSERSITE"] = "1"

        try:
            proc = subprocess.run(
                [sys.executable, script_path],
                cwd=self.work_dir if restricted else None,
                capture_output=True,
                text=True,
                timeout=self.cfg.timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise PythonExecutionError(f"Execution timed out after {self.cfg.timeout_seconds}s")
        finally:
            Path(script_path).unlink(missing_ok=True)

        duration_ms = int((time.monotonic() - start) * 1000)

        # Collect matplotlib figures from temp dir
        figures = []
        fig_dir = Path(tempfile.gettempdir()) / "kimi_python_figures"
        if fig_dir.exists():
            for fig in sorted(fig_dir.glob("kimi_fig_*.png")):
                figures.append(str(fig))

        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
            "figures": figures,
            "duration_ms": duration_ms,
        }

    async def _run_sandboxed(self, code: str) -> dict[str, Any]:
        """Run via macOS sandbox-exec wrapper."""
        # macOS sandbox-exec is not implemented in this fork.
        # Fall back to restricted mode.
        logger.warning("sandbox-exec not implemented, falling back to restricted")
        return await self._execute_restricted(code)

    def _security_prelude(self) -> str:
        """Python code injected before user code to restrict file access."""
        return """
import builtins
import os
_original_open = builtins.open
_WORK_DIR = os.environ.get("CONSILIUM_WORK_DIR", ".")

def _restricted_open(path, *args, **kwargs):
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(os.path.abspath(_WORK_DIR)):
        raise PermissionError(f"File access outside work directory blocked: {path}")
    return _original_open(path, *args, **kwargs)

builtins.open = _restricted_open
"""

    def _matplotlib_prelude(self) -> str:
        """Setup matplotlib to save figures instead of displaying."""
        return """
import os, tempfile
os.environ["MPLBACKEND"] = "Agg"
_kimi_fig_dir = os.path.join(tempfile.gettempdir(), "kimi_python_figures")
os.makedirs(_kimi_fig_dir, exist_ok=True)
"""

    def _matplotlib_postlude(self) -> str:
        """Save any open matplotlib figures."""
        return """
try:
    import matplotlib.pyplot as _plt
    for i, fig in enumerate(_plt.get_fignums(), 1):
        _plt.figure(fig).savefig(os.path.join(_kimi_fig_dir, f"kimi_fig_{i:03d}.png"), dpi=150, bbox_inches="tight")
    _plt.close("all")
except Exception:
    pass
"""

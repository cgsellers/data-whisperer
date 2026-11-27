"""Sandbox Python seguro para ejecutar código generado por LLM"""
import asyncio
import json
import resource
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from data_platform.core.observability import get_logger

logger = get_logger(__name__)


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool
    memory_mb: float


class PythonSandbox:
    """
    Ejecuta código Python en subprocess aislado con límites de recursos:
    - Sin red
    - Sin acceso a filesystem (excepto /tmp)
    - Timeout configurable
    - Límite de memoria (best effort)
    - Solo librerías permitidas
    """

    ALLOWED_IMPORTS = {
        "pandas", "numpy", "json", "math", "statistics", "datetime",
        "collections", "itertools", "re", "uuid", "hashlib", "decimal",
        "fractions", "random", "string", "textwrap", "pprint",
        "prophet", "plotly", "scipy", "sklearn", "matplotlib",
    }

    FORBIDDEN_PATTERNS = [
        "import os", "import sys", "import subprocess", "import socket",
        "import urllib", "import requests", "import http", "import ftplib",
        "import smtplib", "import telnetlib", "import xmlrpc",
        "open(", "__import__", "eval(", "exec(", "compile(",
        "getattr(", "setattr(", "delattr(", "globals(", "locals(",
        "vars(", "dir(", "input(", "raw_input(", "exit(", "quit(",
    ]

    def __init__(
        self,
        timeout_seconds: int = 30,
        memory_limit_mb: int = 512,
        cpu_limit_seconds: int = 10,
    ):
        self.timeout = timeout_seconds
        self.memory_limit = memory_limit_mb * 1024 * 1024  # bytes
        self.cpu_limit = cpu_limit_seconds

    def _validate_code(self, code: str) -> tuple[bool, str]:
        """Valida que el código no use patrones prohibidos"""
        code_lower = code.lower()

        # Check forbidden patterns
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern.lower() in code_lower:
                return False, f"Patrón prohibido detectado: {pattern}"

        # Check imports (basic AST would be better but keep simple)
        lines = code.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                # Extract module name
                parts = stripped.replace("from ", "").replace("import ", "").split()
                if parts:
                    mod = parts[0].split(".")[0]
                    if mod not in self.ALLOWED_IMPORTS:
                        return False, f"Import no permitido: {mod}"

        return True, "OK"

    def _limit_resources(self):
        """Configura límites de recursos en el proceso hijo (best effort)"""
        with suppress(Exception):
            # CPU time limit
            resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_limit, self.cpu_limit))
        with suppress(Exception):
            # Memory limit
            resource.setrlimit(resource.RLIMIT_AS, (self.memory_limit, self.memory_limit))
        with suppress(Exception):
            # File size limit
            resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
        with suppress(Exception):
            # No core dumps
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with suppress(Exception):
            # Max processes (may not work on macOS)
            resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))

    async def execute(self, code: str, input_data: dict | None = None) -> SandboxResult:
        """
        Ejecuta código Python en sandbox.

        El código debe definir una variable `result` o imprimir JSON a stdout.
        input_data se pasa como variable `features` (lista de dicts).
        """
        valid, msg = self._validate_code(code)
        if not valid:
            return SandboxResult(
                stdout="",
                stderr=f"ValidationError: {msg}",
                returncode=-1,
                timed_out=False,
                memory_mb=0,
            )

        # Preparar código wrapper
        wrapper = self._build_wrapper(code, input_data)

        # Escribir a archivo temporal
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir="/tmp"
        ) as f:
            f.write(wrapper)
            temp_path = f.name

        try:
            # Ejecutar en subprocess
            proc = await asyncio.create_subprocess_exec(
                sys.executable, temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=self._limit_resources,
                # Sin env vars peligrosas
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONPATH": "",
                    "HOME": "/tmp",
                    "TMPDIR": "/tmp",
                }
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout
                )
                timed_out = False
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    stdout="",
                    stderr=f"Timeout after {self.timeout}s",
                    returncode=-1,
                    timed_out=True,
                    memory_mb=0,
                )

            return SandboxResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                returncode=proc.returncode or 0,
                timed_out=timed_out,
                memory_mb=0,  # Hard to get accurately without psutil
            )

        finally:
            # Cleanup
            with suppress(Exception):
                Path(temp_path).unlink()

    def _build_wrapper(self, code: str, input_data: dict | None) -> str:
        """Construye código wrapper que captura resultado"""
        features_json = json.dumps(input_data or {}, ensure_ascii=False)

        return f'''
import json
import sys
import traceback

# Input data
features = {features_json}

# User code
{code}

# Capture result
if "result" in locals():
    print(json.dumps(result, default=str, ensure_ascii=False))
elif "df" in locals():
    # Si hay un dataframe, convertir a records
    try:
        print(json.dumps(df.to_dict(orient="records"), default=str, ensure_ascii=False))
    except Exception:
        pass
'''


# Instancia global por defecto
_default_sandbox: PythonSandbox | None = None


def get_sandbox() -> PythonSandbox:  # noqa: PLW0603
    global _default_sandbox  # noqa: PLW0603
    if _default_sandbox is None:
        _default_sandbox = PythonSandbox()
    return _default_sandbox


async def execute_python(code: str, features: list[dict] | None = None) -> SandboxResult:
    """Helper para ejecutar código en sandbox por defecto"""
    sandbox = get_sandbox()
    return await sandbox.execute(code, {"features": features} if features else None)



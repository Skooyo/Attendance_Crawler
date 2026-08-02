"""Hermes cron wrapper: weekly Discord digest."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable


def _child_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.upper().startswith("PYTHON"):
            continue
        env[key] = value
    env["PYTHONNOUSERSITE"] = "1"
    return env


def main() -> int:
    result = subprocess.run(
        [PY, "-m", "attendance_crawler", "review", "--days", "7", "--format", "hermes"],
        cwd=str(ROOT),
        env=_child_env(),
        capture_output=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

"""Hermes cron wrapper: weekly collect (FIT2102 + FIT2109 only)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable

# EdStem + Gmail only — ETM1005 has collect_enabled: false in config.yaml
COLLECT_UNITS = "FIT2102,FIT2109"


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
        [
            PY,
            "-m",
            "attendance_crawler",
            "collect",
            "--units",
            COLLECT_UNITS,
        ],
        cwd=str(ROOT),
        env=_child_env(),
        capture_output=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

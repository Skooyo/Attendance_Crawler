from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
AUTH_DIR = ROOT / ".auth"
CONFIG_PATH = ROOT / "config.yaml"
DB_PATH = DATA_DIR / "attendance.db"
MOODLE_STATE_PATH = AUTH_DIR / "moodle.json"
GMAIL_CREDENTIALS_PATH = ROOT / "credentials.json"
GMAIL_TOKEN_PATH = ROOT / "token.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_DIR.mkdir(parents=True, exist_ok=True)

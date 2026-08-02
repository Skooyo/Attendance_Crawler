"""Gmail OAuth — switch accounts by re-running auth after deleting token.json."""

from attendance_crawler.collectors.gmail import _get_gmail_service
from attendance_crawler.paths import GMAIL_CREDENTIALS_PATH, GMAIL_TOKEN_PATH


def auth_gmail_interactive() -> None:
    if not GMAIL_CREDENTIALS_PATH.exists():
        raise SystemExit(
            "credentials.json not found in project root. See README Gmail setup."
        )
    if GMAIL_TOKEN_PATH.exists():
        GMAIL_TOKEN_PATH.unlink()
    _get_gmail_service()
    print(f"Gmail authorized. Token saved to {GMAIL_TOKEN_PATH}")

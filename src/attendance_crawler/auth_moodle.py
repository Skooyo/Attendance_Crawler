"""Moodle session via Playwright storageState."""

from attendance_crawler.config import AppConfig
from attendance_crawler.paths import MOODLE_STATE_PATH, ensure_dirs


def auth_moodle_interactive(config: AppConfig) -> None:
    from playwright.sync_api import sync_playwright

    ensure_dirs()
    base = config.moodle_base_url
    if not base:
        raise SystemExit("Set moodle_base_url in config.yaml or MOODLE_BASE_URL in .env")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base, wait_until="domcontentloaded")
        print(
            "Complete Okta login in the browser window, then press Enter here when Moodle is loaded..."
        )
        input()
        context.storage_state(path=str(MOODLE_STATE_PATH))
        browser.close()
    print(f"Moodle session saved to {MOODLE_STATE_PATH}")


def moodle_session_valid(config: AppConfig) -> bool:
    return MOODLE_STATE_PATH.exists()

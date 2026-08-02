# Attendance Code Crawler

Collect attendance codes from Moodle, EdStem, and Gmail into a local SQLite database, then send a weekly summary to Discord via [Hermes Agent](https://hermes-agent.nousresearch.com/) cron.

## Requirements

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed and on `PATH` (for image codes)
- Playwright Chromium: `playwright install chromium`

## Setup

```powershell
cd D:\Projects\Attendance_Crawler
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium
```

Copy `.env.example` to `.env` and edit `config.yaml` with your units.

### EdStem

1. Create an API token at https://edstem.org/settings/api-tokens (AU: https://edstem.org/au/settings/api-tokens)
2. Set `ED_API_TOKEN` and `ED_REGION=au` in `.env`

### Gmail (FIT2109)

Gmail uses **Google OAuth** — see README. Subject filter example:
`FIT2109 S2 2026 Malaysia : Attendance code ... - Week 1 Workshops and Tutorials`

### OpenRouter (optional LLM extraction)

When regex/OCR miss codes, enable in `config.yaml` under `llm:` and set:

```env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Get a key at https://openrouter.ai/keys


1. **Google Cloud Console** — https://console.cloud.google.com/
2. Create a project (or pick an existing one).
3. **APIs & Services → Library** → search **Gmail API** → **Enable**.
4. **APIs & Services → OAuth consent screen**
   - User type: **External** (or Internal if your org allows it)
   - Add your Google account under **Test users** while the app is in testing mode
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Download JSON
6. Save the downloaded file as **`credentials.json`** in the project root:
   `D:\Projects\Attendance_Crawler\credentials.json`
7. Run collect — a browser opens for Google sign-in:

```powershell
python -m attendance_crawler collect
```

8. After you approve, **`token.json`** is created locally. Future collects reuse it until it expires.

If you see `credentials.json not found`, the file is missing or not in the project root. If OAuth fails with “access blocked”, add your account as a test user on the consent screen.

### Moodle (Okta)

```powershell
python -m attendance_crawler auth moodle
```

Complete Okta Verify (push or code) in the browser, then press Enter. Session is saved to `.auth/moodle.json`.

## CLI

```powershell
# All units with collect_enabled: true (ETM1005 is disabled in config)
python -m attendance_crawler collect

# Only FIT2102 (EdStem) + FIT2109 (Gmail)
python -m attendance_crawler collect --units FIT2102,FIT2109

python -m attendance_crawler review --days 7 --format markdown
python -m attendance_crawler review --days 7 --format hermes
```

Set `collect_enabled: false` on a unit in `config.yaml` to skip it during normal `collect` (ETM1005 is already disabled).

### Only your tutorial/workshop sessions (`my_sessions`)

Each unit can list the **session numbers** between the date and time in the digest line (`Tutorial | Friday, 31 Jul | **03** | 10:00AM | CODE`):

```yaml
  - code: FIT2102
    my_sessions:
      tutorial: ["01", "02", "09"]
      workshop: ["01"]
```

`review` and the Hermes weekly digest apply this filter automatically. Omit `my_sessions` (or leave a type out) to show all sessions of that type for that unit. Use `--all-sessions` to bypass filters for a one-off full dump.

## Hermes: weekly scrape + Discord digest

Prerequisites: Hermes gateway running with Discord connected.

**Two cron jobs** (script-only, no LLM tokens):

| Job | Schedule (example) | Script | Delivery |
|-----|-------------------|--------|----------|
| Collect FIT2102 + FIT2109 | Sunday 5:30pm | `attendance_collect_weekly.py` in Hermes scripts dir (see below) | `local` |
| Last 7 days digest | Sunday 6:00pm | `attendance_review_weekly.py` in Hermes scripts dir | `discord` |

```bash
hermes cron create "30 17 * * 0" \
  --name "Attendance collect weekly" \
  --script attendance_collect_weekly.py \
  --no-agent \
  --deliver local

hermes cron create "0 18 * * 0" \
  --name "Attendance weekly digest" \
  --script attendance_review_weekly.py \
  --no-agent \
  --deliver discord
```

Cron times use your machine’s local timezone. `30 17 * * 0` = Sunday 5:30pm; `0 18 * * 0` = Sunday 6:00pm.

Hermes only runs scripts from its **scripts directory** (filename only, no `D:\...` paths). On Windows this is usually:

`%LOCALAPPDATA%\hermes\scripts\`  
(e.g. `C:\Users\<you>\AppData\Local\hermes\scripts\`)

Copy the wrappers from this repo’s `scripts/hermes_*.py` templates into that folder as `attendance_collect_weekly.py` and `attendance_review_weekly.py`, or sync from `%USERPROFILE%\.hermes\scripts\` if you keep a copy there.

**Important (Windows):** Hermes runs `.py` with Python and `.sh` with bash. It does **not** run `.cmd` batch files — a job pointing at `attendance_collect_weekly.cmd` will always fail (`SyntaxError` on `@echo off`). Use **`attendance_collect_weekly.py`** or **`attendance_collect_weekly.sh`** (requires Git Bash on `PATH`).

**Windows CMD** (one line each):

```bat
hermes cron create "30 17 * * 0" --name "Attendance collect weekly" --script attendance_collect_weekly.py --no-agent --deliver local

hermes cron create "0 18 * * 0" --name "Attendance weekly digest" --script attendance_review_weekly.py --no-agent --deliver discord
```

Manual test without Hermes: run `attendance_collect_weekly.cmd` from the Hermes scripts folder (or project `scripts\hermes_collect.py`). On failure, check `%LOCALAPPDATA%\hermes\scripts\attendance_cron.log`.

If you already created broken jobs named `\`, remove them first:

```bat
hermes cron list
hermes cron remove <job-id>
```

Test without waiting:

```bash
hermes cron run "Attendance collect weekly"
hermes cron run "Attendance weekly digest"
```

### Discord delivery (`deliver discord`)

Hermes cron resolves `deliver discord` via **`DISCORD_HOME_CHANNEL` in the gateway process environment** (loaded from `%LOCALAPPDATA%\hermes\.env` at startup). `/sethome` in Discord should set this, but only if the command is **authorized** — check `%LOCALAPPDATA%\hermes\logs\gateway.log` for `Unauthorized user` right after `/sethome`.

Add manually if needed:

```env
DISCORD_HOME_CHANNEL=your_channel_id
```

(Right-click channel → Copy channel ID, Developer Mode on.) Or use `--deliver "discord:#channel-name"` when creating the job.

`DISCORD_ALLOWED_USERS` should include your **numeric Discord user ID**, not only a display name, so slash commands like `/sethome` are allowed.

Restart the Hermes gateway after editing `.env`, then run `hermes cron run "Attendance weekly digest"` again.

`hermes_collect.py` runs `collect --units FIT2102,FIT2109` (no Moodle / ETM1005).

## Security

Never commit `.env`, `.auth/`, `credentials.json`, `token.json`, or `data/`.

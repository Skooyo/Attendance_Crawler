import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from attendance_crawler.paths import CONFIG_PATH, ROOT


@dataclass
class UnitConfig:
    code: str
    moodle_paths: list[str] = field(default_factory=list)
    moodle_course_id: int | None = None
    moodle_discover_sections: bool = False
    moodle_section_ids: list[int] = field(default_factory=list)
    # Monash-style: week 1 at section 8, week 2 at 12 (+4), week 3 at 16, ...
    moodle_week1_section: int | None = None
    moodle_week_section_step: int = 4
    moodle_week_count: int = 12
    collect_enabled: bool = True
    ed_course_id: int | None = None
    ed_thread_title_pattern: str | None = None
    ed_author_name: str | None = None
    gmail_query: str | None = None
    gmail_subject_pattern: str | None = None
    # tutorial / workshop session numbers you attend (see context: Type | date | NUMBER | time | code)
    my_sessions: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class AppConfig:
    moodle_base_url: str
    units: list[UnitConfig]
    code_patterns: list[str]
    collect_lookback_days: int = 7
    hermes_lookback_days: int = 7
    hermes_silent_when_empty: bool = True
    ed_api_token: str | None = None
    ed_base_url: str = "https://edstem.org/api"
    ed_region: str = "us"
    llm_enabled: bool = False
    llm_only_when_empty: bool = True
    llm_model: str | None = None


def load_config(config_path: Path | None = None) -> AppConfig:
    load_dotenv(ROOT / ".env")
    path = config_path or CONFIG_PATH
    raw: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    units = []
    for u in raw.get("units", []):
        ms_raw = u.get("my_sessions") or {}
        my_sessions: dict[str, list[str]] = {}
        if isinstance(ms_raw, dict):
            for key, val in ms_raw.items():
                k = str(key).strip().lower()
                if isinstance(val, str):
                    my_sessions[k] = [val.strip()]
                elif isinstance(val, list):
                    my_sessions[k] = [str(x).strip() for x in val if str(x).strip()]
        units.append(
            UnitConfig(
                code=u["code"],
                moodle_paths=list(u.get("moodle_paths", [])),
                moodle_course_id=u.get("moodle_course_id"),
                moodle_discover_sections=bool(u.get("moodle_discover_sections", False)),
                moodle_section_ids=[int(x) for x in u.get("moodle_section_ids", [])],
                moodle_week1_section=u.get("moodle_week1_section"),
                moodle_week_section_step=int(u.get("moodle_week_section_step", 4)),
                moodle_week_count=int(u.get("moodle_week_count", 12)),
                collect_enabled=bool(u.get("collect_enabled", True)),
                ed_course_id=u.get("ed_course_id"),
                ed_thread_title_pattern=u.get("ed_thread_title_pattern"),
                ed_author_name=u.get("ed_author_name"),
                gmail_query=u.get("gmail_query"),
                gmail_subject_pattern=u.get("gmail_subject_pattern"),
                my_sessions=my_sessions,
            )
        )

    collect = raw.get("collect", {})
    hermes = raw.get("hermes", {})
    llm = raw.get("llm", {})

    moodle_base = raw.get("moodle_base_url") or os.getenv("MOODLE_BASE_URL", "")
    if not moodle_base:
        moodle_base = os.getenv("MOODLE_BASE_URL", "https://lms.example.edu")

    return AppConfig(
        moodle_base_url=moodle_base.rstrip("/"),
        units=units,
        code_patterns=list(raw.get("code_patterns", [])),
        collect_lookback_days=int(collect.get("lookback_days", 7)),
        hermes_lookback_days=int(hermes.get("lookback_days", 7)),
        hermes_silent_when_empty=bool(hermes.get("silent_when_empty", True)),
        ed_api_token=os.getenv("ED_API_TOKEN"),
        ed_base_url=os.getenv("ED_BASE_URL", "https://edstem.org/api").rstrip("/"),
        ed_region=os.getenv("ED_REGION", "us"),
        llm_enabled=bool(llm.get("enabled", False)),
        llm_only_when_empty=bool(llm.get("only_when_regex_empty", True)),
        llm_model=llm.get("model") or os.getenv("OPENROUTER_MODEL"),
    )

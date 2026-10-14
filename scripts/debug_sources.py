#!/usr/bin/env python
"""Debug Gmail and EdStem collectors: list what was fetched and what codes were extracted.

Run from the project root (with venv active and pip install -e .):

  python scripts/debug_sources.py
  python scripts/debug_sources.py --units FIT2109,FIT2102
  python scripts/debug_sources.py --edstem-only --list-all-threads
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Project src on path when run as scripts/debug_sources.py
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from attendance_crawler.config import AppConfig, UnitConfig, load_config
from attendance_crawler.collectors.edstem import (
    _author_matches,
    _author_name_from_thread,
    _author_needles,
    _download_ed_images,
    _list_threads,
    _normalize_thread_detail,
    _thread_matches_filters,
)
from attendance_crawler.collectors.gmail import (
    _extract_parts,
    _get_gmail_service,
    _list_messages,
)
from attendance_crawler import llm_extract
from attendance_crawler.extract import extract_codes_from_text, strip_html
from attendance_crawler.llm_extract import extract_entries_hybrid
from attendance_crawler.paths import GMAIL_CREDENTIALS_PATH

import httpx


def _hr(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _sub(title: str) -> None:
    print()
    print(f"--- {title} ---")


def _snippet(text: str, max_len: int = 400) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def _print_config_summary(config: AppConfig) -> None:
    _hr("Config")
    print(f"collect.lookback_days: {config.collect_lookback_days}")
    print(f"collect.edstem_lookback_days: {config.edstem_lookback_days:g}")
    print(f"llm.enabled: {config.llm_enabled}  llm.only_when_regex_empty: {config.llm_only_when_empty}")
    print(f"llm.model: {config.llm_model or 'claude-sonnet-5-5'}  effort: {config.llm_effort}")
    print(f"ED_API_TOKEN set: {bool(config.ed_api_token)}")
    print(f"code_patterns: {len(config.code_patterns)} pattern(s)")


def _gmail_query(unit: UnitConfig, config: AppConfig) -> str:
    from attendance_crawler.collectors.gmail import gmail_search_query

    return gmail_search_query(unit, config)


def debug_gmail(config: AppConfig, units: list[UnitConfig], *, show_skipped: bool) -> tuple[int, list[str]]:
    errors: list[str] = []
    total_codes = 0

    _hr("Gmail")
    if not GMAIL_CREDENTIALS_PATH.exists():
        print("SKIP: credentials.json not found at project root")
        return 0, ["credentials.json missing"]

    try:
        service = _get_gmail_service()
    except Exception as e:
        print(f"FAIL auth: {e}")
        return 0, [str(e)]

    gmail_units = [u for u in units if u.gmail_query]
    if not gmail_units:
        print("No units with gmail_query in selection.")
        return 0, errors

    for unit in gmail_units:
        _sub(f"Unit {unit.code}")
        query = _gmail_query(unit, config)
        print(f"Query: {query!r}")
        if unit.gmail_subject_pattern:
            print(f"Subject regex: {unit.gmail_subject_pattern!r}")

        try:
            msg_ids = _list_messages(service, query)
        except Exception as e:
            print(f"List messages failed: {e}")
            errors.append(f"Gmail {unit.code}: {e}")
            continue

        print(f"Messages returned by API: {len(msg_ids)}")
        if not msg_ids:
            errors.append(f"Gmail {unit.code}: 0 messages for query")
            continue

        for i, msg_id in enumerate(msg_ids, 1):
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            subject = headers.get("subject", "")
            internal_date = int(msg.get("internalDate", 0))
            occurred = datetime.fromtimestamp(internal_date / 1000, tz=timezone.utc)

            subject_ok = True
            if unit.gmail_subject_pattern:
                subject_ok = bool(re.search(unit.gmail_subject_pattern, subject, re.I))

            if not subject_ok and not show_skipped:
                continue

            print()
            print(f"  [{i}] id={msg_id}")
            print(f"      date: {occurred.isoformat()}")
            print(f"      subject: {subject!r}")
            if not subject_ok:
                print("      >> SKIPPED: subject does not match gmail_subject_pattern")
                continue

            body_text, inline_images, html_raw = _extract_parts(
                service, msg_id, msg.get("payload", {})
            )
            from attendance_crawler.collectors.gmail import _download_images_from_html

            html_images = _download_images_from_html(html_raw)
            all_images = inline_images + html_images

            regex_codes = extract_codes_from_text(
                body_text, config.code_patterns
            )
            entries = extract_entries_hybrid(
                text=body_text,
                patterns=config.code_patterns,
                unit_code=unit.code,
                title=subject,
                image_blobs=all_images,
                llm_enabled=config.llm_enabled,
                llm_only_when_empty=config.llm_only_when_empty,
                llm_model=config.llm_model,
                llm_effort=config.llm_effort,
                default_occurred=occurred,
            )

            print(f"      body chars: {len(body_text)}  inline images: {len(inline_images)}  html images: {len(html_images)}")
            print(f"      body snippet: {_snippet(body_text)!r}")
            print(f"      regex on body only ({len(regex_codes)}): {regex_codes or '(none)'}")
            print(f"      hybrid entries ({len(entries)}):")
            if llm_extract.last_llm_error:
                print(f"      Claude: {llm_extract.last_llm_error}")
            if entries:
                for e in entries:
                    print(f"        - {e.code} | {e.context}")
                total_codes += len(entries)
            else:
                print("        (none - check `claude` login or llm.enabled in config.yaml)")

    return total_codes, errors


def debug_edstem(
    config: AppConfig,
    units: list[UnitConfig],
    *,
    list_all_threads: bool,
) -> tuple[int, list[str]]:
    errors: list[str] = []
    total_codes = 0

    _hr("EdStem")
    if not config.ed_api_token:
        print("SKIP: ED_API_TOKEN not set in .env")
        return 0, ["ED_API_TOKEN missing"]

    headers = {
        "Authorization": f"Bearer {config.ed_api_token}",
        "Content-Type": "application/json",
    }
    base = config.ed_base_url.rstrip("/")
    ed_units = [u for u in units if u.ed_course_id is not None]
    if not ed_units:
        print("No units with ed_course_id in selection.")
        return 0, errors

    with httpx.Client(headers=headers, timeout=60.0) as client:
        for unit in ed_units:
            _sub(f"Unit {unit.code} (course {unit.ed_course_id})")
            if unit.ed_thread_title_pattern:
                print(f"Title regex: {unit.ed_thread_title_pattern!r}")
            if _author_needles(unit):
                print(f"Author contains any of: {_author_needles(unit)!r}")

            try:
                threads = _list_threads(client, base, unit.ed_course_id)
            except Exception as e:
                print(f"List threads failed: {e}")
                errors.append(f"EdStem {unit.code}: {e}")
                continue

            print(f"Threads from API: {len(threads)}")
            matched_threads = 0
            unit_entries = 0
            attendance_like = 0

            for t in threads:
                if not isinstance(t, dict):
                    continue
                tid = t.get("id")
                title = str(t.get("title") or "").strip()
                author = _author_name_from_thread(t, None)
                title_hit = (
                    bool(re.search(unit.ed_thread_title_pattern, title, re.I))
                    if unit.ed_thread_title_pattern
                    else True
                )
                author_hit = _author_matches(unit, author)
                if re.search(r"attendance", title, re.I):
                    attendance_like += 1

                passes = _thread_matches_filters(unit, title, author)
                if list_all_threads or passes or re.search(r"attendance", title, re.I):
                    flag = "MATCH" if passes else "no match"
                    print(f"  thread {tid} [{flag}] title={title!r} author={author!r}")
                    if unit.ed_thread_title_pattern and not title_hit:
                        print("      >> title filter failed")
                    if _author_needles(unit) and author and not author_hit:
                        print("      >> author filter failed")

                if not passes:
                    continue

                matched_threads += 1
                envelope = {}
                detail = t
                try:
                    r = client.get(f"{base}/threads/{tid}")
                    if r.status_code == 200:
                        envelope = r.json()
                        detail = _normalize_thread_detail(envelope, t)
                except Exception as e:
                    print(f"      detail fetch error: {e}")

                title = str(detail.get("title") or t.get("title") or "").strip()
                author_name = _author_name_from_thread(detail, envelope)
                content = detail.get("content") or ""
                if isinstance(content, list):
                    content = " ".join(str(x) for x in content)
                document = detail.get("document") or ""
                text = f"{title}\n{strip_html(str(content))}\n{document}"
                image_blobs = _download_ed_images(client, str(content))
                created = detail.get("created_at") or detail.get("created")
                from attendance_crawler.collectors.edstem import _parse_ed_time

                occurred = _parse_ed_time(created)

                regex_codes = extract_codes_from_text(
                    text, config.code_patterns
                )
                entries = extract_entries_hybrid(
                    text=text,
                    patterns=config.code_patterns,
                    unit_code=unit.code,
                    title=title,
                    image_blobs=image_blobs,
                    llm_enabled=config.llm_enabled,
                    llm_only_when_empty=config.llm_only_when_empty,
                    llm_model=config.llm_model,
                    llm_effort=config.llm_effort,
                    default_occurred=occurred,
                )

                print(f"      text chars: {len(text)}  images: {len(image_blobs)}")
                print(f"      snippet: {_snippet(text)!r}")
                print(f"      regex on body only ({len(regex_codes)}): {regex_codes or '(none)'}")
                print(f"      hybrid entries ({len(entries)}):")
                if llm_extract.last_llm_error:
                    print(f"      Claude: {llm_extract.last_llm_error}")
                if entries:
                    for e in entries:
                        print(f"        - {e.code} | {e.context}")
                    unit_entries += len(entries)
                    total_codes += len(entries)
                else:
                    print("        (none)")

            print()
            print(
                f"Summary: {matched_threads} thread(s) passed filters, "
                f"{attendance_like} title(s) mention 'attendance'"
            )
            if unit.ed_thread_title_pattern and matched_threads == 0 and threads:
                errors.append(
                    f"EdStem {unit.code}: no threads passed title/author filters "
                    f"({len(threads)} listed; try --list-all-threads)"
                )
            elif matched_threads > 0 and unit_entries == 0:
                print(
                    f"Note: {matched_threads} thread(s) matched filters but "
                    "extraction returned 0 codes (images/LLM may have failed)."
                )

    return total_codes, errors


def _filter_units(config: AppConfig, unit_codes: list[str] | None) -> list[UnitConfig]:
    if not unit_codes:
        return config.units
    allowed = {c.upper() for c in unit_codes}
    return [u for u in config.units if u.code.upper() in allowed]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--units",
        help="Comma-separated unit codes (default: all units in config.yaml)",
    )
    parser.add_argument("--gmail-only", action="store_true")
    parser.add_argument("--edstem-only", action="store_true")
    parser.add_argument(
        "--list-all-threads",
        action="store_true",
        help="EdStem: print every thread title (verbose)",
    )
    parser.add_argument(
        "--hide-skipped-gmail",
        action="store_true",
        help="Do not print Gmail messages that fail subject filter",
    )
    args = parser.parse_args()

    unit_codes = None
    if args.units:
        unit_codes = [u.strip() for u in args.units.split(",") if u.strip()]

    config = load_config()
    units = _filter_units(config, unit_codes)
    _print_config_summary(config)

    run_gmail = not args.edstem_only
    run_edstem = not args.gmail_only
    total = 0
    all_errors: list[str] = []

    if run_gmail:
        n, errs = debug_gmail(
            config, units, show_skipped=not args.hide_skipped_gmail
        )
        total += n
        all_errors.extend(errs)

    if run_edstem:
        n, errs = debug_edstem(
            config, units, list_all_threads=args.list_all_threads
        )
        total += n
        all_errors.extend(errs)

    _hr("Collect preview (same as collect would return)")
    if run_gmail and run_edstem:
        from attendance_crawler.collectors.edstem import collect_edstem
        from attendance_crawler.collectors.gmail import collect_gmail

        g_recs, g_errs = collect_gmail(config)
        e_recs, e_errs = collect_edstem(config)
        if unit_codes:
            allowed = {c.upper() for c in unit_codes}
            g_recs = [r for r in g_recs if r.unit_code.upper() in allowed]
            e_recs = [r for r in e_recs if r.unit_code.upper() in allowed]
        print(f"collect_gmail(): {len(g_recs)} candidate record(s)")
        for r in g_recs:
            print(f"  {r.unit_code} {r.code} | {r.context}")
        print(f"collect_edstem(): {len(e_recs)} candidate record(s)")
        for r in e_recs:
            print(f"  {r.unit_code} {r.code} | {r.context}")
        all_errors.extend(g_errs)
        all_errors.extend(e_errs)

    _hr("Done")
    print(f"Total hybrid entries from debug walk: {total}")
    if all_errors:
        print("Warnings / errors:")
        for e in all_errors:
            print(f"  - {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

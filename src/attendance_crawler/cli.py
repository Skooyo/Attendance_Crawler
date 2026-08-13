import argparse
import sys

from attendance_crawler.auth_gmail import auth_gmail_interactive
from attendance_crawler.config import load_config
from attendance_crawler.collectors.edstem import collect_edstem
from attendance_crawler.collectors.gmail import collect_gmail
from attendance_crawler.collectors.moodle import collect_moodle
from attendance_crawler.paths import ensure_dirs
from attendance_crawler.report import format_hermes, format_markdown
from attendance_crawler.session_filter import filter_records_for_my_sessions
from attendance_crawler.store import fetch_since, insert_records
from attendance_crawler.auth_moodle import auth_moodle_interactive
from attendance_crawler.ed_digest import (
    collect_ed_digest,
    confirm_digest,
    format_dump,
    load_pending,
    write_pending,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="attendance_crawler")
    sub = parser.add_subparsers(dest="command", required=True)

    auth_p = sub.add_parser("auth", help="Authentication helpers")
    auth_p.add_argument("target", choices=["moodle", "gmail"])

    collect_p = sub.add_parser("collect", help="Collect codes from enabled units")
    collect_p.add_argument(
        "--units",
        help="Comma-separated unit codes to collect (e.g. FIT2102,FIT2109)",
        default=None,
    )

    review_p = sub.add_parser("review", help="Review gathered codes")
    review_p.add_argument("--days", type=int, default=None)
    review_p.add_argument(
        "--format",
        choices=["markdown", "hermes"],
        default="markdown",
    )
    review_p.add_argument(
        "--all-sessions",
        action="store_true",
        help="Ignore my_sessions filters in config.yaml",
    )


    ed_p = sub.add_parser("ed-digest", help="Daily EdStem digest (collect / dump / confirm)")
    ed_sub = ed_p.add_subparsers(dest="ed_command", required=True)
    ed_sub.add_parser("collect", help="Fetch new threads, rank, write pending dump")
    ed_sub.add_parser("dump", help="Print pending dump for Hermes agent (or Nothing new)")
    ed_sub.add_parser("confirm", help="Watermark + mark Ed read after Discord delivery")

    args = parser.parse_args(argv)
    ensure_dirs()
    config = load_config()

    if args.command == "auth":
        if args.target == "moodle":
            auth_moodle_interactive(config)
        elif args.target == "gmail":
            auth_gmail_interactive()
        return


    if args.command == "ed-digest":
        if args.ed_command == "collect":
            posts, errors = collect_ed_digest(config)
            path = write_pending(posts)
            print(f"Ed digest collect: {len(posts)} post(s) -> {path}")
            for err in errors:
                print(err, file=sys.stderr)
            return
        if args.ed_command == "dump":
            posts = load_pending()
            print(format_dump(posts), end="")
            return
        if args.ed_command == "confirm":
            n, errors = confirm_digest(config)
            print(f"Ed digest confirm: watermarked {n} thread(s)")
            for err in errors:
                print(err, file=sys.stderr)
            return

    if args.command == "collect":
        unit_codes = None
        if args.units:
            unit_codes = [u.strip() for u in args.units.split(",") if u.strip()]
        cmd_collect(config, unit_codes=unit_codes)
        return

    if args.command == "review":
        days = args.days or (
            config.hermes_lookback_days if args.format == "hermes" else config.collect_lookback_days
        )
        records = fetch_since(days)
        if not getattr(args, "all_sessions", False):
            records = filter_records_for_my_sessions(records, config.units)
        if args.format == "hermes":
            out = format_hermes(records, days, config.hermes_silent_when_empty)
        else:
            out = format_markdown(records, days)
        print(out)
        return


def cmd_collect(config, unit_codes: list[str] | None = None) -> None:
    config = _filter_units_for_collect(config, unit_codes)
    if not config.units:
        print("No units selected for collect (check collect_enabled or --units).")
        return

    print("Collecting for:", ", ".join(u.code for u in config.units))

    all_records: list = []
    all_errors: list[str] = []

    for name, fn in (
        ("gmail", collect_gmail),
        ("edstem", collect_edstem),
        ("moodle", collect_moodle),
    ):
        recs, errs = fn(config)
        all_records.extend(recs)
        all_errors.extend(errs)
        print(f"{name}: {len(recs)} candidate codes")

    inserted = insert_records(all_records)
    print(f"Inserted {inserted} new records into database")

    for err in all_errors:
        print(err, file=sys.stderr)

    if any("AUTH_REQUIRED" in e for e in all_errors):
        print("AUTH_REQUIRED: moodle", file=sys.stderr)


def _filter_units_for_collect(config, unit_codes: list[str] | None):
    from attendance_crawler.config import AppConfig

    units = config.units
    if unit_codes:
        allowed = {c.upper() for c in unit_codes}
        units = [u for u in units if u.code.upper() in allowed]
    else:
        units = [u for u in units if u.collect_enabled]

    return AppConfig(
        moodle_base_url=config.moodle_base_url,
        units=units,
        code_patterns=config.code_patterns,
        collect_lookback_days=config.collect_lookback_days,
        edstem_lookback_days=config.edstem_lookback_days,
        hermes_lookback_days=config.hermes_lookback_days,
        hermes_silent_when_empty=config.hermes_silent_when_empty,
        ed_api_token=config.ed_api_token,
        ed_base_url=config.ed_base_url,
        ed_region=config.ed_region,
        llm_enabled=config.llm_enabled,
        llm_only_when_empty=config.llm_only_when_empty,
        llm_model=config.llm_model,
        llm_max_tokens=config.llm_max_tokens,
        ed_digest=config.ed_digest,
    )


if __name__ == "__main__":
    main()

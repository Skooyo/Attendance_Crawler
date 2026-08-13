---
id: map-edstem-daily-digest
title: EdStem daily digest
labels: [wayfinder:map]
status: open
assignee: null
---

# EdStem daily digest

## Destination

Working daily EdStem digest for FIT2102 (`ed_course_id` 36340) and FIT2109 (`ed_course_id` 39026), delivered to Discord via Hermes. Each run covers every new unread post since the last successful digest, sorted so Staff/Tutor (and announcement-style posts) and keyword hits (Quiz, Assignment, Specs, …) rise to the top.

## Notes

- Domain: Monash Ed (AU); reuse `ED_API_TOKEN` / `ED_REGION`.
- Skills: `/grilling` and `/domain-modeling` on HITL tickets; `/research` on API tickets.
- Prefer extending this repo over a new project; keep attendance extraction filters out of the digest path.
- Keyword seed: Quiz, Assignment, Specs (config-editable later).
- Locked defaults: Hermes agent summarizes a structured dump; collect/rank stays local Python; do not change weekly attendance cron behavior.
- Tracker: local-markdown under `.wayfinder/` (see [README](../README.md)).
- **Build defaults (no further HITL):** sibling module for digest (do not mix attendance filters); SQLite watermark table keyed by course + thread id/number + last activity; cap bodies/threads per run if rate limits hit (document ceiling with a `ponytail:` note).

## Decisions so far

<!-- one line per closed ticket: gist + link -->
- Prefer local digest watermark over Ed `is_seen` alone; use `user.course_role` + `type` for rank — [Research — Ed unread and role fields](../tickets/001-research-ed-unread-and-role-fields.md)
- Course **39026** valid for FIT2109 (list 200, enrolled) — [Task — Smoke FIT2109 39026](../tickets/002-task-smoke-fit2109-39026.md)
- Keywords seed Quiz/Assignment/Specs (editable later); sort A staff/announcement then keywords then rest — [Grilling — Keyword and rank rules](../tickets/003-grilling-keyword-and-rank-rules.md)
- Dump shape A; Discord: detail for important posts else title+summary+link; empty -> ping "Nothing new"; after send: watermark + mark Ed read — [Grilling — Digest payload and mark-read](../tickets/004-grilling-digest-payload-and-mark-read.md)
- Two jobs: `EdStem daily collect` 20:55 local + `EdStem Daily Digest` 21:00 Discord agent — [Grilling — Daily schedule](../tickets/005-grilling-daily-schedule.md)

## Not yet specified

<!-- fog cleared into Notes build defaults; way is clear for build handoff -->

## Out of scope

- Moodle or Gmail in this digest
- Changing weekly attendance Hermes jobs
- Posting or editing on Ed
- Auto-replying to threads

## Child tickets

- [Research — Ed unread and role fields](../tickets/001-research-ed-unread-and-role-fields.md) (closed)
- [Task — Smoke FIT2109 39026](../tickets/002-task-smoke-fit2109-39026.md) (closed)
- [Grilling — Keyword and rank rules](../tickets/003-grilling-keyword-and-rank-rules.md) (closed)
- [Grilling — Digest payload and mark-read](../tickets/004-grilling-digest-payload-and-mark-read.md) (closed)
- [Grilling — Daily schedule](../tickets/005-grilling-daily-schedule.md) (closed)

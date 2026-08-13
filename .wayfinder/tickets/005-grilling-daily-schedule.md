---
id: ticket-005
title: Grilling — Daily schedule
labels: [wayfinder:grilling]
status: closed
assignee: null
parent: map-edstem-daily-digest
blocked_by: []
---

# Grilling — Daily schedule

## Question

What local cron time and Hermes job names should run the daily Ed digest (parallel to existing weekly attendance jobs, without changing those jobs)?

## Context

- Attendance today: weekly collect + weekly Discord review via Hermes `--no-agent` scripts.
- Ed digest: daily; agent summarizes; Discord delivery.

## Resolution

- **Pattern B (two jobs):** local collect/rank first, then Hermes agent summarizes to Discord. Do not change weekly attendance jobs.
- **Collect job:** name `EdStem daily collect`; cron `55 20 * * *` (20:55 local); `--no-agent`; deliver `local`.
- **Digest job:** name `EdStem Daily Digest`; cron `0 21 * * *` (21:00 local); agent on; deliver `discord`.
- Collect must finish before 21:00 so the agent reads a fresh dump.

---
id: ticket-004
title: Grilling — Digest payload and mark-read
labels: [wayfinder:grilling]
status: closed
assignee: null
parent: map-edstem-daily-digest
blocked_by: [ticket-001, ticket-002]
---

# Grilling — Digest payload and mark-read

## Question

What structured dump does the Hermes agent receive per post (title, body, link, role, keywords, …)? Silent when empty? After a successful Discord digest, do we mark Ed threads read, only update a local watermark, or both?

## Locked so far

- Hermes **agent** writes the Discord summary from a structured dump.
- Collect/rank stays local Python (no LLM in the scrape path).

## Resolution

- **Collector dump (to Hermes):** per post — unit, title, type, role, matched keywords, link, short body (~500 chars), no comments (payload shape A).
- **Agent Discord output:** important posts (staff/announcement / keyword hits) get more detail; other posts get title + short summary + link only.
- **Empty digest:** still send Discord — ping with `Nothing new` (not silent).
- **After successful Discord send:** update **local watermark** and **mark Ed threads read** (option B). Use detail GET (or mark-read) only after delivery succeeds; list/collect must use `mark_as_read=false` when fetching bodies beforehand.

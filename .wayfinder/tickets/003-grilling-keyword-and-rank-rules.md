---
id: ticket-003
title: Grilling — Keyword and rank rules
labels: [wayfinder:grilling]
status: closed
assignee: null
parent: map-edstem-daily-digest
blocked_by: [ticket-001]
---

# Grilling — Keyword and rank rules

## Question

What is the final keyword list, and how do Staff/Tutor (and announcement type) combine with keyword hits for sort order?

## Seed (not final)

- Keywords: Quiz, Assignment, Specs
- Priority sketch from map defaults: (1) Staff/Tutor / announcement (2) keyword hits (3) remaining unread

## Resolution

- **Keywords:** start with seed `Quiz`, `Assignment`, `Specs`. Config must allow later edits to add/remove keywords without a code change.
- **Sort (rule A):** (1) staff-side author (`course_role` not `student` / not null) or `type == announcement` (2) keyword hits in title/body (3) remaining digest items. Within a tier, keep newest-first.
- **Staff-side note:** treat `admin` / `staff` / `tutor` / `mentor` as staff-side (live courses often use `admin`).

---
id: ticket-001
title: Research — Ed unread and role fields
labels: [wayfinder:research]
status: closed
assignee: null
parent: map-edstem-daily-digest
blocked_by: []
---

# Research — Ed unread and role fields

## Question

What does the Ed API expose for unread/seen state, mark-read, author course role (staff/tutor), announcement thread type, and list/filter params — for courses 36340 and 39026 — so we can choose Ed unread vs a local digest watermark?

## Notes for research

- Existing collector: `src/attendance_crawler/collectors/edstem.py` (Bearer token, `/courses/{id}/threads`, `/threads/{id}`).
- Prefer community docs (edapi, mcp-ed) and live response field names over inventing schemas.
- Capture: field names, endpoints, whether listing returns `is_seen`, how staff/tutor appears on thread or user objects, announcement `type` values, and any mark-read side effects of GET thread.
- Assets: link findings branch or note file from this ticket; do not paste huge dumps into the body.

## Resolution

Use a **local digest watermark** (e.g. course thread `number`) for “since last digest.” List threads expose `is_seen`, `new_reply_count`, and `filter=unread` / `new_replies` / `staff`, but Ed seen-state follows the UI and default `GET /threads/{id}` marks read. Author staff signal is `user.course_role` (`admin`/`staff`/`tutor`/`mentor`/`student`; live 36340/39026 authors were `admin` or `student`). Thread types: `announcement` | `question` | `post`.

Findings: [ed-unread-and-role-fields.md](../research/ed-unread-and-role-fields.md) (branch `research/ed-unread-and-role-fields`).

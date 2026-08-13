# Research — Ed unread and role fields

Ticket: [001-research-ed-unread-and-role-fields](../tickets/001-research-ed-unread-and-role-fields.md)  
Date: 2026-08-12  
Courses probed live: `36340` (FIT2102), `39026` (FIT2109)  
Base used: `ED_BASE_URL` → `https://edstem.org/api` (token present; list-only GETs; no mark-read POSTs; no bare `GET /threads/{id}`)

Sources: live list responses; [wondermuttt/mcp-ed](https://github.com/wondermuttt/mcp-ed) `edClient.ts`; [laggycomputer/edstem](https://github.com/laggycomputer/edstem) `opts.rs` / `model/thread.rs` / `model/course.rs`; [smartspot2/edapi](https://github.com/smartspot2/edapi) `docs/api_docs.md`; [advaith1/ed-poster](https://github.com/advaith1/ed-poster) local `number` watermark pattern.

## Endpoints and list params

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/courses/{id}/threads` | List. Safe for research (does not mark read). |
| `GET` | `/threads/{id}` | Detail. **Marks seen by default** (mcp-ed). Prefer `?mark_as_read=false` if body is needed. |
| `GET` | `/courses/{id}/threads/{number}` | Detail by course thread number (edapi). |
| `POST` | `/threads/{id}/unread` | Mark unread (mcp-ed). |
| `GET` | `/threads/{id}` (no `mark_as_read=false`) | De-facto mark-read (mcp-ed). |
| `GET` | `/user` | Self + enrolled courses; course role at `courses[].role.role`. |
| `GET` | `/courses/{id}/users` | Returns 200 with empty `users` for token used here (not useful for roster). |

### Query params for `GET /courses/{id}/threads`

Observed / documented:

| Param | Values | Live check |
|-------|--------|------------|
| `limit` | ≤100 treated as page size (edstem crate) | Used `50` / `20` / `10` OK |
| `offset` | skip count | OK |
| `sort` | `new` (known); community also cites `top` / `unanswered` | `new` OK |
| `filter` | see below | several verified |

`filter` keys from edstem crate + live:

| `filter` | Meaning (crate) | Live on 36340/39026 |
|----------|-----------------|---------------------|
| `unread` | not read by token user | all returned had `is_seen=false` |
| `new_replies` | read threads with unread replies (crate); live returned mix | works; **needed** because `unread` alone omits seen threads that still have `new_reply_count>0` |
| `unresolved` | not resolved by staff | works |
| `staff` | initially posted by course staff | works; authors had `course_role=admin` here |
| `following` / `mine` / `unanswered` / `endorsed` / `watching` / `starred` / `private` / `public` | documented in edstem `GetCourseThreadsFilterKey` | `following`/`mine` probed; others not all probed |

No `created_after` param (matches existing collector comment).

## Seen / unread field names (exact)

On each list thread object (live + docs):

| Field | Type | Meaning |
|-------|------|---------|
| `is_seen` | bool | Token user has seen the thread |
| `new_reply_count` | int | New replies since user last viewed |
| `glanced_at` | str \| null | Last glance time (ISO); null when never seen |
| `is_starred` | bool | Starred by user |
| `is_watched` | bool \| null | Watch state (`true`/`false`/`null` in live JSON) |

Related list envelope keys: `sort_key`, `threads`, `users`.

**Unread selection without mark-read side effects:** use list + `filter=unread` and/or client filter `is_seen == false`. Also include `filter=new_replies` or `new_reply_count > 0` if reply activity matters.

## Mark read / unread

| Action | How |
|--------|-----|
| Mark read | `GET /threads/{id}` (default). mcp-ed wraps this as mark-read. |
| Avoid mark read | `GET /threads/{id}?mark_as_read=false` (mcp-ed). |
| Mark unread | `POST /threads/{id}/unread` (mcp-ed). |

edapi `api_docs.md` documents thread get/update/pin/star/etc., but does **not** document mark-read query or `/unread`. Prefer mcp-ed + live behavior for those.

**Do not** use bare detail GET in a digest collector if Ed UI unread state must stay intact.

## Author course role (field path)

| Path | Where | Values |
|------|-------|--------|
| `thread.user.course_role` | list thread embedded author | live: `admin`, `student`, sometimes `null` (anon / missing) |
| `users[].course_role` | sibling `users` array on list response | same |
| `users[].role` | platform role | live always `"user"` (not course role) |
| `courses[].role.role` on `GET /user` | **your** enrollment role | live: `"student"` for both target courses |

Canonical course-role enum ([edstem `Role`](https://github.com/laggycomputer/edstem/blob/master/src/model/course.rs)):

`student` | `mentor` | `tutor` | `staff` | `admin` (+ `Other`)

Course UI labels exist under `course.settings.role_labels.{student,mentor,tutor,staff,admin}` (edapi).

**Live note for 36340 / 39026:** staff-like authors appear as `course_role=admin`, not `staff` or `tutor`. Treat non-`student` (and non-null) as staff-side for ranking, or use `filter=staff`. Do not require the literal string `tutor`.

## Thread `type` values

Exact strings (live + edapi + edstem `ThreadType`):

- `announcement`
- `question`
- `post`

Live type mixes (sample pages):

- 36340 `limit=50 sort=new`: announcement 7, post 10, question 33  
- 39026 `limit=50 sort=new`: announcement 6, post 2, question 15  

## Recommendation: Ed unread vs local watermark

**Prefer a local digest watermark** (e.g. last digested course `number`, or set of digested thread ids), not Ed `is_seen` alone.

Why:

1. Map goal is “since the last successful digest,” not “whatever the human left unread in the Ed UI.”
2. Browsing Ed (or attendance collector `GET /threads/{id}`) marks `is_seen` and would drop items from an Ed-unread-only digest.
3. `filter=unread` misses seen threads that still have new replies; you would need a second pass (`new_replies` / `new_reply_count`).
4. Community digests (ed-poster) already watermark on increasing `number`.

**Still use Ed fields for ranking and optional UI sync:**

- Rank: `type == announcement`, `user.course_role` in `{admin,staff,tutor,mentor}`, or `filter=staff`.
- Optional: surface `is_seen` / `new_reply_count` as metadata.
- Only mark Ed read after a successful digest if product wants UI badges cleared (`GET` detail or future explicit mark-read) — grill that in ticket 004.

## Sample key lists (live; field names only)

### List response top-level

`sort_key`, `threads`, `users`

### Thread object keys (36340 and 39026 identical shape)

`accepted_id`, `anonymous_comments`, `anonymous_id`, `approved_status`, `category`, `content`, `course_id`, `created_at`, `deleted_at`, `document`, `duplicate_id`, `duplicate_title`, `editor_id`, `flag_count`, `glanced_at`, `id`, `is_anonymous`, `is_answered`, `is_archived`, `is_endorsed`, `is_locked`, `is_megathread`, `is_pinned`, `is_private`, `is_seen`, `is_staff_answered`, `is_starred`, `is_student_answered`, `is_watched`, `new_reply_count`, `number`, `original_id`, `pinned_at`, `reply_count`, `star_count`, `subcategory`, `subsubcategory`, `title`, `type`, `unique_view_count`, `unresolved_count`, `updated_at`, `user`, `user_id`, `view_count`, `vote`, `vote_count`

### Embedded / list user keys

`avatar`, `course_role`, `id`, `name`, `role`, `tutorials`

### `GET /user` course enrollment keys (target courses)

Envelope: `course`, `lab`, `last_active`, `role`  
`role` object fields include: `user_id`, `course_id`, `lab_id`, `role`, `tutorial`, `digest`, `settings`, `created_at`, `deleted_at`

### Live unread snapshot (list only; counts change over time)

| Course | `filter=unread` count (cap 20/100 probes) | Unfiltered `is_seen` false share |
|--------|-------------------------------------------|----------------------------------|
| 36340 | 20 (all `is_seen=false`); later ~24 at limit 100 | 23/50 false on first page |
| 39026 | 12 unread total in course at probe | 12/23 false on full list page |

## Collector impact (no implementation)

Existing `edstem.py` list call (`limit`, `sort=new`) is correct for attendance. Digest should reuse list fields above; avoid detail GET unless `mark_as_read=false` or mark-read is intentional.

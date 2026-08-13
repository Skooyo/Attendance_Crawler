# Local-markdown wayfinder tracker

Issues live as markdown files. The map is the index; tickets hold decisions.

## Layout

- `maps/` — issues labelled `wayfinder:map`
- `tickets/` — child issues labelled `wayfinder:<type>`
- Frontmatter: `id`, `title`, `labels`, `status`, `assignee`, `parent`, `blocked_by`

## Wayfinding operations

| Operation | How |
|-----------|-----|
| Create map | Add `maps/<slug>.md` with label `wayfinder:map`, `status: open` |
| Create ticket | Add `tickets/<nnn>-<slug>.md` with `parent` = map id |
| Claim | Set `assignee` to the driver; clear to unclaim |
| Block | List blocker ticket ids in `blocked_by` |
| Frontier | Open tickets where every `blocked_by` id is `status: closed`, and `assignee` is empty |
| Resolve | Add `## Resolution`, set `status: closed`, append one gist line under the map **Decisions so far** |
| Out of scope | Close the ticket; one line under map **Out of scope**, not Decisions so far |

Refer to maps and tickets by **title**, with the file path as the link.

"""Assert-based self-check for Ed digest rank/watermark helpers."""
from datetime import datetime, timezone

from attendance_crawler.ed_digest import DigestPost, _needs_digest, _tier, format_dump, rank_posts


def _post(**kwargs) -> DigestPost:
    base = dict(
        unit_code="FIT2102",
        course_id=1,
        thread_id=1,
        thread_number=1,
        title="Hello",
        type="post",
        role="student",
        matched_keywords=[],
        link="https://example.com",
        body="body",
        important=False,
        last_activity_at="2026-08-01T00:00:00+00:00",
        created_at="2026-08-01T00:00:00+00:00",
    )
    base.update(kwargs)
    return DigestPost(**base)


def main() -> None:
    staff = _post(thread_id=1, role="admin", type="announcement", title="A", created_at="2026-08-01T10:00:00+00:00")
    kw = _post(thread_id=2, role="student", matched_keywords=["Quiz"], title="Q", created_at="2026-08-02T10:00:00+00:00", important=True)
    other = _post(thread_id=3, role="student", title="Z", created_at="2026-08-03T10:00:00+00:00")
    ranked = rank_posts([other, kw, staff])
    assert [p.thread_id for p in ranked] == [1, 2, 3], ranked
    assert _tier(staff) == 0
    assert _tier(kw) == 1
    assert _tier(other) == 2

    assert _needs_digest({"id": 9, "updated_at": "2026-08-10T00:00:00Z"}, {}) is True
    assert (
        _needs_digest(
            {"id": 9, "updated_at": "2026-08-10T00:00:00Z"},
            {9: "2026-08-10T00:00:00+00:00"},
        )
        is False
    )
    assert (
        _needs_digest(
            {"id": 9, "updated_at": "2026-08-11T00:00:00Z"},
            {9: "2026-08-10T00:00:00+00:00"},
        )
        is True
    )

    assert format_dump([]) == "Nothing new\n"
    assert "Quiz" in format_dump([kw])
    print("check_ed_digest: ok")


if __name__ == "__main__":
    main()
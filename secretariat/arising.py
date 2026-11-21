"""Matters-arising report: what is overdue, due, closed or still to implement, as at a given date."""
from __future__ import annotations

import datetime as dt

from .model import Company
from .registers import RAG, action_flag, days_overdue


def fmt_date(d: dt.date | None) -> str:
    return f"{d.day} {d:%b %Y}" if d else ""


def matters_arising(company: Company, body_code: str, resolutions: list[dict], actions: list[dict], as_of: dt.date,
                    next_meeting: dt.date | None, since: dt.date | None, deferred_items: list[dict] | None = None) -> dict:
    """Group one body's actions and resolutions for the next agenda pack.

    `since` is the date of the last meeting: actions closed on or after it are listed as closed.
    Actions due on or before `next_meeting` (and not yet overdue) are "due before the next meeting".
    """
    soon = company.due_soon_days
    name = lambda pid: company.people[pid].name if pid in company.people else pid  # noqa: E731
    mine = [a for a in actions if a["body"] == body_code]
    groups = {"overdue": [], "due_next": [], "later": [], "deferred_actions": [], "closed": []}
    for a in sorted(mine, key=lambda a: (a["due_date"], a["id"])):
        flag = action_flag(a["status"], a["due_date"], as_of, soon)
        row = {"id": a["id"], "action": a["action"], "owner": name(a["owner"]), "due": fmt_date(a["due_date"]),
               "raised": a["meeting_id"], "status": a["status"], "flag": flag, "bg": RAG[flag],
               "days": days_overdue(a["status"], a["due_date"], as_of)}
        if flag == "Overdue":
            row["flag"] = f"Overdue {row['days']} d"
            groups["overdue"].append(row)
        elif flag == "Closed":
            if since and a.get("closed_date") and a["closed_date"] >= since:
                groups["closed"].append({**row, "closed": fmt_date(a["closed_date"]), "note": a.get("update_note") or ""})
        elif flag == "Deferred":
            groups["deferred_actions"].append(row)
        elif next_meeting is None or a["due_date"] <= next_meeting:
            groups["due_next"].append(row)
        else:
            groups["later"].append(row)
    groups["overdue"].sort(key=lambda r: -r["days"])

    res_rows = []
    for r in sorted(resolutions, key=lambda r: (r["meeting_date"], r["ref"])):
        if r["body"] == body_code and r["implementation_status"] in ("Not started", "In progress"):
            res_rows.append({"ref": r["ref"], "title": r["title"], "owner": name(r["owner"]), "date": fmt_date(r["meeting_date"]),
                             "status": r["implementation_status"],
                             "bg": "FFF3CD" if r["implementation_status"] == "In progress" else "F8D7DA"})

    n_open = len(groups["overdue"]) + len(groups["due_next"]) + len(groups["later"])
    parts = [f"{n_open} open action{'s' if n_open != 1 else ''}"]
    if groups["overdue"]:
        worst = groups["overdue"][0]
        parts.append(f"{len(groups['overdue'])} overdue (longest: {worst['id']}, {worst['owner']}, {worst['days']} days)")
    else:
        parts.append("none overdue")
    if next_meeting:
        parts.append(f"{len(groups['due_next'])} due by {fmt_date(next_meeting)}")
    summary = (", ".join(parts) + f". {len(groups['closed'])} closed since {fmt_date(since) if since else 'the last meeting'}. "
               f"{len(res_rows)} resolution{'s' if len(res_rows) != 1 else ''} awaiting implementation.")
    return {**groups, "resolutions": res_rows, "deferred_items": deferred_items or [], "summary": summary,
            "as_of": fmt_date(as_of), "since": fmt_date(since) if since else "the last meeting", "open": n_open}

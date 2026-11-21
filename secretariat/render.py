"""Fill the Word templates with docxtpl and, if LibreOffice is installed, convert them to PDF."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from docxtpl import DocxTemplate

from .arising import fmt_date
from .model import Company, Meeting

try:
    from hijridate import Gregorian
except ImportError:  # optional
    Gregorian = None

TYPE_LABEL = {"ordinary": "Ordinary resolution", "special": "Special resolution"}


def long_date(d: dt.date) -> str:
    return f"{d:%A} {d.day} {d:%B %Y}"


def hijri(d: dt.date) -> str:
    if Gregorian is None:
        return ""
    h = Gregorian(d.year, d.month, d.day).to_hijri()
    return f"{h.day} {h.month_name()} {h.year} AH"


def _names(company: Company, ids) -> str:
    return ", ".join(company.people[i].name for i in ids) or "None"


def base_context(company: Company, meeting: Meeting) -> dict:
    timings = meeting.timings()
    sec = company.people[company.secretary]
    return {
        "company": {"name": company.name, "name_ar": company.name_ar, "timezone": company.timezone},
        "body": {"name": meeting.body.name, "name_ar": meeting.body.name_ar, "code": meeting.body.code},
        "meeting": {
            "id": meeting.id, "title": meeting.title, "venue": meeting.venue,
            "date_long": long_date(meeting.date), "hijri": hijri(meeting.date) if company.show_hijri else "",
            "notice_long": long_date(meeting.notice_date), "start": f"{meeting.start:%H:%M}",
            "end": f"{timings[-1][1]:%H:%M}", "quorum_required": meeting.quorum_required,
            "members_count": len(meeting.body.members),
            "opened": f"{meeting.record['opened']:%H:%M}" if meeting.record and meeting.record.get("opened") else "",
            "closed": f"{meeting.record['closed']:%H:%M}" if meeting.record and meeting.record.get("closed") else "",
        },
        "secretary": sec.name, "secretary_email": sec.email,
        "chair": company.people[meeting.body.chair].name,
        "next_meeting": long_date(meeting.next_meeting) if meeting.next_meeting else "",
    }


def agenda_context(company: Company, meeting: Meeting, ma: dict) -> dict:
    ctx = base_context(company, meeting)
    ctx["members"] = [{"name": company.people[m].name, "name_ar": company.people[m].name_ar,
                       "role": ("Chair" if m == meeting.body.chair else company.people[m].title)} for m in meeting.body.members]
    ctx["agenda"] = [{"no": i["no"], "title": i["title"], "purpose": i["purpose"],
                      "presenter": company.people[i["presenter"]].name if i.get("presenter") else "",
                      "time": f"{s:%H:%M} to {e:%H:%M}", "papers": "; ".join(i["papers"])}
                     for i, (s, e) in zip(meeting.agenda, meeting.timings())]
    arising_item = next((i["no"] for i in meeting.agenda if "matters arising" in i["title"].lower()), None)
    ctx["arising_paper"] = f"{arising_item}.1" if arising_item else "A"
    ctx["ma"] = ma
    return ctx


def _vote_line(t: dict) -> str:
    if t["unanimous"]:
        return f"Approved unanimously by the {t['eligible']} eligible members present."
    return f"Votes: {t['for']} for, {t['against']} against, {t['abstain']} abstaining ({t['eligible']} eligible)."


def resolution_rows(company: Company, meeting: Meeting) -> list[dict]:
    rows = []
    for r in meeting.resolutions:
        t = r["tally"]
        rows.append({
            "ref": r["ref"], "item": r["item"], "title": r["title"], "text": r["text"].rstrip("."),
            "type": r["type"].capitalize(), "type_label": TYPE_LABEL[r["type"]],
            "proposer": company.people[r["proposer"]].name if r.get("proposer") else "not recorded",
            "seconder": company.people[r["seconder"]].name if r.get("seconder") else "not recorded",
            "votes": f"{t['for']} / {t['against']} / {t['abstain']}", "vote_line": _vote_line(t), "rule": t["rule"],
            "outcome": t["outcome"], "bg": "E2EFDA" if t["carried"] else "F8D7DA",
            "owner": company.people[r["owner"]].name if r.get("owner") else "",
            "excluded": ", ".join(company.people[p].name for p in r["excluded"]),
        })
    return rows


def minutes_context(company: Company, meeting: Meeting) -> dict:
    ctx = base_context(company, meeting)
    rec = meeting.record or {}
    n_present, req, total = len(meeting.members_present), meeting.quorum_required, len(meeting.body.members)
    ctx["status"] = "DRAFT for the Chair's review. Not approved."
    ctx["present"] = [{"name": company.people[p].name, "role": "Chair" if p == meeting.body.chair else company.people[p].title}
                      for p in meeting.present]
    ctx["apologies"] = _names(company, meeting.apologies)
    ctx["in_attendance"] = [{"name": company.people[x["person"]].name, "role": company.people[x["person"]].title,
                             "for_items": str(x.get("items", "All"))} for x in meeting.in_attendance]
    ctx["quorum_text"] = (f"{n_present} of {total} members present; at least {req} required. "
                          + ("The meeting was quorate." if meeting.quorate else "The meeting was NOT quorate."))
    ctx["conflicts"] = [{"name": company.people[c["person"]].name, "item": c["item"], "nature": c["nature"]} for c in meeting.conflicts]
    res = resolution_rows(company, meeting)
    acts = [{"id": a["id"], "item": a["item"], "action": a["action"].rstrip("."), "owner": company.people[a["owner"]].name,
             "due": fmt_date(a["due"])} for a in meeting.actions]
    deferred = set(rec.get("deferred") or [])
    notes = rec.get("items") or {}
    ctx["items"] = [{"no": i["no"], "title": i["title"], "notes": (notes.get(i["no"]) or {}).get("notes", []),
                     "resolutions": [r for r in res if r["item"] == i["no"]],
                     "actions": [a for a in acts if a["item"] == i["no"]], "deferred": i["no"] in deferred}
                    for i in meeting.agenda]
    ctx["actions"] = acts
    ctx["date_notes"] = [w for w in meeting.warnings if "weekend" in w]
    return ctx


def resolutions_context(company: Company, meeting: Meeting) -> dict:
    ctx = base_context(company, meeting)
    ctx["resolutions"] = resolution_rows(company, meeting)
    ctx["quorum_short"] = f"{len(meeting.members_present)} of {len(meeting.body.members)} members"
    return ctx


def render(template: Path, context: dict, out: Path) -> Path:
    tpl = DocxTemplate(str(template))
    tpl.render(context, autoescape=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(out))
    return out


def soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def to_pdf(files: list[Path], out_dir: Path) -> list[Path]:
    """Convert DOCX/XLSX files to PDF with LibreOffice (one call). Returns [] if LibreOffice is missing."""
    exe = soffice()
    if not exe or not files:
        return []
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([exe, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
                        "--convert-to", "pdf", "--outdir", str(out_dir), *map(str, files)],
                       check=True, capture_output=True, timeout=300, env={**os.environ, "SAL_USE_VCLPLUGIN": "svp"})
    return [out_dir / (f.stem + ".pdf") for f in files if (out_dir / (f.stem + ".pdf")).exists()]

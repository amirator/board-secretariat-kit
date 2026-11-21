"""One meeting file in, the full set of secretariat documents out."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import render as R
from .arising import matters_arising
from .model import Company, Meeting, load_meeting, number_meeting
from .registers import apply_meeting, load_registers, write_csvs, write_workbook

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"


def last_meeting_date(body_code: str, before: dt.date, resolutions: list[dict], actions: list[dict]) -> dt.date | None:
    dates = [r["meeting_date"] for r in resolutions + actions if r["body"] == body_code and r["meeting_date"] < before]
    return max(dates, default=None)


def default_as_of(meeting: Meeting) -> dt.date:
    """Flags are worked out as at the meeting date unless --as-of is given (e.g. the day the next pack goes out)."""
    return meeting.date


def prepare(company: Company, meeting_path, registers_dir):
    res, act = load_registers(registers_dir)
    meeting = load_meeting(meeting_path, company)
    number_meeting(meeting, company, [r["ref"] for r in res], [a["id"] for a in act])
    return meeting, res, act


def run_agenda(company: Company, meeting_path, registers_dir, out_dir, templates=TEMPLATES, pdf=False) -> dict:
    meeting, res, act = prepare(company, meeting_path, registers_dir)
    out = Path(out_dir)
    ma = matters_arising(company, meeting.body.code, res, act, as_of=meeting.notice_date, next_meeting=meeting.date,
                         since=last_meeting_date(meeting.body.code, meeting.date, res, act))
    docx = R.render(Path(templates) / "agenda_pack.docx", R.agenda_context(company, meeting, ma), out / f"{meeting.id}_agenda_pack.docx")
    files = {"agenda_pack": docx}
    if pdf:
        for p in R.to_pdf([docx], out):
            files["agenda_pack_pdf"] = p
    return {"meeting": meeting, "files": files, "warnings": meeting.warnings}


def run_pack(company: Company, meeting_path, registers_dir, out_dir, templates=TEMPLATES, pdf=False,
             as_of: dt.date | None = None) -> dict:
    """Agenda pack, minutes draft, resolutions, updated registers (CSV + Excel) and the next matters-arising report."""
    meeting, res, act = prepare(company, meeting_path, registers_dir)
    if not meeting.record:
        raise ValueError(f"{meeting.id} has no 'record' section yet; use the 'agenda' command before the meeting")
    out, templates = Path(out_dir), Path(templates)
    code = meeting.body.code
    files: dict[str, Path] = {}

    ma_before = matters_arising(company, code, res, act, as_of=meeting.notice_date, next_meeting=meeting.date,
                                since=last_meeting_date(code, meeting.date, res, act))
    files["agenda_pack"] = R.render(templates / "agenda_pack.docx", R.agenda_context(company, meeting, ma_before),
                                    out / f"{meeting.id}_agenda_pack.docx")
    files["minutes"] = R.render(templates / "minutes.docx", R.minutes_context(company, meeting),
                                out / f"{meeting.id}_minutes_DRAFT.docx")
    files["resolutions"] = R.render(templates / "resolutions.docx", R.resolutions_context(company, meeting),
                                    out / f"{meeting.id}_resolutions.docx")

    res2, act2, applied = apply_meeting(meeting, res, act)
    as_of = as_of or default_as_of(meeting)
    deferred = [{"no": i["no"], "title": i["title"],
                 "presenter": company.people[i["presenter"]].name if i.get("presenter") else ""}
                for i in meeting.agenda if i["no"] in set(meeting.record.get("deferred") or [])]
    ma_after = matters_arising(company, code, res2, act2, as_of=as_of, next_meeting=meeting.next_meeting,
                               since=meeting.date, deferred_items=deferred)
    ctx = R.base_context(company, meeting)
    ctx["ma"] = ma_after
    files["matters_arising"] = R.render(templates / "matters_arising.docx", ctx, out / f"{meeting.id}_matters_arising.docx")

    reg_dir = out / "registers"
    write_csvs(reg_dir, res2, act2)
    files["registers_csv_dir"] = reg_dir
    summary = write_workbook(out / f"{meeting.id}_registers.xlsx", company, res2, act2, as_of,
                             title=f"{company.name}: registers after {meeting.id}")
    files["registers_xlsx"] = out / f"{meeting.id}_registers.xlsx"

    if pdf:
        docs = [files[k] for k in ("agenda_pack", "minutes", "resolutions", "matters_arising")]
        for p in R.to_pdf(docs, out):
            files[p.stem.split("_", 1)[1] + "_pdf"] = p
    return {"meeting": meeting, "files": files, "summary": summary, "matters_arising": ma_after,
            "applied_updates": applied, "warnings": meeting.warnings, "as_of": as_of,
            "resolutions": res2, "actions": act2}

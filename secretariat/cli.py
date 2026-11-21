"""Command line: python -m secretariat <command>."""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

from . import __version__
from .model import InputError, load_company, load_meeting
from .pipeline import ROOT, TEMPLATES, run_agenda, run_pack
from .render import soffice
from .templates import build_templates

SAMPLE = ROOT / "sample_data"


def _common(p: argparse.ArgumentParser):
    p.add_argument("--company", type=Path, default=SAMPLE / "company.yaml", help="company, people and bodies (YAML)")
    p.add_argument("--registers", type=Path, default=SAMPLE / "registers", help="folder with resolutions_register.csv and action_log.csv")
    p.add_argument("--templates", type=Path, default=TEMPLATES, help="folder with the four .docx templates")
    p.add_argument("--out", type=Path, default=ROOT / "outputs", help="output folder")
    p.add_argument("--pdf", action="store_true", help="also write PDFs (needs LibreOffice)")


def _print_files(result: dict):
    for k, v in result["files"].items():
        print(f"  {k:<20} {v}")
    for w in result["warnings"]:
        print(f"  note: {w}")


def cmd_validate(a) -> int:
    company = load_company(a.company)
    m = load_meeting(a.meeting, company)
    n_res = len((m.record or {}).get("resolutions") or [])
    print(f"OK  {m.id}: {m.body.name}, {m.date:%d %b %Y}, {len(m.agenda)} agenda items, "
          f"{len(m.members_present)}/{len(m.body.members)} members present (quorum {m.quorum_required}), "
          f"{n_res} resolutions recorded")
    return 0


def cmd_agenda(a) -> int:
    r = run_agenda(load_company(a.company), a.meeting, a.registers, a.out, a.templates, a.pdf)
    print(f"Agenda pack for {r['meeting'].id}:")
    _print_files(r)
    return 0


def cmd_pack(a) -> int:
    as_of = dt.date.fromisoformat(a.as_of) if a.as_of else None
    r = run_pack(load_company(a.company), a.meeting, a.registers, a.out, a.templates, a.pdf, as_of)
    s = r["summary"]
    print(f"{r['meeting'].id}: {len(r['meeting'].resolutions)} resolutions numbered, {len(r['meeting'].actions)} actions added, "
          f"{len(r['applied_updates'])} action updates applied")
    print(f"Registers as at {r['as_of']:%d %b %Y}: {s['open']} open actions, {s['overdue']} overdue, "
          f"{s['awaiting_implementation']} resolutions awaiting implementation")
    _print_files(r)
    return 0


def cmd_demo(a) -> int:
    """Audit Committee meeting first, then the Board meeting, feeding the registers through."""
    company = load_company(SAMPLE / "company.yaml")
    base = a.out / "demo"
    if base.exists():
        shutil.rmtree(base)
    pdf = (soffice() is not None) and not a.no_pdf
    registers = SAMPLE / "registers"
    for mid in ("AC-2026-04", "BOD-2026-04"):
        out = base / mid
        r = run_pack(company, SAMPLE / "meetings" / f"{mid}.yaml", registers, out, a.templates, pdf)
        s = r["summary"]
        print(f"\n{mid}  ({r['meeting'].body.name}, {r['meeting'].date:%d %b %Y})")
        print(f"  resolutions {', '.join(x['ref'] for x in r['meeting'].resolutions)}")
        print(f"  actions     {', '.join(x['id'] for x in r['meeting'].actions)}")
        print(f"  registers   as at {r['as_of']:%d %b %Y}: {s['open']} open, {s['overdue']} overdue, {s['due_soon']} due soon")
        _print_files(r)
        registers = out / "registers"
    if not pdf:
        print("\n(PDFs skipped: LibreOffice not found or --no-pdf given. DOCX and XLSX were written.)")
    print(f"\nAll outputs: {base}")
    return 0


def cmd_templates(a) -> int:
    company = load_company(a.company)
    for p in build_templates(a.templates, company.latin_font, company.arabic_font):
        print(f"  {p}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m secretariat", description="Board and committee secretariat kit")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check a meeting file and report every problem")
    v.add_argument("meeting", type=Path)
    v.add_argument("--company", type=Path, default=SAMPLE / "company.yaml")
    v.set_defaults(fn=cmd_validate)
    g = sub.add_parser("agenda", help="before the meeting: notice, agenda and matters-arising paper")
    g.add_argument("meeting", type=Path)
    _common(g)
    g.set_defaults(fn=cmd_agenda)
    p = sub.add_parser("pack", help="after the meeting: minutes, resolutions, registers and next matters arising")
    p.add_argument("meeting", type=Path)
    p.add_argument("--as-of", help="date for overdue flags (YYYY-MM-DD); default: the meeting date")
    _common(p)
    p.set_defaults(fn=cmd_pack)
    d = sub.add_parser("demo", help="run both sample meetings end to end")
    d.add_argument("--out", type=Path, default=ROOT / "outputs")
    d.add_argument("--templates", type=Path, default=TEMPLATES)
    d.add_argument("--no-pdf", action="store_true")
    d.set_defaults(fn=cmd_demo)
    t = sub.add_parser("build-templates", help="regenerate the .docx templates (overwrites your edits)")
    t.add_argument("--company", type=Path, default=SAMPLE / "company.yaml")
    t.add_argument("--templates", type=Path, default=TEMPLATES)
    t.set_defaults(fn=cmd_templates)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except InputError as exc:
        print(f"Input problem in {exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

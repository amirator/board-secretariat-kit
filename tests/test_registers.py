import csv
import datetime as dt
import subprocess
import tempfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

from secretariat.model import InputError, load_meeting, number_meeting
from secretariat.registers import (action_flag, apply_meeting, days_overdue, load_registers, summarise, write_csvs,
                                   write_workbook)

from .conftest import SAMPLE, has_soffice

D = dt.date


@pytest.fixture
def applied(company):
    res, act = load_registers(SAMPLE / "registers")
    m = load_meeting(SAMPLE / "meetings" / "BOD-2026-04.yaml", company)
    number_meeting(m, company, [r["ref"] for r in res], [a["id"] for a in act])
    res2, act2, updates = apply_meeting(m, res, act)
    return m, res, act, res2, act2, updates


@pytest.mark.parametrize("status,due,flag,days", [
    ("Open", D(2026, 11, 17), "Overdue", 1),
    ("In progress", D(2026, 11, 18), "Due soon", 0),   # due today is not overdue yet
    ("Open", D(2026, 11, 25), "Due soon", 0),          # edge of the 7-day window
    ("Open", D(2026, 11, 26), "On track", 0),
    ("Closed", D(2026, 1, 1), "Closed", 0),
    ("Deferred", D(2026, 1, 1), "Deferred", 0),
])
def test_action_flags(status, due, flag, days):
    as_of = D(2026, 11, 18)
    assert action_flag(status, due, as_of, 7) == flag
    assert days_overdue(status, due, as_of) == days


def test_apply_meeting_adds_and_updates(applied):
    m, res, act, res2, act2, updates = applied
    assert len(res2) == len(res) + 5 and len(act2) == len(act) + 4
    a12 = next(a for a in act2 if a["id"] == "A-2026-012")
    assert a12["status"] == "Closed" and a12["closed_date"] == m.date
    a15 = next(a for a in act2 if a["id"] == "A-2026-015")
    assert a15["due_date"] == D(2026, 11, 30) and a15["status"] == "In progress"
    assert {u["id"] for u in updates} == {"A-2026-012", "A-2026-015"}
    # inputs are not modified
    assert next(a for a in act if a["id"] == "A-2026-012")["status"] == "In progress"
    new = [r for r in res2 if r["meeting_id"] == m.id]
    assert all(r["implementation_status"] == "Not started" for r in new)


def test_meeting_cannot_be_applied_twice(applied):
    m, _, _, res2, act2, _ = applied
    with pytest.raises(InputError, match="applied before"):
        apply_meeting(m, res2, act2)


def test_unknown_action_update_is_rejected(company, meeting_file):
    p = meeting_file(edit=lambda t: t.replace("id: A-2026-012", "id: A-2026-999"))
    res, act = load_registers(SAMPLE / "registers")
    m = load_meeting(p, company)
    number_meeting(m, company, [], [])
    with pytest.raises(InputError, match="A-2026-999"):
        apply_meeting(m, res, act)


def test_csv_round_trip(tmp_path, applied):
    _, _, _, res2, act2, _ = applied
    write_csvs(tmp_path, res2, act2)
    assert (tmp_path / "action_log.csv").read_text(encoding="utf-8").startswith("# SAMPLE / DEMO DATA")
    r3, a3 = load_registers(tmp_path)
    assert [r["ref"] for r in r3] == [r["ref"] for r in res2]
    assert [(a["id"], a["due_date"], a["status"]) for a in a3] == [(a["id"], a["due_date"], a["status"]) for a in act2]


def test_duplicate_numbers_in_register_are_rejected(tmp_path, registers_dir):
    p = registers_dir / "action_log.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join(lines + [lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(InputError, match="duplicate action"):
        load_registers(registers_dir)


def test_summary_counts(applied):
    _, _, _, res2, act2, _ = applied
    s = summarise(act2, res2, D(2026, 11, 18), 7)
    assert s["open"] + s["closed"] + s["deferred"] == s["actions_total"] == len(act2)
    assert s["overdue"] == 3                     # A-2026-010, A-2026-009 and A-2026-013 (committee meeting not applied here)
    assert s["oldest_overdue"][0]["id"] == "A-2026-010" and s["oldest_overdue"][1] == 34


def test_workbook_is_live(tmp_path, company, applied):
    _, _, _, res2, act2, _ = applied
    path = tmp_path / "reg.xlsx"
    write_workbook(path, company, res2, act2, D(2026, 11, 18), "test")
    wb = load_workbook(path)
    assert wb.sheetnames == ["Summary", "Action log", "Resolutions"]
    assert set(wb.defined_names) >= {"AsOf", "SoonDays"}
    al = wb["Action log"]
    assert al.freeze_panes == "B5"
    assert al["M5"].value.startswith('=IF(I5="Closed"')
    assert "AsOf" in al["L5"].value
    assert any("Open,In progress,Closed,Deferred" in dv.formula1 for dv in al.data_validations.dataValidation)
    assert al.conditional_formatting
    assert wb["Summary"]["B9"].value.startswith("=COUNTIF(")
    assert al.max_row == 4 + len(act2)


@pytest.mark.skipif(not has_soffice(), reason="LibreOffice not installed")
def test_excel_formulas_match_python(tmp_path, company, applied):
    """Recalculate the workbook in LibreOffice and compare every flag with the Python rules."""
    _, _, _, res2, act2, _ = applied
    as_of = D(2026, 12, 9)
    path = tmp_path / "reg.xlsx"
    s = write_workbook(path, company, res2, act2, as_of, "test")
    with tempfile.TemporaryDirectory() as prof:
        subprocess.run(["soffice", f"-env:UserInstallation={Path(prof).as_uri()}", "--headless", "--convert-to",
                        "csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,false,false,false,-1",
                        "--outdir", str(tmp_path), str(path)], check=True, capture_output=True, timeout=180)
    rows = list(csv.reader(open(tmp_path / "reg-Action log.csv", encoding="utf-8")))[4:]
    got = {r[0]: (r[12], int(r[11])) for r in rows if r and r[0]}
    want = {a["id"]: (action_flag(a["status"], a["due_date"], as_of, 7), days_overdue(a["status"], a["due_date"], as_of))
            for a in act2}
    assert got == want
    summary = {r[0]: r[1] for r in csv.reader(open(tmp_path / "reg-Summary.csv", encoding="utf-8")) if r}
    assert int(summary["Overdue"]) == s["overdue"] and int(summary["Open (all)"]) == s["open"]

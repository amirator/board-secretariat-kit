import datetime as dt

from secretariat.arising import matters_arising
from secretariat.registers import load_registers

from .conftest import SAMPLE


def test_board_matters_arising_before_the_meeting(company):
    res, act = load_registers(SAMPLE / "registers")
    ma = matters_arising(company, "BOD", res, act, as_of=dt.date(2026, 11, 4), next_meeting=dt.date(2026, 11, 18),
                         since=dt.date(2026, 9, 16))
    assert [a["id"] for a in ma["overdue"]] == ["A-2026-015", "A-2026-013", "A-2026-012"]   # longest overdue first
    assert ma["overdue"][0]["days"] == 15
    assert all(a["raised"].startswith("BOD") for k in ("overdue", "due_next", "later") for a in ma[k])
    assert [a["id"] for a in ma["closed"]] == ["A-2026-011"]
    assert {r["ref"] for r in ma["resolutions"]} == {"BR/2026/006", "BR/2026/007", "BR/2026/008", "BR/2026/011"}
    assert ma["summary"].startswith("6 open actions, 3 overdue (longest: A-2026-015, Khalid Bin Saeed, 15 days)")


def test_committee_report_only_shows_committee_items(company):
    res, act = load_registers(SAMPLE / "registers")
    ma = matters_arising(company, "AC", res, act, as_of=dt.date(2026, 11, 4), next_meeting=dt.date(2026, 11, 11),
                         since=dt.date(2026, 9, 9))
    ids = [a["id"] for k in ("overdue", "due_next", "later", "closed") for a in ma[k]]
    assert ids and all(i in {"A-2026-007", "A-2026-009", "A-2026-010", "A-2026-017"} for i in ids)


def test_empty_registers_give_a_clean_report(company):
    ma = matters_arising(company, "BOD", [], [], as_of=dt.date(2026, 11, 4), next_meeting=None, since=None)
    assert ma["open"] == 0 and ma["summary"].startswith("0 open actions, none overdue")

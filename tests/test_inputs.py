import pytest

from secretariat.model import InputError, load_company, load_meeting, number_meeting
from secretariat.registers import load_registers

from .conftest import SAMPLE


def test_sample_meetings_load(company):
    for name in ("AC-2026-04", "BOD-2026-04"):
        m = load_meeting(SAMPLE / "meetings" / f"{name}.yaml", company)
        assert m.quorate
        assert m.agenda[0]["title"] == "Opening, quorum and declarations of interest"


def test_board_meeting_numbers_and_votes(company):
    res, act = load_registers(SAMPLE / "registers")
    m = load_meeting(SAMPLE / "meetings" / "BOD-2026-04.yaml", company)
    number_meeting(m, company, [r["ref"] for r in res], [a["id"] for a in act])
    assert [r["ref"] for r in m.resolutions] == [f"BR/2026/{n:03d}" for n in range(13, 18)]
    lease = next(r for r in m.resolutions if r["item"] == 6)
    assert lease["excluded"] == ["OFR"]                  # conflicted director did not vote
    assert lease["tally"]["eligible"] == 5 and lease["tally"]["for"] == 5
    doa = next(r for r in m.resolutions if r["type"] == "special")
    assert doa["tally"]["carried"] and doa["tally"]["needed"] == 4
    assert [a["id"] for a in m.actions] == ["A-2026-019", "A-2026-020", "A-2026-021", "A-2026-022"]
    assert any("moved to Sun 06 Dec 2026" in w for w in m.warnings)


def test_unquoted_no_key_is_still_read(company, meeting_file):
    p = meeting_file(edit=lambda t: t.replace("{item: 2,", "{no: 2,"))
    assert load_meeting(p, company).agenda[1]["no"] == 2


def errors_for(company, path):
    with pytest.raises(InputError) as exc:
        load_meeting(path, company)
    return "\n".join(exc.value.problems)


def test_every_problem_is_reported_at_once(company, meeting_file):
    def edit(t):
        t = t.replace("presenter: KBS, minutes: 20", "presenter: ZZZ, minutes: 20")
        t = t.replace("proposer: NSH", "proposer: TZH")           # TZH sent apologies
        t = t.replace('title: "Opening, quorum and declarations of interest"', "title: Opening, quorum")
        return t
    msg = errors_for(company, meeting_file(edit=edit))
    assert "unknown presenter 'ZZZ'" in msg
    assert "proposer 'TZH' is not a member present" in msg
    assert "put quotes around text that contains commas" in msg


def test_inquorate_meeting_cannot_record_resolutions(company, meeting_file):
    p = meeting_file(edit=lambda t: t.replace("present: [SMU, NSH, KBS, RHD, OFR, LMN]", "present: [SMU, NSH, OFR]")
                     .replace("apologies: [TZH]", "apologies: [TZH, KBS, RHD, LMN]"))
    msg = errors_for(company, p)
    assert "not quorate" in msg


def test_conflict_must_name_a_present_member_and_real_item(company, meeting_file):
    p = meeting_file(edit=lambda t: t.replace("  - person: OFR\n    item: 6", "  - person: TZH\n    item: 99"))
    msg = errors_for(company, p)
    assert "'TZH' is not listed as present" in msg and "agenda item 99 does not exist" in msg


def test_non_member_must_be_in_attendance_not_present(company, meeting_file):
    p = meeting_file(edit=lambda t: t.replace("present: [SMU, NSH, KBS, RHD, OFR, LMN]", "present: [SMU, NSH, KBS, RHD, OFR, LMN, PNR]"))
    assert "PNR is not a member of Board of Directors" in errors_for(company, p)


def test_too_many_votes_is_caught_when_numbering(company, meeting_file):
    p = meeting_file(edit=lambda t: t.replace("votes: {for: 4, against: 1, abstain: 1}", "votes: {for: 6, against: 1, abstain: 0}"))
    m = load_meeting(p, company)
    with pytest.raises(InputError, match="only 6 eligible"):
        number_meeting(m, company, [], [])


def test_bad_company_file(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("company: {name: X, secretary: NOPE, weekend: [Friday]}\npeople: []\nbodies: {}\n", encoding="utf-8")
    with pytest.raises(InputError) as exc:
        load_company(p)
    msg = "\n".join(exc.value.problems)
    assert "secretary" in msg and "Friday" in msg and "at least one body" in msg


def test_special_majority_accepts_fractions_and_percentages(tmp_path):
    base = (SAMPLE / "company.yaml").read_text(encoding="utf-8")
    for value, expected in (("2/3", 2 / 3), ("75%", 0.75), ("0.6", 0.6)):
        p = tmp_path / "c.yaml"
        p.write_text(base.replace("special_majority: 2/3", f'special_majority: "{value}"', 1), encoding="utf-8")
        assert abs(load_company(p).bodies["BOD"].special_majority - expected) < 1e-9
    p.write_text(base.replace("special_majority: 2/3", "special_majority: two thirds", 1), encoding="utf-8")
    with pytest.raises(InputError, match="not a fraction"):
        load_company(p)

import datetime as dt

import pytest

from secretariat.model import Body, next_action_id, next_ref, roll_to_working_day, tally

BOARD = Body("BOD", "Board", "", "BR", ["A", "B", "C", "D", "E", "F", "G"], "A", 0.5, 3, 2 / 3, True)
COMMITTEE = Body("AC", "Audit Committee", "", "ACR", ["A", "B", "C", "D"], "A", 0.5, 2, 2 / 3, False)


def test_quorum_required_uses_the_higher_of_fraction_and_minimum():
    assert BOARD.quorum_required() == 4          # ceil(0.5 * 7)
    assert COMMITTEE.quorum_required() == 2
    small = Body("X", "X", "", "X", ["A", "B", "C"], "A", 0.5, 3)
    assert small.quorum_required() == 3          # minimum count wins


def test_unanimous_vote_counts_every_eligible_member():
    t = tally("unanimous", 5, "ordinary", BOARD)
    assert (t["for"], t["against"], t["abstain"], t["carried"], t["unanimous"]) == (5, 0, 0, True, True)


def test_ordinary_resolution_needs_more_for_than_against():
    assert tally({"for": 4, "against": 1, "abstain": 1}, 6, "ordinary", BOARD)["outcome"] == "Carried"
    assert tally({"for": 2, "against": 3, "abstain": 1}, 6, "ordinary", BOARD)["outcome"] == "Not carried"


def test_tie_fails_without_casting_vote_and_follows_it_when_allowed():
    assert not tally({"for": 3, "against": 3}, 6, "ordinary", BOARD)["carried"]
    assert tally({"for": 3, "against": 3}, 6, "ordinary", BOARD, casting_vote="for")["carried"]
    assert not tally({"for": 3, "against": 3}, 6, "ordinary", BOARD, casting_vote="against")["carried"]
    with pytest.raises(ValueError, match="casting vote"):
        tally({"for": 2, "against": 2}, 4, "ordinary", COMMITTEE, casting_vote="for")


def test_special_resolution_threshold_is_on_eligible_members_present():
    # 6 eligible, two-thirds rule: 4 needed
    assert tally({"for": 4, "against": 0, "abstain": 2}, 6, "special", BOARD)["carried"]
    assert not tally({"for": 3, "against": 0, "abstain": 3}, 6, "special", BOARD)["carried"]
    assert tally({"for": 3, "against": 0, "abstain": 3}, 6, "special", BOARD)["needed"] == 4


def test_more_votes_than_eligible_members_is_rejected():
    with pytest.raises(ValueError, match="only 5 eligible"):
        tally({"for": 5, "against": 1}, 5, "ordinary", BOARD)
    with pytest.raises(ValueError):
        tally({"for": -1}, 5, "ordinary", BOARD)
    with pytest.raises(ValueError):
        tally("most", 5, "ordinary", BOARD)


def test_resolution_numbers_continue_per_prefix_and_restart_each_year():
    refs = ["BR/2026/001", "BR/2026/012", "ACR/2026/008", "BR/2025/031"]
    assert next_ref(refs, "BR", 2026) == "BR/2026/013"
    assert next_ref(refs, "ACR", 2026) == "ACR/2026/009"
    assert next_ref(refs, "BR", 2027) == "BR/2027/001"
    assert next_ref([], "NRC", 2026) == "NRC/2026/001"


def test_action_ids_continue_within_the_year():
    assert next_action_id(["A-2026-001", "A-2026-018", "A-2025-090"], 2026) == "A-2026-019"
    assert next_action_id(["A-2026-018"], 2027) == "A-2027-001"


@pytest.mark.parametrize("given,expected", [
    (dt.date(2026, 12, 4), dt.date(2026, 12, 6)),    # Friday -> Sunday
    (dt.date(2026, 11, 28), dt.date(2026, 11, 29)),  # Saturday -> Sunday
    (dt.date(2026, 11, 29), dt.date(2026, 11, 29)),  # Sunday is a working day in KSA
])
def test_due_dates_roll_off_the_gulf_weekend(given, expected):
    assert roll_to_working_day(given, [4, 5]) == expected


def test_weekend_is_configurable():
    assert roll_to_working_day(dt.date(2026, 11, 28), [5, 6]) == dt.date(2026, 11, 30)  # Sat/Sun weekend -> Monday

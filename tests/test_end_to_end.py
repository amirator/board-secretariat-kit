import zipfile

import pytest

from secretariat.cli import main
from secretariat.pipeline import run_agenda, run_pack

from .conftest import ROOT, SAMPLE, has_soffice


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        return "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("word/") and n.endswith(".xml"))


def test_demo_runs_both_meetings_and_chains_registers(tmp_path, capsys):
    assert main(["demo", "--out", str(tmp_path), "--no-pdf"]) == 0
    out = capsys.readouterr().out
    assert "ACR/2026/009, ACR/2026/010, ACR/2026/011" in out
    assert "BR/2026/013" in out and "A-2026-022" in out   # Board actions numbered after the committee's
    bod = tmp_path / "demo" / "BOD-2026-04"
    for name in ("agenda_pack", "minutes_DRAFT", "resolutions", "matters_arising"):
        text = docx_text(bod / f"BOD-2026-04_{name}.docx")
        assert "{{" not in text and "{%" not in text, f"unrendered tag in {name}"
        assert "SAMPLE / DEMO DATA" in text
        assert "شركة الساحل التجريبية للصناعات" in text
    minutes = docx_text(bod / "BOD-2026-04_minutes_DRAFT.docx")
    assert "6 of 7 members present; at least 4 required. The meeting was quorate." in minutes
    assert "Did not vote (declared interest): Omar Farooqui" in minutes
    assert "This item was deferred to the next meeting." in minutes
    assert "Jumada al-Akhirah 1448 AH" in minutes
    log = (bod / "registers" / "action_log.csv").read_text(encoding="utf-8")
    assert "A-2026-021" in log and "A-2026-025" in log      # committee and board actions both present


def test_agenda_before_the_meeting_needs_no_record(tmp_path, company, meeting_file):
    def strip_record(t):
        return t.split("\nrecord:")[0] + "\n"
    p = meeting_file(edit=strip_record)
    r = run_agenda(company, p, SAMPLE / "registers", tmp_path)
    text = docx_text(r["files"]["agenda_pack"])
    assert "Paper 3.1: Matters arising" in text and "16:00 to 16:05" in text and "18:20 to 18:25" in text
    with pytest.raises(ValueError, match="no 'record' section"):
        run_pack(company, p, SAMPLE / "registers", tmp_path)


def test_cli_reports_bad_input_with_exit_code_2(tmp_path, capsys, meeting_file):
    p = meeting_file(edit=lambda t: t.replace("date: 2026-11-18", "date: 18/11/2026"))
    assert main(["validate", str(p)]) == 2
    assert "is not a date" in capsys.readouterr().err
    assert main(["validate", str(SAMPLE / "meetings" / "AC-2026-04.yaml")]) == 0


def test_templates_contain_their_tags():
    for name in ("agenda_pack", "minutes", "resolutions", "matters_arising"):
        text = docx_text(ROOT / "templates" / f"{name}.docx")
        assert "{{ company.name }}" in text and "{%tr for" in text


@pytest.mark.skipif(not has_soffice(), reason="LibreOffice not installed")
def test_pdfs_are_produced(tmp_path):
    assert main(["demo", "--out", str(tmp_path)]) == 0
    pdfs = sorted((tmp_path / "demo" / "BOD-2026-04").glob("*.pdf"))
    assert [p.stem for p in pdfs] == ["BOD-2026-04_agenda_pack", "BOD-2026-04_matters_arising",
                                      "BOD-2026-04_minutes_DRAFT", "BOD-2026-04_resolutions"]
    assert all(p.read_bytes().startswith(b"%PDF") and p.stat().st_size > 20_000 for p in pdfs)

import shutil
from pathlib import Path

import pytest

from secretariat.model import load_company

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample_data"


@pytest.fixture(scope="session")
def company():
    return load_company(SAMPLE / "company.yaml")


@pytest.fixture
def meeting_file(tmp_path):
    """Copy of the sample Board meeting that a test can edit."""
    def _make(name="BOD-2026-04.yaml", edit=None):
        text = (SAMPLE / "meetings" / name).read_text(encoding="utf-8")
        if edit:
            text = edit(text)
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return p
    return _make


@pytest.fixture
def registers_dir(tmp_path):
    d = tmp_path / "registers"
    shutil.copytree(SAMPLE / "registers", d)
    return d


def has_soffice():
    return bool(shutil.which("soffice") or shutil.which("libreoffice"))

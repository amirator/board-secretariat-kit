"""Run the demo with PDFs, copy sample outputs to examples/ and render the README images to docs/.

Needs LibreOffice (soffice) and poppler (pdftoppm) on PATH, plus Pillow (requirements-dev.txt).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from secretariat.cli import main  # noqa: E402

OUT = ROOT / "outputs"
DOCS, EXAMPLES = ROOT / "docs", ROOT / "examples"


def page_png(pdf: Path, page: int, dpi: int = 110) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "p"
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(page), "-l", str(page), "-singlefile",
                        str(pdf), str(stem)], check=True)
        return Image.open(f"{stem}.png").convert("RGB")


def frame(img: Image.Image) -> Image.Image:
    return ImageOps.expand(img, border=1, fill="#C9CED6")


def trim(img: Image.Image, pad: int = 24) -> Image.Image:
    """Crop white margins, ignoring the page footer (bottom 8% of the page)."""
    body = img.crop((0, 0, img.width, int(img.height * 0.92)))
    box = ImageOps.invert(body.convert("L")).point(lambda v: 255 if v > 20 else 0).getbbox()
    if not box:
        return img
    return img.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(body.height, box[3] + pad)))


def main_() -> None:
    if main(["demo", "--out", str(OUT)]) != 0:
        raise SystemExit("demo failed")
    demo = OUT / "demo"
    bod = demo / "BOD-2026-04"
    if not (bod / "BOD-2026-04_minutes_DRAFT.pdf").exists():
        raise SystemExit("PDFs were not produced: install LibreOffice")

    # examples/: the Board meeting's full output set plus the committee's minutes
    if EXAMPLES.exists():
        shutil.rmtree(EXAMPLES)
    EXAMPLES.mkdir()
    for f in sorted(bod.glob("*.pdf")) + [bod / "BOD-2026-04_registers.xlsx"]:
        shutil.copy(f, EXAMPLES / f.name)
    for f in sorted(bod.glob("*.docx")):
        shutil.copy(f, EXAMPLES / f.name)
    shutil.copy(demo / "AC-2026-04" / "AC-2026-04_minutes_DRAFT.pdf", EXAMPLES)

    # registers workbook as PDF, for its screenshot
    with tempfile.TemporaryDirectory() as prof, tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["soffice", f"-env:UserInstallation={Path(prof).as_uri()}", "--headless", "--convert-to", "pdf",
                        "--outdir", tmp, str(bod / "BOD-2026-04_registers.xlsx")], check=True, capture_output=True)
        xl_pdf = Path(tmp) / "BOD-2026-04_registers.pdf"
        summary = trim(page_png(xl_pdf, 1, 120))
        log = trim(page_png(xl_pdf, 2, 110))

    DOCS.mkdir(exist_ok=True)
    shots = {
        "agenda_pack.png": page_png(bod / "BOD-2026-04_agenda_pack.pdf", 1),
        "minutes.png": page_png(bod / "BOD-2026-04_minutes_DRAFT.pdf", 2),
        "resolutions.png": page_png(bod / "BOD-2026-04_resolutions.pdf", 1),
        "matters_arising.png": page_png(bod / "BOD-2026-04_matters_arising.pdf", 1),
        "action_log.png": log,
        "register_summary.png": summary,
    }
    for name, img in shots.items():
        frame(img).save(DOCS / name, optimize=True)

    # hero: minutes page 1 next to the matters-arising report and the action log
    left = frame(page_png(bod / "BOD-2026-04_minutes_DRAFT.pdf", 1, 90))
    mid = frame(page_png(bod / "BOD-2026-04_matters_arising.pdf", 1, 90))
    gap = 24
    hero = Image.new("RGB", (left.width + mid.width + 3 * gap, left.height + 2 * gap + 30), "#EEF1F5")
    hero.paste(left, (gap, gap + 30))
    hero.paste(mid, (2 * gap + left.width, gap + 30))
    d = ImageDraw.Draw(hero)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 17)
    except OSError:
        font = ImageFont.load_default()
    d.text((gap, 14), "One YAML file in: draft minutes (left) and the matters-arising report for the next meeting (right). "
           "Sample data, fictional company.", fill="#1F2A44", font=font)
    hero.save(DOCS / "hero.png", optimize=True)
    for p in sorted(DOCS.glob("*.png")):
        print(f"  {p.relative_to(ROOT)}  {Image.open(p).size}")
    for p in sorted(EXAMPLES.iterdir()):
        print(f"  {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main_()

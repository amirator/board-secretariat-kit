"""Build the four Word templates (python-docx). They hold Jinja tags that docxtpl fills in.

The generated .docx files in templates/ can be opened and restyled in Word: change fonts,
colours, logos or wording, keep the {{ tags }}, and the kit will use your version.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

NAVY = RGBColor(0x1F, 0x2A, 0x44)
RED = RGBColor(0x9C, 0x00, 0x06)
GREY = RGBColor(0x5F, 0x66, 0x73)
TEMPLATE_NAMES = ("agenda_pack", "minutes", "resolutions", "matters_arising")


# ------------------------------------------------------------------ low-level helpers

def _rfonts(rpr, latin: str | None, arabic: str | None):
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    if latin:
        for k in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            rf.set(qn(k), latin)
    if arabic:
        rf.set(qn("w:cs"), arabic)


def _set_style_fonts(doc, latin: str, arabic: str):
    for name in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Title"):
        st = doc.styles[name]
        st.font.name = latin
        _rfonts(st.element.get_or_add_rPr(), latin, arabic)
    normal = doc.styles["Normal"]
    normal.font.size = Pt(10.5)
    rpr = normal.element.get_or_add_rPr()
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), "22")
    rpr.append(szcs)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "en-GB")
    lang.set(qn("w:bidi"), "ar-SA")
    rpr.append(lang)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.1
    for name, size, before in (("Heading 1", 14, 12), ("Heading 2", 11.5, 10), ("Heading 3", 10.5, 6)):
        st = doc.styles[name]
        st.font.size, st.font.bold, st.font.color.rgb = Pt(size), True, NAVY
        st.paragraph_format.space_before, st.paragraph_format.space_after = Pt(before), Pt(3)
        st.paragraph_format.keep_with_next = True


def _shade(cell, hex_fill: str):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcpr.append(shd)


def _borders(table, color="C9CED6"):
    tblpr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "4")
        e.set(qn("w:color"), color)
        b.append(e)
    tblpr.append(b)


def _widths(table, cms: list[float]):
    """Set widths on the grid and on every cell so Word and LibreOffice agree."""
    grid = table._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), cms):
        gc.set(qn("w:w"), str(int(Cm(w).twips)))
    for row in table.rows:
        for cell, w in zip(row.cells, cms):
            cell.width = Cm(w)


def _repeat_header(row):
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def _cell_text(cell, text: str, bold=False, color=None, size=None):
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(1)
    r = p.add_run(text)
    r.bold = bold
    if color:
        r.font.color.rgb = color
    if size:
        r.font.size = Pt(size)
    return p


def para(doc, text="", style=None, bold=False, italic=False, size=None, color=None, align=None, after=None):
    p = doc.add_paragraph(style=style)
    if text:
        r = p.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color
    if align:
        p.alignment = align
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    return p


def runs(doc, parts: list[tuple[str, dict]], style=None, after=None):
    """One paragraph made of several runs, e.g. [("Owner: ", {"bold": True}), ("{{ a.owner }}", {})]."""
    p = doc.add_paragraph(style=style)
    for text, fmt in parts:
        r = p.add_run(text)
        r.bold = fmt.get("bold", False)
        r.italic = fmt.get("italic", False)
        if fmt.get("color"):
            r.font.color.rgb = fmt["color"]
        if fmt.get("size"):
            r.font.size = Pt(fmt["size"])
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    return p


def arabic(doc, text: str, size=13, bold=True, color=NAVY):
    """Right-to-left paragraph for Arabic text."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    ppr = p._p.get_or_add_pPr()
    ppr.append(OxmlElement("w:bidi"))
    r = p.add_run(text)
    r.font.rtl = True
    rpr = r._r.get_or_add_rPr()
    for tag in ("w:bCs",) if bold else ():
        rpr.append(OxmlElement(tag))
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(int(size * 2)))
    rpr.append(szcs)
    r.bold = bold
    r.font.size = Pt(size)
    r.font.color.rgb = color
    p.paragraph_format.space_after = Pt(2)
    return p


def _field(paragraph, instr: str):
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    paragraph._p.append(fld)


def loop_table(doc, headers: list[str], cells: list[str], loop: str, widths: list[float], header_fill="1F2A44"):
    """Header row, then one row repeated by docxtpl for each element of `loop` (e.g. 'a in actions')."""
    t = doc.add_table(rows=4, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(t)
    for c, h in zip(t.rows[0].cells, headers):
        _cell_text(c, h, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF), size=9.5)
        _shade(c, header_fill)
    _repeat_header(t.rows[0])
    t.rows[1].cells[0].paragraphs[0].add_run(f"{{%tr for {loop} %}}")
    for c, text in zip(t.rows[2].cells, cells):
        _cell_text(c, text, size=9.5)
    t.rows[3].cells[0].paragraphs[0].add_run("{%tr endfor %}")
    _widths(t, widths)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def kv_table(doc, rows: list[tuple[str, str]], widths=(4.2, 12.8)):
    t = doc.add_table(rows=len(rows), cols=2)
    _borders(t)
    for (k, v), row in zip(rows, t.rows):
        _cell_text(row.cells[0], k, bold=True, size=9.5)
        _shade(row.cells[0], "F2F4F7")
        _cell_text(row.cells[1], v, size=9.5)
    _widths(t, list(widths))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def new_document(latin: str, arabic_font: str, doc_label: str) -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(1.8)
    _set_style_fonts(doc, latin, arabic_font)

    hp = sec.header.paragraphs[0]
    r = hp.add_run("SAMPLE / DEMO DATA: fictional company and people, generated by board-secretariat-kit")
    r.font.size, r.font.bold, r.font.color.rgb = Pt(8), True, RED
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h2 = sec.header.add_paragraph()
    r = h2.add_run("{{ company.name }}  |  {{ body.name }}  |  " + doc_label)
    r.font.size, r.font.color.rgb = Pt(8), GREY
    h2.alignment = WD_ALIGN_PARAGRAPH.CENTER

    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("{{ meeting.id }}  |  Confidential  |  Page ")
    r.font.size, r.font.color.rgb = Pt(8), GREY
    _field(fp, "PAGE")
    r = fp.add_run(" of ")
    r.font.size, r.font.color.rgb = Pt(8), GREY
    _field(fp, "NUMPAGES")
    return doc


def title_block(doc, title: str, arabic_title: str, subtitle: str):
    para(doc, "{{ company.name }}", bold=True, size=11, color=GREY, after=0)
    arabic(doc, "{{ company.name_ar }}", size=11, bold=False, color=GREY)
    para(doc, title, bold=True, size=20, color=NAVY, after=0)
    arabic(doc, arabic_title, size=15)
    para(doc, subtitle, size=11, color=GREY, after=8)


# ------------------------------------------------------------------ matters arising block (shared)

def matters_arising_block(doc, v: str = "ma"):
    """Tables of open, overdue and recently closed items. `v` is the context variable holding the data."""
    para(doc, f"{{{{ {v}.summary }}}}", after=6)
    act_cells = [f"{{{{ a.id }}}}", f"{{{{ a.action }}}}", f"{{{{ a.owner }}}}", f"{{{{ a.due }}}}",
                 f"{{% cellbg a.bg %}}{{{{ a.flag }}}}", f"{{{{ a.raised }}}}"]
    act_heads = ["Action", "Description", "Owner", "Due", "Status", "Raised at"]
    act_w = [2.0, 5.2, 2.7, 2.1, 2.6, 2.4]
    for key, heading in (("overdue", "A. Overdue actions"), ("due_next", "B. Actions due before the next meeting"),
                         ("later", "C. Other open actions"), ("deferred_actions", "D. Deferred actions")):
        para(doc, heading, style="Heading 3")
        para(doc, f"{{%p if {v}.{key} %}}")
        loop_table(doc, act_heads, act_cells, f"a in {v}.{key}", act_w)
        para(doc, "{%p else %}")
        para(doc, "None.", italic=True, color=GREY)
        para(doc, "{%p endif %}")

    para(doc, "E. Actions closed since {{ " + v + ".since }}", style="Heading 3")
    para(doc, f"{{%p if {v}.closed %}}")
    loop_table(doc, ["Action", "Description", "Owner", "Closed", "Note"],
               ["{{ a.id }}", "{{ a.action }}", "{{ a.owner }}", "{{ a.closed }}", "{{ a.note }}"],
               f"a in {v}.closed", [2.1, 6.4, 2.9, 2.2, 4.4])
    para(doc, "{%p else %}")
    para(doc, "None.", italic=True, color=GREY)
    para(doc, "{%p endif %}")

    para(doc, "F. Resolutions awaiting implementation", style="Heading 3")
    para(doc, f"{{%p if {v}.resolutions %}}")
    loop_table(doc, ["Ref", "Resolution", "Owner", "Passed", "Status"],
               ["{{ r.ref }}", "{{ r.title }}", "{{ r.owner }}", "{{ r.date }}", "{% cellbg r.bg %}{{ r.status }}"],
               f"r in {v}.resolutions", [2.6, 7.0, 2.9, 2.2, 3.3])
    para(doc, "{%p else %}")
    para(doc, "None.", italic=True, color=GREY)
    para(doc, "{%p endif %}")

    para(doc, f"{{%p if {v}.deferred_items %}}")
    para(doc, "G. Agenda items deferred from the last meeting", style="Heading 3")
    para(doc, f"{{%p for d in {v}.deferred_items %}}")
    para(doc, "Item {{ d.no }}: {{ d.title }} (presenter: {{ d.presenter }})", style="List Bullet")
    para(doc, "{%p endfor %}")
    para(doc, "{%p endif %}")


# ------------------------------------------------------------------ the four templates

def build_agenda_pack(latin, arabic_font) -> Document:
    doc = new_document(latin, arabic_font, "Agenda pack")
    title_block(doc, "Notice and agenda", "دعوة وجدول أعمال الاجتماع", "{{ meeting.title }} ({{ meeting.id }})")
    kv_table(doc, [
        ("Date", "{{ meeting.date_long }}{% if meeting.hijri %} ({{ meeting.hijri }}){% endif %}"),
        ("Time", "{{ meeting.start }} to {{ meeting.end }} ({{ company.timezone }})"),
        ("Venue", "{{ meeting.venue }}"),
        ("Notice issued", "{{ meeting.notice_long }}"),
        ("Quorum", "{{ meeting.quorum_required }} of {{ meeting.members_count }} members"),
        ("Secretary", "{{ secretary }}"),
    ])
    para(doc, "Members", style="Heading 2")
    loop_table(doc, ["Name", "الاسم", "Role"], ["{{ m.name }}", "{{ m.name_ar }}", "{{ m.role }}"],
               "m in members", [6.0, 4.5, 6.5])
    para(doc, "Agenda", style="Heading 2")
    loop_table(doc, ["No.", "Item", "Purpose", "Presenter", "Time", "Papers"],
               ["{{ i.no }}", "{{ i.title }}", "{{ i.purpose }}", "{{ i.presenter }}", "{{ i.time }}", "{{ i.papers }}"],
               "i in agenda", [1.0, 5.6, 2.2, 3.0, 2.4, 3.8])
    runs(doc, [("Declarations of interest. ", {"bold": True}),
               ("Members are asked to tell the Secretary before the meeting about any personal or business interest in an "
                "agenda item. Members with an interest leave the room for that item and do not vote.", {})])
    runs(doc, [("Apologies. ", {"bold": True}), ("Please send apologies to {{ secretary_email }}.", {})])
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)
    para(doc, "Paper {{ arising_paper }}: Matters arising", style="Heading 1")
    para(doc, "Prepared from the action log and resolutions register as at {{ ma.as_of }}.", italic=True, color=GREY)
    matters_arising_block(doc, "ma")
    return doc


def build_minutes(latin, arabic_font) -> Document:
    doc = new_document(latin, arabic_font, "Minutes")
    title_block(doc, "Minutes", "محضر الاجتماع", "{{ meeting.title }} ({{ meeting.id }})")
    para(doc, "{{ status }}", bold=True, color=RED, after=6)
    kv_table(doc, [
        ("Date", "{{ meeting.date_long }}{% if meeting.hijri %} ({{ meeting.hijri }}){% endif %}"),
        ("Venue", "{{ meeting.venue }}"),
        ("Opened / closed", "{{ meeting.opened }} / {{ meeting.closed }} ({{ company.timezone }})"),
    ])
    para(doc, "Attendance", style="Heading 2")
    loop_table(doc, ["Members present", "Role"], ["{{ m.name }}", "{{ m.role }}"], "m in present", [8.0, 9.0])
    runs(doc, [("Apologies: ", {"bold": True}), ("{{ apologies }}", {})])
    para(doc, "{%p if in_attendance %}")
    loop_table(doc, ["In attendance", "Role", "For items"], ["{{ x.name }}", "{{ x.role }}", "{{ x.for_items }}"],
               "x in in_attendance", [6.0, 7.5, 3.5])
    para(doc, "{%p endif %}")
    runs(doc, [("Secretary: ", {"bold": True}), ("{{ secretary }}", {})])
    runs(doc, [("Quorum: ", {"bold": True}), ("{{ quorum_text }}", {})])
    para(doc, "Declarations of interest", style="Heading 2")
    para(doc, "{%p if conflicts %}")
    para(doc, "{%p for c in conflicts %}")
    runs(doc, [("{{ c.name }}, item {{ c.item }}: ", {"bold": True}), ("{{ c.nature }}", {})], style="List Bullet")
    para(doc, "{%p endfor %}")
    para(doc, "{%p else %}")
    para(doc, "No interests were declared.")
    para(doc, "{%p endif %}")

    para(doc, "Proceedings", style="Heading 2")
    para(doc, "{%p for it in items %}")
    para(doc, "{{ it.no }}. {{ it.title }}", style="Heading 3")
    para(doc, "{%p for n in it.notes %}")
    para(doc, "{{ n }}")
    para(doc, "{%p endfor %}")
    para(doc, "{%p for r in it.resolutions %}")
    runs(doc, [("Resolution {{ r.ref }}", {"bold": True, "color": NAVY}), ("  {{ r.type_label }}", {"color": GREY})], after=0)
    runs(doc, [("It was RESOLVED to ", {"bold": True}), ("{{ r.text }}.", {})], after=0)
    runs(doc, [("Proposed by {{ r.proposer }}; seconded by {{ r.seconder }}. {{ r.vote_line }} ", {"italic": True}),
               ("{{ r.outcome }}.", {"bold": True})], after=0)
    para(doc, "{%p if r.excluded %}")
    para(doc, "Did not vote (declared interest): {{ r.excluded }}.", italic=True, color=GREY, after=0)
    para(doc, "{%p endif %}")
    para(doc, "", after=2)
    para(doc, "{%p endfor %}")
    para(doc, "{%p for a in it.actions %}")
    runs(doc, [("Action {{ a.id }}: ", {"bold": True}), ("{{ a.action }}. ", {}),
               ("Owner: {{ a.owner }}. Due: {{ a.due }}.", {"italic": True})], style="List Bullet")
    para(doc, "{%p endfor %}")
    para(doc, "{%p if it.deferred %}")
    para(doc, "This item was deferred to the next meeting.", bold=True, color=RED)
    para(doc, "{%p endif %}")
    para(doc, "{%p endfor %}")

    para(doc, "Summary of actions", style="Heading 2")
    para(doc, "{%p if actions %}")
    loop_table(doc, ["Action", "Item", "Description", "Owner", "Due"],
               ["{{ a.id }}", "{{ a.item }}", "{{ a.action }}", "{{ a.owner }}", "{{ a.due }}"],
               "a in actions", [2.2, 1.1, 8.2, 3.3, 2.2])
    para(doc, "{%p else %}")
    para(doc, "No new actions.")
    para(doc, "{%p endif %}")
    para(doc, "{%p for w in date_notes %}")
    para(doc, "{{ w }}", italic=True, color=GREY, size=9)
    para(doc, "{%p endfor %}")
    para(doc, "There being no further business, the Chair closed the meeting at {{ meeting.closed }}.")
    para(doc, "")
    t = doc.add_table(rows=3, cols=2)
    for c, text in zip(t.rows[0].cells, ["Chair", "Secretary"]):
        _cell_text(c, text, bold=True)
    for c, text in zip(t.rows[1].cells, ["{{ chair }}", "{{ secretary }}"]):
        _cell_text(c, text)
    for c in t.rows[2].cells:
        _cell_text(c, "\nSignature: ______________\nDate: ______________", color=GREY)
    _widths(t, [8.5, 8.5])
    return doc


def build_resolutions(latin, arabic_font) -> Document:
    doc = new_document(latin, arabic_font, "Resolutions")
    title_block(doc, "Resolutions", "قرارات {{ body.name_ar }}", "Passed at {{ meeting.title }} ({{ meeting.id }}), {{ meeting.date_long }}")
    loop_table(doc, ["Ref", "Resolution", "Type", "For / against / abstain", "Outcome", "Owner"],
               ["{{ r.ref }}", "{{ r.title }}", "{{ r.type }}", "{{ r.votes }}", "{% cellbg r.bg %}{{ r.outcome }}", "{{ r.owner }}"],
               "r in resolutions", [2.6, 5.6, 1.8, 2.6, 2.0, 2.4])
    para(doc, "{%p for r in resolutions %}")
    para(doc, "{{ r.ref }}: {{ r.title }}", style="Heading 3")
    runs(doc, [("RESOLVED to ", {"bold": True}), ("{{ r.text }}.", {})])
    runs(doc, [("Agenda item {{ r.item }}. Proposed by {{ r.proposer }}; seconded by {{ r.seconder }}. {{ r.vote_line }} "
                "Decision rule: {{ r.rule }}. ", {"italic": True, "color": GREY}), ("{{ r.outcome }}.", {"bold": True})])
    para(doc, "{%p endfor %}")
    para(doc, "")
    para(doc, "Certified as a true extract of the resolutions of the above meeting, at which a quorum was present "
              "({{ quorum_short }}).")
    para(doc, "{{ secretary }}, Secretary to the {{ body.name }}")
    para(doc, "Signature: ____________________   Date: ___________", color=GREY)
    return doc


def build_matters_arising(latin, arabic_font) -> Document:
    doc = new_document(latin, arabic_font, "Matters arising")
    title_block(doc, "Matters arising", "متابعة القرارات والمهام",
                "For the next meeting of the {{ body.name }}{% if next_meeting %} on {{ next_meeting }}{% endif %}")
    para(doc, "Prepared from the action log and resolutions register as at {{ ma.as_of }}, after meeting {{ meeting.id }}.",
         italic=True, color=GREY)
    matters_arising_block(doc, "ma")
    return doc


BUILDERS = {"agenda_pack": build_agenda_pack, "minutes": build_minutes, "resolutions": build_resolutions,
            "matters_arising": build_matters_arising}


def build_templates(folder: Path | str, latin="Calibri", arabic_font="Noto Naskh Arabic") -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, fn in BUILDERS.items():
        path = folder / f"{name}.docx"
        fn(latin, arabic_font).save(path)
        out.append(path)
    return out

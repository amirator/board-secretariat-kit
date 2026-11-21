"""Load and check the company setup and a meeting file; apply quorum, voting and numbering rules."""
from __future__ import annotations

import datetime as dt
import math
import re
from fractions import Fraction
from dataclasses import dataclass, field
from pathlib import Path

import yaml

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
PURPOSES = {"Decision", "Discussion", "Information", "Procedural"}
RES_TYPES = {"ordinary", "special"}
AGENDA_KEYS = {"no", "title", "purpose", "presenter", "minutes", "papers"}
ACTION_STATUSES = ["Open", "In progress", "Closed", "Deferred"]
IMPL_STATUSES = ["Not started", "In progress", "Implemented", "Not applicable"]


class InputError(ValueError):
    """Raised with every problem found in an input file, not just the first."""

    def __init__(self, problems: list[str], source: str = "input"):
        self.problems = problems
        super().__init__(f"{source}: {len(problems)} problem(s)\n  - " + "\n  - ".join(problems))


@dataclass
class Person:
    id: str
    name: str
    title: str
    name_ar: str = ""
    email: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.title})"


@dataclass
class Body:
    code: str
    name: str
    name_ar: str
    prefix: str
    members: list[str]
    chair: str
    min_fraction: float
    min_count: int
    special_majority: float = 2 / 3
    chair_casting_vote: bool = False

    def quorum_required(self) -> int:
        return max(self.min_count, math.ceil(self.min_fraction * len(self.members)))


@dataclass
class Company:
    name: str
    name_ar: str
    registered_office: str
    timezone: str
    weekend: list[int]
    show_hijri: bool
    due_soon_days: int
    latin_font: str
    arabic_font: str
    secretary: str
    people: dict[str, Person]
    bodies: dict[str, Body]

    def person(self, pid: str) -> Person:
        return self.people[pid]


def _read_yaml(path: Path | str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise InputError(["file is empty or not a YAML mapping"], str(path))
    return data


def _fraction(value, name: str, problems: list[str]) -> float:
    """Accept 0.75, "75%" or "2/3"."""
    try:
        text = str(value).strip()
        if text.endswith("%"):
            out = float(text[:-1]) / 100
        else:
            out = float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        problems.append(f"{name}: {value!r} is not a fraction such as 2/3, 0.75 or 75%")
        return 2 / 3
    if not 0 < out <= 1:
        problems.append(f"{name}: must be between 0 and 1")
    return out


def load_company(path: Path | str) -> Company:
    raw = _read_yaml(path)
    problems: list[str] = []
    c = raw.get("company") or {}
    for key in ("name", "secretary"):
        if not c.get(key):
            problems.append(f"company.{key} is required")
    people: dict[str, Person] = {}
    for p in raw.get("people") or []:
        if not p.get("id") or not p.get("name") or not p.get("title"):
            problems.append(f"person entry needs id, name and title: {p}")
            continue
        if p["id"] in people:
            problems.append(f"duplicate person id {p['id']}")
        people[p["id"]] = Person(p["id"], p["name"], p["title"], p.get("name_ar", ""), p.get("email", ""))
    bodies: dict[str, Body] = {}
    for code, b in (raw.get("bodies") or {}).items():
        members = list(b.get("members") or [])
        for m in members + [b.get("chair")]:
            if m not in people:
                problems.append(f"bodies.{code}: unknown person id {m!r}")
        q = b.get("quorum") or {}
        bodies[code] = Body(
            code=code, name=b.get("name", code), name_ar=b.get("name_ar", ""),
            prefix=b.get("resolution_prefix", code), members=members, chair=b.get("chair"),
            min_fraction=float(q.get("min_fraction", 0.5)), min_count=int(q.get("min_count", 1)),
            special_majority=_fraction(b.get("special_majority", "2/3"), f"bodies.{code}.special_majority", problems),
            chair_casting_vote=bool(b.get("chair_casting_vote", False)),
        )
    if not bodies:
        problems.append("at least one body (board or committee) is required")
    if c.get("secretary") and c["secretary"] not in people:
        problems.append(f"company.secretary {c['secretary']!r} is not in people")
    weekend = []
    for d in c.get("weekend", ["Fri", "Sat"]):
        if d not in WEEKDAYS:
            problems.append(f"company.weekend: {d!r} is not one of {', '.join(WEEKDAYS)}")
        else:
            weekend.append(WEEKDAYS[d])
    if problems:
        raise InputError(problems, str(path))
    fonts = c.get("fonts") or {}
    return Company(
        name=c["name"], name_ar=c.get("name_ar", ""), registered_office=c.get("registered_office", ""),
        timezone=c.get("timezone", "Asia/Riyadh"), weekend=weekend, show_hijri=bool(c.get("show_hijri", False)),
        due_soon_days=int(c.get("due_soon_days", 7)), latin_font=fonts.get("latin", "Calibri"),
        arabic_font=fonts.get("arabic", "Noto Naskh Arabic"), secretary=c["secretary"], people=people, bodies=bodies,
    )


# ---------------------------------------------------------------- rules

def roll_to_working_day(day: dt.date, weekend: list[int]) -> dt.date:
    """Move a date that falls on the weekend forward to the next working day."""
    while day.weekday() in weekend:
        day += dt.timedelta(days=1)
    return day


def next_ref(existing: list[str], prefix: str, year: int) -> str:
    """Next resolution number in the series PREFIX/YEAR/NNN (numbering restarts each year)."""
    pat = re.compile(rf"^{re.escape(prefix)}/{year}/(\d+)$")
    nums = [int(m.group(1)) for r in existing if (m := pat.match(r))]
    return f"{prefix}/{year}/{max(nums, default=0) + 1:03d}"


def next_action_id(existing: list[str], year: int) -> str:
    pat = re.compile(rf"^A-{year}-(\d+)$")
    nums = [int(m.group(1)) for r in existing if (m := pat.match(r))]
    return f"A-{year}-{max(nums, default=0) + 1:03d}"


def tally(votes, eligible: int, rtype: str, body: Body, casting_vote: str | None = None) -> dict:
    """Count a vote and decide the outcome.

    `votes` is "unanimous" or a mapping with for/against/abstain. Directors with a declared conflict
    are already excluded from `eligible`. Ordinary resolutions need more votes for than against;
    special resolutions need votes for of at least `special_majority` of eligible directors present.
    """
    if votes == "unanimous":
        f, a, ab = eligible, 0, 0
    elif isinstance(votes, dict):
        f, a, ab = (int(votes.get(k, 0)) for k in ("for", "against", "abstain"))
    else:
        raise ValueError(f"votes must be 'unanimous' or a for/against/abstain mapping, got {votes!r}")
    if min(f, a, ab) < 0:
        raise ValueError("vote counts cannot be negative")
    if f + a + ab > eligible:
        raise ValueError(f"{f + a + ab} votes recorded but only {eligible} eligible voter(s) present")
    if rtype == "special":
        needed = math.ceil(body.special_majority * eligible - 1e-9)
        carried = f >= needed
        rule = f"special majority: at least {needed} of {eligible} eligible votes in favour"
    else:
        needed = None
        carried = f > a
        rule = "simple majority of votes cast"
        if f == a and f > 0 and casting_vote in ("for", "against"):
            if not body.chair_casting_vote:
                raise ValueError(f"{body.name} has no chair's casting vote")
            carried = casting_vote == "for"
            rule += f"; tie decided by the Chair's casting vote ({casting_vote})"
    return {"for": f, "against": a, "abstain": ab, "eligible": eligible, "unanimous": f == eligible and f > 0,
            "carried": carried, "outcome": "Carried" if carried else "Not carried", "rule": rule, "needed": needed}


def parse_date(value, field_name: str, problems: list[str]) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        problems.append(f"{field_name}: {value!r} is not a date (use YYYY-MM-DD)")
        return None


def parse_time(value, field_name: str, problems: list[str]) -> dt.time | None:
    if isinstance(value, int):  # YAML 1.1 reads 16:00 as sexagesimal minutes
        return dt.time(value // 60, value % 60)
    try:
        return dt.time.fromisoformat(str(value))
    except (TypeError, ValueError):
        problems.append(f"{field_name}: {value!r} is not a time (use \"HH:MM\")")
        return None


# ---------------------------------------------------------------- meeting

@dataclass
class Meeting:
    id: str
    body: Body
    title: str
    date: dt.date
    start: dt.time
    venue: str
    notice_date: dt.date
    next_meeting: dt.date | None
    previous_minutes: str
    agenda: list[dict]
    present: list[str]
    apologies: list[str]
    in_attendance: list[dict]
    conflicts: list[dict]
    record: dict | None
    resolutions: list[dict] = field(default_factory=list)  # filled by number_meeting()
    actions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def quorum_required(self) -> int:
        return self.body.quorum_required()

    @property
    def members_present(self) -> list[str]:
        return [p for p in self.present if p in self.body.members]

    @property
    def quorate(self) -> bool:
        return len(self.members_present) >= self.quorum_required

    def conflicted_on(self, item_no: int) -> list[str]:
        return [c["person"] for c in self.conflicts if int(c["item"]) == int(item_no)]

    def eligible_voters(self, item_no: int) -> list[str]:
        out = set(self.conflicted_on(item_no))
        return [p for p in self.members_present if p not in out]

    def timings(self) -> list[tuple[dt.time, dt.time]]:
        t = dt.datetime.combine(self.date, self.start)
        out = []
        for item in self.agenda:
            end = t + dt.timedelta(minutes=int(item.get("minutes", 0)))
            out.append((t.time(), end.time()))
            t = end
        return out


def load_meeting(path: Path | str, company: Company) -> Meeting:
    """Read a meeting file and check it against the company setup. Raises InputError listing every problem."""
    raw = _read_yaml(path)
    problems: list[str] = []
    m = raw.get("meeting") or {}
    for key in ("id", "body", "title", "date", "start", "venue", "notice_date"):
        if m.get(key) in (None, ""):
            problems.append(f"meeting.{key} is required")
    body = company.bodies.get(m.get("body"))
    if m.get("body") and body is None:
        problems.append(f"meeting.body {m.get('body')!r} is not defined in the company file")
    date = parse_date(m.get("date"), "meeting.date", problems) if m.get("date") else None
    start = parse_time(m.get("start"), "meeting.start", problems) if m.get("start") is not None else None
    notice = parse_date(m.get("notice_date"), "meeting.notice_date", problems) if m.get("notice_date") else None
    nxt = parse_date(m["next_meeting"], "meeting.next_meeting", problems) if m.get("next_meeting") else None
    if date and notice and notice > date:
        problems.append("meeting.notice_date is after the meeting date")
    if date and nxt and nxt <= date:
        problems.append("meeting.next_meeting must be after the meeting date")

    agenda = list(raw.get("agenda") or [])
    if not agenda:
        problems.append("agenda must have at least one item")
    seen = set()
    for i, item in enumerate(agenda):
        if False in item:  # YAML 1.1 reads an unquoted `no:` key as boolean False
            item["no"] = item.pop(False)
        if "item" in item:
            item["no"] = item.pop("item")
        no = item.get("no")
        extra = sorted(str(k) for k in item if k not in AGENDA_KEYS)
        if extra:
            problems.append(f"agenda item {no}: unknown field(s) {extra}; put quotes around text that contains commas")
        if not isinstance(no, int):
            problems.append(f"agenda[{i}].no must be a whole number")
        elif no in seen:
            problems.append(f"agenda item {no} appears twice")
        seen.add(no)
        if not item.get("title"):
            problems.append(f"agenda item {no}: title is required")
        if item.get("purpose", "Discussion") not in PURPOSES:
            problems.append(f"agenda item {no}: purpose must be one of {sorted(PURPOSES)}")
        if item.get("presenter") and item["presenter"] not in company.people:
            problems.append(f"agenda item {no}: unknown presenter {item['presenter']!r}")
        item.setdefault("purpose", "Discussion")
        item.setdefault("papers", [])
        item.setdefault("minutes", 0)

    att = raw.get("attendance") or {}
    present = list(att.get("present") or [])
    apologies = list(att.get("apologies") or [])
    in_att = list(att.get("in_attendance") or [])
    for pid in present + apologies + [x.get("person") for x in in_att]:
        if pid not in company.people:
            problems.append(f"attendance: unknown person id {pid!r}")
    if set(present) & set(apologies):
        problems.append(f"attendance: {sorted(set(present) & set(apologies))} listed as both present and apologies")
    if body:
        for pid in present + apologies:
            if pid in company.people and pid not in body.members:
                problems.append(f"attendance: {pid} is not a member of {body.name}; list them under in_attendance")

    conflicts = list(raw.get("conflicts") or [])
    for c in conflicts:
        if c.get("person") not in present:
            problems.append(f"conflict: {c.get('person')!r} is not listed as present")
        if c.get("item") not in seen:
            problems.append(f"conflict: agenda item {c.get('item')!r} does not exist")

    record = raw.get("record")
    if record:
        for r in record.get("resolutions") or []:
            if r.get("item") not in seen:
                problems.append(f"resolution {r.get('title')!r}: agenda item {r.get('item')!r} does not exist")
            for k in ("title", "text"):
                if not r.get(k):
                    problems.append(f"resolution on item {r.get('item')}: {k} is required")
            if r.get("type", "ordinary") not in RES_TYPES:
                problems.append(f"resolution {r.get('title')!r}: type must be ordinary or special")
            for k in ("proposer", "seconder"):
                if r.get(k) and r[k] not in present:
                    problems.append(f"resolution {r.get('title')!r}: {k} {r[k]!r} is not a member present")
            if r.get("owner") and r["owner"] not in company.people:
                problems.append(f"resolution {r.get('title')!r}: unknown owner {r['owner']!r}")
        for a in record.get("actions") or []:
            if a.get("owner") not in company.people:
                problems.append(f"action {a.get('action')!r}: unknown owner {a.get('owner')!r}")
            if a.get("item") not in seen:
                problems.append(f"action {a.get('action')!r}: agenda item {a.get('item')!r} does not exist")
            a["due"] = parse_date(a.get("due"), f"action {a.get('action')!r} due", problems)
        for u in record.get("action_updates") or []:
            if u.get("status") not in ACTION_STATUSES:
                problems.append(f"action update {u.get('id')}: status must be one of {ACTION_STATUSES}")
            if u.get("due") is not None:
                u["due"] = parse_date(u["due"], f"action update {u.get('id')} due", problems)
        for d in record.get("deferred") or []:
            if d not in seen:
                problems.append(f"deferred item {d!r} is not on the agenda")
        for k in ("opened", "closed"):
            if record.get(k) is not None:
                record[k] = parse_time(record[k], f"record.{k}", problems)
        if record.get("resolutions") and body and date and len([p for p in present if p in body.members]) < body.quorum_required():
            problems.append("resolutions are recorded but the meeting was not quorate")

    if problems:
        raise InputError(problems, str(path))
    return Meeting(
        id=str(m["id"]), body=body, title=m["title"], date=date, start=start, venue=m["venue"],
        notice_date=notice, next_meeting=nxt, previous_minutes=m.get("previous_minutes", ""),
        agenda=sorted(agenda, key=lambda x: x["no"]), present=present, apologies=apologies,
        in_attendance=in_att, conflicts=conflicts, record=record,
    )


def number_meeting(meeting: Meeting, company: Company, existing_refs: list[str], existing_action_ids: list[str]) -> None:
    """Give each recorded resolution its register number and vote result, and each action its ID and due date."""
    if not meeting.record:
        return
    refs, ids = list(existing_refs), list(existing_action_ids)
    year = meeting.date.year
    resolutions = []
    for r in meeting.record.get("resolutions") or []:
        ref = next_ref(refs, meeting.body.prefix, year)
        refs.append(ref)
        eligible = meeting.eligible_voters(r["item"])
        try:
            t = tally(r.get("votes", "unanimous"), len(eligible), r.get("type", "ordinary"), meeting.body, r.get("casting_vote"))
        except ValueError as exc:
            raise InputError([f"resolution {r['title']!r}: {exc}"], meeting.id) from exc
        resolutions.append({**r, "ref": ref, "type": r.get("type", "ordinary"), "tally": t,
                            "excluded": meeting.conflicted_on(r["item"])})
    actions = []
    for a in meeting.record.get("actions") or []:
        aid = next_action_id(ids, year)
        ids.append(aid)
        due = roll_to_working_day(a["due"], company.weekend)
        if due != a["due"]:
            meeting.warnings.append(f"{aid}: due date {a['due']:%a %d %b %Y} falls on the weekend, moved to {due:%a %d %b %Y}")
        if due < meeting.date:
            meeting.warnings.append(f"{aid}: due date is before the meeting date")
        actions.append({**a, "id": aid, "due": due, "requested_due": a["due"]})
    meeting.resolutions, meeting.actions = resolutions, actions

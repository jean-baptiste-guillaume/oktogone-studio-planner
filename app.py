import json
import os
import sqlite3
import calendar
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv("PLANNER_DB", str(ROOT / "planner.db")))
TZ = ZoneInfo("Europe/Paris")
app = FastAPI(title="Oktogone Studio Planner", version="0.1")


@contextmanager
def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS availability(resource_id INTEGER NOT NULL, day TEXT NOT NULL, slot TEXT NOT NULL CHECK(slot IN ('none','am','pm','full')), PRIMARY KEY(resource_id, day), FOREIGN KEY(resource_id) REFERENCES resources(id));
CREATE TABLE IF NOT EXISTS busy(id INTEGER PRIMARY KEY, resource_id INTEGER NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL, FOREIGN KEY(resource_id) REFERENCES resources(id));
CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, title TEXT NOT NULL, trainer_id INTEGER NOT NULL, repeats INTEGER NOT NULL, shoots INTEGER NOT NULL, min_gap INTEGER NOT NULL, max_gap INTEGER NOT NULL, makeup INTEGER NOT NULL, coach INTEGER NOT NULL, consecutive INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS options(id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, payload TEXT NOT NULL, score INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('option','selected','confirmed','cancelled')), created_at TEXT NOT NULL, FOREIGN KEY(request_id) REFERENCES requests(id));
"""


def seed(con):
    con.executescript("DELETE FROM options; DELETE FROM requests; DELETE FROM busy; DELETE FROM availability; DELETE FROM resources;")
    people = [(1, "Studio A", "studio"), (2, "Studio B", "studio"), (3, "Studio C", "studio"), (4, "Salle répétition", "rehearsal"), (5, "Sophie", "makeup"), (6, "Emma", "makeup"), (7, "Marc Laurent", "trainer"), (8, "Claire", "coach"), (9, "Julien", "coach")]
    con.executemany("INSERT INTO resources VALUES (?,?,?)", people)
    start = date(2026, 11, 9)
    for i in range(240):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            for rid in range(1, 10):
                con.execute("INSERT INTO availability VALUES (?,?,?)", (rid, d.isoformat(), "full"))
    blocked = [(1, "2026-11-19", "2026-11-20"), (2, "2026-11-23", "2026-11-24"), (3, "2026-11-26", "2026-11-27"), (5, "2026-11-24", "2026-11-25"), (6, "2026-11-19", "2026-11-20")]
    for rid, a, b in blocked:
        con.execute("INSERT INTO busy(resource_id,start,end,title,source) VALUES (?,?,?,?,?)", (rid, a+"T09:00:00+01:00", b+"T09:00:00+01:00", "Occupation de démonstration", "demo"))


def initialize():
    with connection() as con:
        con.executescript(SCHEMA)
        if con.execute("SELECT count(*) FROM resources").fetchone()[0] == 0:
            seed(con)
        else:
            # Non-destructive upgrade of databases created by POC V1.
            con.execute("INSERT OR IGNORE INTO resources(id,name,kind) VALUES (9,'Julien','coach')")
            resource_ids=[r[0] for r in con.execute("SELECT id FROM resources")]
            start=date(2026,11,9)
            for i in range(240):
                d=start+timedelta(days=i)
                if d.weekday()<5:
                    for rid in resource_ids:
                        con.execute("INSERT OR IGNORE INTO availability(resource_id,day,slot) VALUES (?,?,?)",(rid,d.isoformat(),"full"))


initialize()


def rows(con, query, params=()):
    return [dict(r) for r in con.execute(query, params).fetchall()]


class AvailabilityChange(BaseModel):
    resource_id: int
    day: date
    slot: str


class Blackout(BaseModel):
    start: date
    end: date


class RequestInput(BaseModel):
    title: str = "MOOC Management de projet"
    trainer_id: int = 7
    repeats: int = Field(default=1, ge=1, le=3)
    shoots: int = Field(default=2, ge=1, le=4)
    min_gap: int = Field(default=7, ge=0, le=60)
    max_gap: int = Field(default=14, ge=0, le=60)
    makeup: bool = True
    coach: bool = True
    preferred_coach_id: int | None = None
    consecutive: bool = True
    planning_day: date = date(2026, 11, 5)
    min_production_months: int = Field(default=1, ge=0, le=12)
    trainer_blackouts: list[Blackout] = Field(default_factory=list)
    from_day: date = date(2026, 11, 9)
    to_day: date = date(2027, 4, 30)


def add_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def trainer_unavailable(request, day):
    return any(b.start <= day <= b.end for b in request.trainer_blackouts)


def interval(day, slot="full"):
    a, b = {"full": (9, 17), "am": (9, 13), "pm": (13, 17), "repetition": (14, 17)}[slot]
    return (datetime(day.year, day.month, day.day, a, tzinfo=TZ), datetime(day.year, day.month, day.day, b, tzinfo=TZ))


def available(con, rid, day, slot="full"):
    if day.weekday() >= 5:
        return False
    r = con.execute("SELECT slot FROM availability WHERE resource_id=? AND day=?", (rid, day.isoformat())).fetchone()
    declared = r[0] if r else "none"
    if slot == "full" and declared != "full":
        return False
    if slot == "repetition" and declared not in ("pm", "full"):
        return False
    if slot in ("am", "pm") and declared not in (slot, "full"):
        return False
    a, b = interval(day, slot)
    for busy in con.execute("SELECT start,end FROM busy WHERE resource_id=?", (rid,)):
        begin = datetime.fromisoformat(busy[0]); end = datetime.fromisoformat(busy[1])
        if begin.tzinfo is None: begin = begin.replace(tzinfo=TZ)
        if end.tzinfo is None: end = end.replace(tzinfo=TZ)
        if a < end and begin < b:
            return False
    return True


def workdays(a, count):
    result = []
    d = a
    while len(result) < count:
        if d.weekday() < 5: result.append(d)
        d += timedelta(days=1)
    return result


def make_candidates(con, request):
    if request.max_gap < request.min_gap or request.to_day <= request.from_day or request.planning_day > request.to_day:
        raise HTTPException(422, "Période ou délai invalide")
    if any(b.end < b.start for b in request.trainer_blackouts):
        raise HTTPException(422, "Période d'indisponibilité invalide")
    if request.preferred_coach_id is not None and (not request.coach or not con.execute("SELECT 1 FROM resources WHERE id=? AND kind='coach'", (request.preferred_coach_id,)).fetchone()):
        raise HTTPException(422, "Coach préféré invalide")
    studios = [1, 2, 3]
    makeup_people = [5, 6] if request.makeup else [None]
    coach_people = [r[0] for r in con.execute("SELECT id FROM resources WHERE kind='coach'")] if request.coach else [None]
    proposals = []
    day = max(request.from_day, request.planning_day + timedelta(days=60), add_months(request.planning_day, request.min_production_months))
    while day <= request.to_day:
        if day.weekday() >= 5:
            day += timedelta(days=1); continue
        shoots = workdays(day, request.shoots)
        if shoots[-1] > request.to_day:
            break
        if request.consecutive and any((b-a).days != 1 for a,b in zip(shoots, shoots[1:])):
            day += timedelta(days=1); continue
        for rid in studios:
            if not all(available(con, rid, d) and available(con, request.trainer_id, d) and not trainer_unavailable(request,d) for d in shoots): continue
            for mid in makeup_people:
                if mid and not all(available(con, mid, d) for d in shoots): continue
                for cid in coach_people:
                    rep = day - timedelta(days=request.min_gap)
                    while rep >= request.from_day and (day-rep).days <= request.max_gap:
                        reps = [rep - timedelta(days=7 * k) for k in range(request.repeats - 1, -1, -1)]
                        if reps[0] >= max(request.from_day, request.planning_day) and all(available(con,4,r,"repetition") and available(con,request.trainer_id,r,"repetition") and not trainer_unavailable(request,r) and (not cid or available(con,cid,r,"repetition")) for r in reps):
                            proposals.append({"repetitions":[r.isoformat() for r in reps], "shoots":[d.isoformat() for d in shoots], "studio_id":rid, "makeup_id":mid, "coach_id":cid, "trainer_id":request.trainer_id, "score":0, "trainer_blackouts":[b.model_dump(mode='json') for b in request.trainer_blackouts], "reasons":["Premier créneau compatible", "Studio identique sur les tournages", "Prestataire identique sur les tournages" if mid else "Maquillage non requis", "Délai de préparation respecté"]})
                        rep -= timedelta(days=1)
        day += timedelta(days=1)
        eligible = [p for p in proposals if request.preferred_coach_id is None or p["coach_id"] == request.preferred_coach_id]
        if len({tuple(p["shoots"]) for p in eligible}) >= 3: break
    proposals.sort(key=lambda p: (p["shoots"][0], p["studio_id"], p["repetitions"], p["coach_id"] or 0))
    # With a coach preference: earliest option irrespective of coach,
    # followed by two distinct shoot dates involving that preferred coach.
    selected, used_dates = [], set()
    def take(candidates, count):
        for p in candidates:
            key=tuple(p["shoots"])
            if key in used_dates: continue
            selected.append(p); used_dates.add(key)
            if len(selected)>=count: break
    if request.preferred_coach_id is not None and proposals:
        take(proposals, 1)
        take((p for p in proposals if p["coach_id"] == request.preferred_coach_id),3)
    else:
        take(proposals,3)
    return selected


@app.get("/")
def homepage():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/resources")
def resources():
    with connection() as con: return rows(con, "SELECT * FROM resources ORDER BY id")


@app.get("/api/availability/{resource_id}")
def get_availability(resource_id: int):
    with connection() as con:
        return {"days":rows(con, "SELECT day,slot FROM availability WHERE resource_id=? ORDER BY day", (resource_id,)), "busy":rows(con,"SELECT id,start,end,title,source FROM busy WHERE resource_id=? ORDER BY start",(resource_id,))}


@app.put("/api/availability")
def set_availability(item: AvailabilityChange):
    if item.slot not in ("none", "am", "pm", "full"): raise HTTPException(422, "Créneau invalide")
    with connection() as con:
        if not con.execute("SELECT 1 FROM resources WHERE id=?",(item.resource_id,)).fetchone(): raise HTTPException(404,"Ressource inconnue")
        con.execute("INSERT INTO availability VALUES (?,?,?) ON CONFLICT(resource_id,day) DO UPDATE SET slot=excluded.slot",(item.resource_id,item.day.isoformat(),item.slot))
    return {"ok":True}


@app.post("/api/match")
def match(request: RequestInput):
    with connection() as con: return make_candidates(con, request)


@app.post("/api/requests")
def create_request(request: RequestInput):
    with connection() as con:
        proposals = make_candidates(con, request)
        c = con.execute("INSERT INTO requests(title,trainer_id,repeats,shoots,min_gap,max_gap,makeup,coach,consecutive,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",(request.title,request.trainer_id,request.repeats,request.shoots,request.min_gap,request.max_gap,int(request.makeup),int(request.coach),int(request.consecutive),datetime.now(TZ).isoformat()))
        req_id=c.lastrowid
        for p in proposals: con.execute("INSERT INTO options(request_id,payload,score,status,created_at) VALUES (?,?,?,?,?)",(req_id,json.dumps(p),p["score"],"option",datetime.now(TZ).isoformat()))
        return {"request_id":req_id,"options":rows(con,"SELECT id,payload,score,status FROM options WHERE request_id=?",(req_id,))}


@app.get("/api/requests")
def get_requests():
    with connection() as con:
        return rows(con,"SELECT r.id,r.title,r.created_at,o.id AS option_id,o.payload,o.status,o.score FROM requests r LEFT JOIN options o ON o.request_id=r.id ORDER BY r.id DESC,o.score DESC")


@app.post("/api/options/{option_id}/select")
def select_option(option_id:int):
    with connection() as con:
        o=con.execute("SELECT * FROM options WHERE id=?",(option_id,)).fetchone()
        if not o or o["status"] not in ("option","selected"): raise HTTPException(409,"Option non sélectionnable")
        con.execute("UPDATE options SET status='option' WHERE request_id=? AND status='selected'",(o["request_id"],))
        con.execute("UPDATE options SET status='selected' WHERE id=?",(option_id,))
    return {"ok":True}


@app.post("/api/options/{option_id}/confirm")
def confirm_option(option_id:int):
    with connection() as con:
        o=con.execute("SELECT * FROM options WHERE id=?",(option_id,)).fetchone()
        if not o or o["status"]!='selected': raise HTTPException(409,"Sélection du formateur requise")
        if con.execute("SELECT 1 FROM options WHERE request_id=? AND status='confirmed'",(o["request_id"],)).fetchone(): raise HTTPException(409,"Demande déjà confirmée")
        p=json.loads(o["payload"])
        blackout_ranges=[Blackout(**b) for b in p.get("trainer_blackouts",[])]
        for d in p["repetitions"]:
            if any(b.start<=date.fromisoformat(d)<=b.end for b in blackout_ranges): raise HTTPException(409,"Indisponibilité du formateur")
            for rid in [4,p["trainer_id"],p["coach_id"]]:
                if rid and not available(con,rid,date.fromisoformat(d),"repetition"): raise HTTPException(409,f"Conflit détecté en répétition : {d}")
        for d in p["shoots"]:
            if any(b.start<=date.fromisoformat(d)<=b.end for b in blackout_ranges): raise HTTPException(409,"Indisponibilité du formateur")
            for rid in [p["studio_id"],p["trainer_id"],p["makeup_id"]]:
                if rid and not available(con,rid,date.fromisoformat(d)): raise HTTPException(409,f"Conflit détecté en tournage : {d}")
        for d in p["repetitions"]:
            a,b=interval(date.fromisoformat(d),"repetition")
            for rid in [4,p["trainer_id"],p["coach_id"]]:
                if rid: con.execute("INSERT INTO busy(resource_id,start,end,title,source) VALUES (?,?,?,?,?)",(rid,a.isoformat(),b.isoformat(),"Répétition confirmée",f"option:{option_id}"))
        for d in p["shoots"]:
            a,b=interval(date.fromisoformat(d))
            for rid in [p["studio_id"],p["trainer_id"],p["makeup_id"]]:
                if rid: con.execute("INSERT INTO busy(resource_id,start,end,title,source) VALUES (?,?,?,?,?)",(rid,a.isoformat(),b.isoformat(),"Tournage confirmé",f"option:{option_id}"))
        con.execute("UPDATE options SET status='confirmed' WHERE id=?",(option_id,))
        con.execute("UPDATE options SET status='cancelled' WHERE request_id=? AND id!=?",(o["request_id"],option_id))
    return {"ok":True}


@app.post("/api/import-ics/{resource_id}")
async def import_ics(resource_id:int, file:UploadFile=File(...)):
    try:
        from icalendar import Calendar
        from dateutil.rrule import rrulestr
    except ImportError: raise HTTPException(500,"Installer requirements.txt")
    data=await file.read()
    if len(data)>2_000_000: raise HTTPException(413,"ICS trop volumineux (2 Mo max)")
    try: cal=Calendar.from_ical(data)
    except Exception: raise HTTPException(422,"ICS illisible")
    entries=[]
    limit=datetime.now(TZ)+timedelta(days=90)
    for component in cal.walk("VEVENT"):
        if str(component.get("TRANSP", "OPAQUE")).upper()=="TRANSPARENT": continue
        if not component.get("DTSTART") or not component.get("DTEND"): continue
        start=component.decoded("DTSTART"); end=component.decoded("DTEND")
        if isinstance(start,date) and not isinstance(start,datetime): start=datetime.combine(start,datetime.min.time(),TZ)
        if isinstance(end,date) and not isinstance(end,datetime): end=datetime.combine(end,datetime.min.time(),TZ)
        if start.tzinfo is None: start=start.replace(tzinfo=TZ)
        if end.tzinfo is None: end=end.replace(tzinfo=TZ)
        occurrences=[start]
        if component.get("RRULE"):
            try:
                occurrences=list(rrulestr(component.get("RRULE").to_ical().decode(),dtstart=start).between(datetime.now(TZ)-timedelta(days=1),limit,inc=True))[:200]
            except Exception: continue
        for occurrence in occurrences:
            finish=occurrence+(end-start)
            if finish>occurrence: entries.append((resource_id,occurrence.isoformat(),finish.isoformat(),str(component.get("SUMMARY","Occupation ICS"))[:100],"ics"))
    with connection() as con:
        if not con.execute("SELECT 1 FROM resources WHERE id=?",(resource_id,)).fetchone(): raise HTTPException(404,"Ressource inconnue")
        # Replace only prior ICS blocks for the selected resource, transactionally.
        con.execute("DELETE FROM busy WHERE resource_id=? AND source='ics'",(resource_id,))
        con.executemany("INSERT INTO busy(resource_id,start,end,title,source) VALUES (?,?,?,?,?)",entries)
    return {"imported":len(entries)}


@app.post("/api/reset")
def reset():
    with connection() as con: seed(con)
    return {"ok":True}

from v3 import install
install(app, globals())



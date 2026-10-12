"""HTTP API. One router shared by the AWS Lambda handler and the local server.

Every route except /api/health, /api/auth/* authenticates the caller, and
every data access is filtered through access.py on the server.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from statistics import mean

from . import access, audit, auth, config, engine, importer, interventions, records, settings, summary
from .access import Forbidden
from .auth import AuthError, Principal, directory
from .config import ConfigError
from .importer import ImportError_
from .interventions import InterventionError
from .schemas import SCHEMAS, describe, template_csv
from .storage import Conflict


@dataclass
class Request:
    method: str
    path: str
    query: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    ip: str = ""

    def json(self) -> dict:
        try:
            return json.loads(self.body or b"{}")
        except json.JSONDecodeError:
            raise BadRequest("Request body must be JSON") from None


class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


def respond(status: int, body, ctype: str = "application/json", extra: dict | None = None):
    if not isinstance(body, (bytes, str)):
        body = json.dumps(body, separators=(",", ":"), default=str)
    if isinstance(body, str):
        body = body.encode()
    return status, {"Content-Type": ctype, "Cache-Control": "no-store", **(extra or {})}, body


ROUTES: list[tuple[str, re.Pattern, callable, bool]] = []


def route(method: str, pattern: str, public: bool = False):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, public))
        return fn
    return deco


def handle(req: Request):
    try:
        for method, rx, fn, public in ROUTES:
            m = rx.match(req.path)
            if m and method == req.method:
                principal = None if public else auth.authenticate(req.headers)
                return fn(req, principal, *m.groups())
        return respond(404, {"error": "Not found"})
    except AuthError as e:
        return respond(401, {"error": str(e)})
    except Forbidden as e:
        return respond(403, {"error": str(e)})
    except NotFound as e:
        return respond(404, {"error": str(e) or "Not found"})
    except (BadRequest, ImportError_, InterventionError, ConfigError, ValueError) as e:
        return respond(400, {"error": str(e)})
    except Conflict as e:
        return respond(409, {"error": str(e)})
    except Exception as e:  # pragma: no cover - logged, never leaked
        import traceback
        traceback.print_exc()
        return respond(500, {"error": "Something went wrong on the server. The error has been logged.", "type": type(e).__name__})


# --------------------------------------------------------------------------- helpers
_dir_cache: dict = {"at": 0.0, "users": []}


def users_cached() -> list[dict]:
    if time.time() - _dir_cache["at"] > 300:
        _dir_cache["users"] = directory.list()
        _dir_cache["at"] = time.time()
    return _dir_cache["users"]


def user_names() -> dict[str, str]:
    return {u["username"]: u["name"] for u in users_cached()}


def period_of(req: Request, cfg: dict) -> str:
    p = req.query.get("period") or cfg["current_period"]
    if p not in {x["id"] for x in cfg["review_periods"]}:
        raise BadRequest("Unknown review period")
    return p


def context(p: Principal, period: str | None = None):
    cfg = config.active()
    period = period or cfg["current_period"]
    roster = records.roster()
    current = engine.snapshot(cfg["current_period"])["students"]
    snap = current if period == cfg["current_period"] else engine.snapshot(period)["students"]
    ids = access.visible_ids(p, roster, current)
    return cfg, period, roster, snap, ids


def apply_filters(q: dict, roster: dict, snap: dict, ids: set[str]) -> list[str]:
    out = []
    term = (q.get("q") or "").strip().lower()
    for sid in ids:
        st, s = roster.get(sid), snap.get(sid)
        if not st or not s:
            continue
        if q.get("dept") and st["department"] != q["dept"]:
            continue
        if q.get("course") and st["course"] != q["course"]:
            continue
        if q.get("year") and str(s["year"]) != q["year"]:
            continue
        if q.get("cohort") and str(st["admission_year"]) != q["cohort"]:
            continue
        if q.get("segment") and s["segment"]["id"] != q["segment"]:
            continue
        if q.get("band") and s["score"]["band"] != q["band"]:
            continue
        r = q.get("risk")
        if r:
            kind, _, level = r.partition(":")
            if kind == "any":
                if level not in (s["risk"]["academic"]["level"], s["risk"]["placement"]["level"]):
                    continue
            elif s["risk"].get(kind, {}).get("level") != level:
                continue
        if q.get("score_min") and (s["score"]["score"] is None or s["score"]["score"] < float(q["score_min"])):
            continue
        if q.get("score_max") and (s["score"]["score"] is None or s["score"]["score"] >= float(q["score_max"])):
            continue
        if term and term not in st["name"].lower() and term not in sid.lower():
            continue
        out.append(sid)
    return out


def review_reasons(s: dict, open_by_student: dict, overdue_by_student: dict) -> list[str]:
    reasons = []
    sid = s["student_id"]
    for kind, label in (("academic", "Academic"), ("placement", "Placement")):
        if s["risk"][kind]["level"] == "High" and not open_by_student.get(sid, {}).get(kind):
            reasons.append(f"High {label.lower()} risk, no open action")
    if overdue_by_student.get(sid):
        reasons.append(f"{overdue_by_student[sid]} overdue action(s)")
    if s["segment"]["id"] in ("declining", "disengaging"):
        reasons.append(s["segment"]["label"])
    if s["score"]["status"] != "ok":
        reasons.append("Score provisional" if s["score"]["status"] == "provisional" else "Not enough data")
    if s["risk"]["placement"]["level"] == "Insufficient data":
        reasons.append("No placement assessment on record")
    return reasons


def intervention_index(ids: set[str]):
    items = [i for i in interventions.all_items() if i["student_id"] in ids]
    open_by, overdue_by = defaultdict(dict), Counter()
    for i in items:
        if i["status"] != "Completed":
            open_by[i["student_id"]][i["risk"]] = True
            if i["overdue"]:
                overdue_by[i["student_id"]] += 1
    return items, open_by, overdue_by


def freshness() -> dict:
    cats = records.meta().get("categories", {})
    cfg = config.active()
    out = {}
    today = date.today()
    for c, schema in SCHEMAS.items():
        m = cats.get(c)
        if m:
            age = (today - date.fromisoformat(m["updated_at"][:10])).days
            out[c] = {"label": schema.label, "updated_at": m["updated_at"], "period": m["period"], "file": m["file"],
                      "rows": m["rows"], "age_days": age, "stale": age > cfg["freshness_days"].get(c, 180)}
        else:
            out[c] = {"label": schema.label, "updated_at": None, "stale": True}
    return out


def row_summary(sid: str, st: dict, s: dict, mentors: dict) -> dict:
    neg = [i for i in s["score"]["indicators"] if i["status"] == "used"]
    neg.sort(key=lambda i: i["max_points"] - i["points"], reverse=True)
    return {
        "student_id": sid, "name": st["name"], "dept": st["department"], "course": st["course"], "year": s["year"],
        "cohort": st["admission_year"], "mentor": mentors.get(st.get("mentor_username") or "", st.get("mentor_username")),
        "score": s["score"]["score"], "band": s["score"]["band"], "score_status": s["score"]["status"],
        "coverage": s["score"]["coverage"], "academic": s["risk"]["academic"]["level"],
        "academic_points": s["risk"]["academic"]["points"], "placement": s["risk"]["placement"]["level"],
        "placement_points": s["risk"]["placement"]["points"], "segment": s["segment"]["id"],
        "segment_label": s["segment"]["label"], "score_change": s["changes"].get("score_change"),
        "top_gap": neg[0]["label"] if neg else None,
    }


# --------------------------------------------------------------------------- public
@route("GET", "/api/health", public=True)
def health(req, p):
    return respond(200, {"ok": True, "mode": settings.MODE})


@route("POST", "/api/auth/login", public=True)
def login(req, p):
    if settings.MODE != "local":
        raise NotFound()
    body = req.json()
    try:
        token, principal = auth.local_login(body.get("username", ""), body.get("password", ""))
    except AuthError:
        audit.log(body.get("username", "?"), "auth.login_failed", "user", body.get("username", ""), ip=req.ip)
        raise
    audit.log(principal, "auth.login", "user", principal.username, ip=req.ip)
    return respond(200, {"token": token, "user": principal.as_dict()})


# --------------------------------------------------------------------------- session & meta
@route("GET", "/api/me")
def me(req, p):
    cfg = config.active()
    roster = records.roster()
    current = engine.snapshot(cfg["current_period"])["students"]
    ids = access.visible_ids(p, roster, current)
    sm = engine.scoring_meta() or {}
    perms = {
        "upload": p.role == "admin", "manage_users": p.role == "admin", "edit_config": p.role == "admin",
        "audit": p.role == "admin", "create_interventions": p.role in ("admin", "mentor", "placement"),
        "notes": p.role in ("admin", "hod", "mentor", "placement"), "summaries": p.role in ("admin", "hod", "mentor"),
        "dashboard": p.role != "student",
    }
    vis = [roster[i] for i in ids if i in roster]
    return respond(200, {
        "user": p.as_dict(), "permissions": perms, "students_visible": len(ids),
        "periods": cfg["review_periods"], "current_period": cfg["current_period"],
        "scoring": {"version": cfg["version"], "computed_at": sm.get("computed_at"), "run_id": sm.get("run_id")},
        "data_updated_at": records.meta().get("updated_at"),
        "filters": {"departments": sorted({s["department"] for s in vis}), "courses": sorted({s["course"] for s in vis}),
                    "cohorts": sorted({s["admission_year"] for s in vis}),
                    "segments": [{"id": s["id"], "label": s["label"]} for s in cfg["segments"]],
                    "bands": [b["label"] for b in cfg["bands"]]},
        "own_student_id": p.student_id if p.role == "student" else None,
        "pillars": [{"key": k, "label": v["label"], "weight": v["weight"]} for k, v in cfg["pillars"].items()],
        "risk_levels": cfg["risk"]["levels"],
    })


# --------------------------------------------------------------------------- dashboard
@route("GET", "/api/dashboard")
def dashboard(req, p):
    if p.role == "student":
        raise Forbidden("Students see their own profile only.")
    cfg = config.active()
    period = period_of(req, cfg)
    cfg, period, roster, snap, ids = context(p, period)
    sel = apply_filters(req.query, roster, snap, ids)
    S = [snap[i] for i in sel]
    scores = [s["score"]["score"] for s in S if s["score"]["score"] is not None]
    items, open_by, overdue_by = intervention_index(set(sel))
    levels = ["High", "Medium", "Low", "Insufficient data"]

    def by_dept(kind):
        out = defaultdict(Counter)
        for s in S:
            lv = s["risk"][kind]["level"]
            if lv != "Not applicable":
                out[roster[s["student_id"]]["department"]][lv] += 1
        return [{"dept": d, **{lv: c.get(lv, 0) for lv in levels}} for d, c in sorted(out.items())]

    # Trends across review periods for the same filtered students
    trend_scores, att, lms = [], defaultdict(list), defaultdict(list)
    for per in sorted(cfg["review_periods"], key=lambda x: x["start"]):
        ps = snap if per["id"] == period else engine.snapshot(per["id"])["students"]
        vals = [ps[i]["score"]["score"] for i in sel if i in ps and ps[i]["score"]["score"] is not None]
        hi = sum(1 for i in sel if i in ps and ps[i]["risk"]["academic"]["level"] == "High")
        n = sum(1 for i in sel if i in ps)
        trend_scores.append({"period": per["id"], "label": per["label"], "avg_score": round(mean(vals), 1) if vals else None,
                             "academic_high_pct": round(100 * hi / n, 1) if n else None, "students": n})
        for i in sel:
            if i not in ps:
                continue
            for m in ps[i]["series"].get("attendance", []):
                att[m["month"]].append(m["pct"])
            for w in ps[i]["series"].get("lms", []):
                lms[w["week"]].append(w["logins"])
    eng = defaultdict(Counter)
    selset = set(sel)
    for r in records.load("engagement").values():
        if r["student_id"] in selset:
            eng[r["activity_date"][:7]][r["activity_type"]] += 1

    needs = []
    for s in S:
        rs = review_reasons(s, open_by, overdue_by)
        if rs:
            st = roster[s["student_id"]]
            needs.append({"student_id": s["student_id"], "name": st["name"], "dept": st["department"], "year": s["year"],
                          "score": s["score"]["score"], "academic": s["risk"]["academic"]["level"],
                          "placement": s["risk"]["placement"]["level"], "reasons": rs,
                          "priority": (s["risk"]["academic"]["level"] == "High") * 3 + (s["risk"]["placement"]["level"] == "High") * 2
                          + bool(overdue_by.get(s["student_id"])) * 2 + len(rs)})
    needs.sort(key=lambda n: (-n["priority"], n["score"] if n["score"] is not None else 0))

    seg = Counter(s["segment"]["id"] for s in S)
    return respond(200, {
        "period": period, "count": len(S),
        "kpis": {
            "students": len(S), "avg_score": round(mean(scores), 1) if scores else None,
            "provisional": sum(s["score"]["status"] == "provisional" for s in S),
            "insufficient": sum(s["score"]["status"] == "insufficient" for s in S),
            "academic": dict(Counter(s["risk"]["academic"]["level"] for s in S)),
            "placement": dict(Counter(s["risk"]["placement"]["level"] for s in S if s["risk"]["placement"]["level"] != "Not applicable")),
            "needs_review": len(needs),
            "open_actions": sum(1 for i in items if i["status"] != "Completed"),
            "overdue_actions": sum(1 for i in items if i["overdue"]),
        },
        "distribution": [s["score"]["score"] for s in S if s["score"]["score"] is not None],
        "bands": [b for b in cfg["bands"]],
        "risk_by_dept": {"academic": by_dept("academic"), "placement": by_dept("placement")},
        "trends": {
            "scores": trend_scores,
            "attendance": [{"month": k, "avg": round(mean(v), 1), "n": len(v)} for k, v in sorted(att.items())],
            "lms": [{"week": k, "avg": round(mean(v), 2), "n": len(v)} for k, v in sorted(lms.items())],
            "participation": [{"month": k, **dict(c)} for k, c in sorted(eng.items())],
        },
        "segments": [{"id": s["id"], "label": s["label"], "count": seg.get(s["id"], 0)} for s in cfg["segments"]]
        + ([{"id": "insufficient", "label": "Not enough data to segment", "count": seg["insufficient"]}] if seg.get("insufficient") else []),
        "needs_review": needs[:60],
        "freshness": freshness(),
    })


# --------------------------------------------------------------------------- students
@route("GET", "/api/students")
def students(req, p):
    cfg = config.active()
    period = period_of(req, cfg)
    cfg, period, roster, snap, ids = context(p, period)
    sel = apply_filters(req.query, roster, snap, ids)
    mentors = user_names()
    rows = [row_summary(sid, roster[sid], snap[sid], mentors) for sid in sel]
    if req.query.get("review") == "1":
        _, open_by, overdue_by = intervention_index(set(sel))
        keep = {s for s in sel if review_reasons(snap[s], open_by, overdue_by)}
        rows = [r for r in rows if r["student_id"] in keep]
    key = req.query.get("sort", "academic_points")
    if rows and key not in rows[0]:
        key = "academic_points"
    desc = req.query.get("dir", "desc") == "desc"
    known = sorted((r for r in rows if r[key] is not None), key=lambda r: r[key], reverse=desc)
    rows = known + [r for r in rows if r[key] is None]  # blanks always last
    if req.query.get("format") == "csv":
        audit.log(p, "students.exported", "students", "", {"rows": len(rows), "filters": req.query}, ip=req.ip)
        cols = ["student_id", "name", "dept", "course", "year", "mentor", "score", "band", "score_status", "academic",
                "placement", "segment_label", "top_gap"]
        lines = [",".join(cols)] + [",".join('"' + str(r[c] if r[c] is not None else "").replace('"', '""') + '"' for c in cols) for r in rows]
        return respond(200, "\n".join(lines), "text/csv")
    size = min(int(req.query.get("size", 50)), 200)
    page = max(int(req.query.get("page", 1)), 1)
    return respond(200, {"period": period, "total": len(rows), "page": page, "size": size,
                         "rows": rows[(page - 1) * size: page * size]})


@route("GET", r"/api/students/([0-9A-Z]{4,12})")
def student(req, p, sid):
    cfg = config.active()
    period = period_of(req, cfg)
    cfg, period, roster, snap, ids = context(p, period)
    if sid not in ids:
        raise Forbidden("You don't have access to this student.")
    st = roster[sid]
    if sid not in snap:
        raise NotFound(f"{st['name']} was not enrolled in {period}.")
    s = access.redact_snapshot(p, {**snap[sid], "period": period})
    history = []
    for per in sorted(cfg["review_periods"], key=lambda x: x["start"]):
        ps = snap if per["id"] == period else engine.snapshot(per["id"])["students"]
        if sid in ps:
            h = ps[sid]
            history.append({"period": per["id"], "label": per["label"], "score": h["score"]["score"], "band": h["score"]["band"],
                            "status": h["score"]["status"], "coverage": h["score"]["coverage"],
                            "academic": h["risk"]["academic"]["level"], "placement": h["risk"]["placement"]["level"],
                            "segment": h["segment"]["label"], "pillars": h["score"]["pillars"]})
    items = [i for i in interventions.all_items() if i["student_id"] == sid]
    open_actions = {i["action_id"] for i in items if i["status"] != "Completed"}
    if p.role == "student":
        items = [{k: i[k] for k in ("id", "title", "status", "due_date", "owner_role")} for i in items]
    for a in s.get("actions", []):
        a["already_open"] = a["action_id"] in open_actions
        a["can_create"] = access.can_create_intervention(p, st, a["owner_role"])
    fr = {}
    today = date.today()
    for cat, src in s["sources"].items():
        upd = (src or {}).get("updated")
        age = (today - date.fromisoformat(upd[:10])).days if upd else None
        fr[cat] = {**(src or {}), "label": SCHEMAS[cat].label, "age_days": age,
                   "stale": age is None or age > cfg["freshness_days"].get(cat, 180)}
    for cat in SCHEMAS:
        if cat not in fr and cat != "students":
            fr[cat] = {"label": SCHEMAS[cat].label, "missing": True}
    mentors = user_names()
    sm = engine.scoring_meta() or {}
    audit.log(p, "student.viewed", "student", sid, {"period": period}, ip=req.ip)
    return respond(200, {
        "student": {"student_id": sid, "name": st["name"], "dept": st["department"], "course": st["course"],
                    "year": s["year"], "cohort": st["admission_year"], "gender": st.get("gender"), "hosteller": st.get("hosteller"),
                    "mentor_username": st.get("mentor_username"), "mentor": mentors.get(st.get("mentor_username") or "", st.get("mentor_username"))},
        "period": period, "snapshot": s, "history": history, "interventions": items, "freshness": fr,
        "scoring": {"version": cfg["version"], "computed_at": sm.get("computed_at"), "run_id": sm.get("run_id")},
        "summaries": summary.saved(sid) if access.sees_sensitive(p) else [],
        "segment_def": next((x for x in cfg["segments"] if x["id"] == s["segment"]["id"]), None),
        "can": {"create": p.role in ("admin", "mentor", "placement") and any(access.can_create_intervention(p, st, r) for r in ("mentor", "placement")),
                "summary": access.sees_sensitive(p)},
    })


@route("GET", r"/api/students/([0-9A-Z]{4,12})/summary-draft")
def summary_draft(req, p, sid):
    access.require_role(p, "admin", "hod", "mentor")
    cfg, period, roster, snap, ids = context(p, period_of(req, config.active()))
    if sid not in ids or sid not in snap:
        raise Forbidden("You don't have access to this student.")
    history = []
    for per in sorted(cfg["review_periods"], key=lambda x: x["start"]):
        ps = engine.snapshot(per["id"])["students"]
        if sid in ps:
            history.append({"period": per["id"], "score": ps[sid]["score"]["score"]})
    text = summary.draft(roster[sid], {**snap[sid], "period": period}, history, cfg, sensitive=True)
    audit.log(p, "summary.drafted", "student", sid, ip=req.ip)
    return respond(200, {"draft": text, "notice": "Draft generated from this student's records only. Review and edit before saving."})


@route("POST", r"/api/students/([0-9A-Z]{4,12})/summary")
def summary_save(req, p, sid):
    access.require_role(p, "admin", "hod", "mentor")
    cfg, period, roster, snap, ids = context(p)
    if sid not in ids:
        raise Forbidden("You don't have access to this student.")
    body = req.json()
    if not (body.get("text") or "").strip():
        raise BadRequest("The summary is empty.")
    return respond(200, summary.save(p, sid, body["text"][:4000], body.get("generated", "")))


# --------------------------------------------------------------------------- interventions
@route("GET", "/api/interventions")
def list_interventions(req, p):
    cfg, period, roster, snap, ids = context(p)
    items = [i for i in interventions.all_items() if i["student_id"] in ids or i["owner"] == p.username]
    q = req.query
    if q.get("status"):
        items = [i for i in items if i["status"] == q["status"]]
    if q.get("overdue") == "1":
        items = [i for i in items if i["overdue"]]
    if q.get("mine") == "1":
        items = [i for i in items if i["owner"] == p.username]
    if q.get("dept"):
        items = [i for i in items if i["dept"] == q["dept"]]
    if q.get("student"):
        items = [i for i in items if i["student_id"] == q["student"]]
    names = user_names()
    for i in items:
        cur = snap.get(i["student_id"])
        latest = cur["score"]["score"] if cur else None
        base = i["baseline"]["score"]
        i["progress"] = {"latest_score": latest, "change": round(latest - base, 1) if latest is not None and base is not None else None,
                         "latest_academic": cur["risk"]["academic"]["level"] if cur else None,
                         "latest_placement": cur["risk"]["placement"]["level"] if cur else None}
        i["owner_name"] = names.get(i["owner"], i["owner"])
        st = roster.get(i["student_id"], {})
        i["can"] = access.can_update_intervention(p, i, st)
        if p.role == "student":
            i["notes"] = []
    items.sort(key=lambda i: (i["status"] == "Completed", not i["overdue"], i["due_date"]))
    summary_counts = Counter(i["status"] for i in items)
    return respond(200, {"items": items, "counts": {**summary_counts, "overdue": sum(i["overdue"] for i in items)}})


@route("POST", "/api/interventions")
def create_intervention(req, p):
    body = req.json()
    cfg, period, roster, snap, ids = context(p)
    sid = body.get("student_id")
    if sid not in ids or sid not in snap:
        raise Forbidden("You don't have access to this student.")
    st = roster[sid]
    owner_role = body.get("owner_role") or (cfg["actions"].get(body.get("action_id") or "", {}).get("owner_role")) or "mentor"
    if not access.can_create_intervention(p, st, owner_role):
        raise Forbidden("Your role can't create this kind of action for this student.")
    if not body.get("owner"):
        body["owner"] = st.get("mentor_username") if owner_role == "mentor" else p.username
    body["owner_role"] = owner_role
    item = interventions.create(p, st, {**snap[sid], "period": period}, body)
    return respond(201, item)


@route("PATCH", r"/api/interventions/(INT-[0-9a-z-]+)")
def patch_intervention(req, p, iid):
    item = interventions.get(iid)
    if not item:
        raise NotFound("Intervention not found")
    roster = records.roster()
    level = access.can_update_intervention(p, item, roster.get(item["student_id"], {}))
    if not level:
        raise Forbidden("You can't update this action.")
    return respond(200, interventions.update(p, iid, req.json(), level))


@route("GET", "/api/owners")
def owners(req, p):
    if p.role == "student":
        raise Forbidden()
    return respond(200, [{"username": u["username"], "name": u["name"], "role": u["role"]}
                         for u in users_cached() if u["role"] in ("mentor", "placement", "hod", "admin") and u.get("active", True)])


# --------------------------------------------------------------------------- segments
@route("GET", "/api/segments")
def segments(req, p):
    access.require_role(p, "admin", "hod", "mentor", "placement")
    cfg = config.active()
    cfg, period, roster, snap, ids = context(p, period_of(req, cfg))
    sel = apply_filters({k: v for k, v in req.query.items() if k != "segment"}, roster, snap, ids)
    out = []
    for sd in cfg["segments"] + [{"id": "insufficient", "label": "Not enough data to segment", "owner": "Data team",
                                   "playbook": "Collect the missing records, then re-score.", "when": {}}]:
        g = [snap[i] for i in sel if snap[i]["segment"]["id"] == sd["id"]]
        if not g and sd["id"] == "insufficient":
            continue
        sc = [s["score"]["score"] for s in g if s["score"]["score"] is not None]
        reasons = Counter(r.split(" is ")[0] for s in g for r in s["segment"]["reasons"])
        out.append({"id": sd["id"], "label": sd["label"], "owner": sd["owner"], "playbook": sd["playbook"],
                    "rule": sd["when"], "count": len(g), "avg_score": round(mean(sc), 1) if sc else None,
                    "pillars": {k: round(mean(v), 1) if v else None for k, v in
                                {pk: [s["score"]["pillars"][pk] for s in g if s["score"]["pillars"].get(pk) is not None]
                                 for pk in cfg["pillars"]}.items()},
                    "common_reasons": reasons.most_common(4)})
    return respond(200, {"period": period, "segments": out, "pillars": {k: v["label"] for k, v in cfg["pillars"].items()}})


# --------------------------------------------------------------------------- uploads (admin)
@route("GET", "/api/templates")
def templates(req, p):
    access.require_role(p, "admin")
    return respond(200, describe())


@route("GET", r"/api/templates/([a-z_]+)\.csv")
def template(req, p, category):
    access.require_role(p, "admin")
    if category not in SCHEMAS:
        raise NotFound()
    return respond(200, template_csv(category), "text/csv", {"Content-Disposition": f'attachment; filename="{category}_template.csv"'})


@route("GET", "/api/uploads")
def uploads(req, p):
    access.require_role(p, "admin")
    return respond(200, [{k: u.get(k) for k in ("id", "category", "label", "filename", "reporting_period", "uploaded_by",
                                                "uploaded_at", "status", "total_rows", "accepted", "rejected", "duplicates",
                                                "committed_at", "applied")} for u in importer.list_uploads()[:200]])


@route("GET", r"/api/uploads/([0-9a-f-]+)")
def upload(req, p, uid):
    access.require_role(p, "admin")
    u = importer.get_upload(uid)
    if not u:
        raise NotFound()
    return respond(200, u)


@route("POST", "/api/uploads")
def new_upload(req, p):
    access.require_role(p, "admin")
    if len(req.body) > settings.MAX_UPLOAD_BYTES:
        raise BadRequest("File is larger than 6 MB. Split it by month or department.")
    if not req.body:
        raise BadRequest("The file is empty.")
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", req.query.get("filename") or "upload.csv")[:120]
    return respond(200, importer.validate(req.query.get("category", ""), name, req.body, req.query.get("period", ""), p))


@route("POST", r"/api/uploads/([0-9a-f-]+)/commit")
def commit_upload(req, p, uid):
    access.require_role(p, "admin")
    return respond(200, importer.commit(uid, p))


@route("POST", r"/api/uploads/([0-9a-f-]+)/discard")
def discard_upload(req, p, uid):
    access.require_role(p, "admin")
    return respond(200, importer.discard(uid, p))


# --------------------------------------------------------------------------- scoring config
@route("GET", "/api/config")
def get_config(req, p):
    if p.role == "student":
        raise Forbidden()
    m = engine.scoring_meta() or {}
    return respond(200, {"active": config.active(), "versions": config.versions(), "last_run": m,
                         "validation": _validation_report()})


@route("POST", "/api/config")
def set_config(req, p):
    access.require_role(p, "admin")
    body = req.json()
    cfg = config.activate(body.get("config") or {}, p, note=(body.get("note") or "")[:300])
    run = engine.recalculate(p, reason=f"scoring rules {cfg['version']} activated")
    return respond(200, {"version": cfg["version"], "run": run})


@route("POST", "/api/recalculate")
def recalc(req, p):
    access.require_role(p, "admin")
    return respond(200, engine.recalculate(p, reason=(req.json().get("reason") or "manual recalculation")[:200]))


def _validation_report():
    path = settings.ROOT / "config" / "validation_report.json"
    return json.loads(path.read_text()) if path.exists() else None


# --------------------------------------------------------------------------- audit & users (admin)
@route("GET", "/api/audit")
def audit_log(req, p):
    access.require_role(p, "admin")
    today = date.today()
    months = [req.query["month"]] if req.query.get("month") else [
        f"{(today.year * 12 + today.month - 1 - k) // 12}-{(today.month - 1 - k) % 12 + 1:02d}" for k in range(0, 12)]
    return respond(200, audit.recent(months, req.query.get("action", ""), int(req.query.get("limit", 300))))


@route("GET", "/api/users")
def list_users(req, p):
    access.require_role(p, "admin")
    return respond(200, directory.list())


@route("POST", "/api/users")
def create_user(req, p):
    access.require_role(p, "admin")
    b = req.json()
    for k in ("username", "name", "role"):
        if not (b.get(k) or "").strip():
            raise BadRequest(f"{k} is required")
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", b["username"].strip().lower()):
        raise BadRequest("Username: 3-40 characters, letters, digits, dots, dashes or underscores.")
    if b["role"] == "hod" and not b.get("dept"):
        raise BadRequest("A head of department needs a department.")
    if b["role"] == "student" and not b.get("student_id"):
        raise BadRequest("A student account needs a roll number.")
    u = directory.create(b["username"], b["name"].strip(), b["role"], b.get("dept", ""), b.get("student_id", ""),
                         b.get("password") or None, b.get("email", ""))
    _dir_cache["at"] = 0
    audit.log(p, "user.created", "user", u["username"], {"role": u["role"], "dept": u["dept"]}, ip=req.ip)
    return respond(201, u)


@route("POST", r"/api/users/([a-z0-9._-]+)/(enable|disable)")
def toggle_user(req, p, username, action):
    access.require_role(p, "admin")
    if username == p.username:
        raise BadRequest("You can't disable your own account.")
    directory.set_active(username, action == "enable")
    _dir_cache["at"] = 0
    audit.log(p, f"user.{action}d", "user", username, ip=req.ip)
    return respond(200, {"username": username, "active": action == "enable"})

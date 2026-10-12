"""FastAPI application (API Lambda behind CloudFront, or uvicorn locally).

Conventions (see docs/api.md):
  * Auth: `X-App-Authorization: Bearer <Cognito ID token>` (Authorization is
    reserved for CloudFront's SigV4 signature). Locally `Authorization` works too.
  * Writes (POST/PUT/PATCH) carry `x-amz-content-sha256` = hex SHA-256 of the body,
    as CloudFront OAC requires for IAM-protected Function URLs; it is verified here too.
  * Errors: {"error": {"code", "message", "details"}}; 401/403/404/409/422.
  * Lists: `limit` (max 200) and opaque `cursor`; responses include `next_cursor`.
  * Every API response is `Cache-Control: no-store`.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from . import accounts, audit, db, imports, insights, interventions, recordsvc, seed, views
from .auth import AuthError, authenticate, issue_local
from .categories import CATEGORIES, ValidationError, describe
from .policy import Denied, Principal, decide, grants, require
from .settings import curriculum, role_matrix, settings

log = logging.getLogger("ssp")
logging.basicConfig(level=logging.WARNING)

app = FastAPI(title="Smart Campus Student Success API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
              redoc_url=None)


def err(status: int, code: str, message: str, details=None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


@app.exception_handler(AuthError)
async def _auth(_, e):
    return err(401, "unauthenticated", str(e))


@app.exception_handler(Denied)
async def _denied(_, e):
    return err(403, "forbidden", str(e))


@app.exception_handler(recordsvc.NotFound)
async def _nf(_, e):
    return err(404, "not_found", str(e))


@app.exception_handler(ValidationError)
async def _val(_, e):
    return err(422, "validation_error", "Some values are not valid.", e.errors)


@app.exception_handler(RequestValidationError)
async def _rval(_, e):
    return err(422, "validation_error", "The request is not valid.",
               {".".join(str(x) for x in d["loc"][1:]) or "body": d["msg"] for d in e.errors()})


@app.exception_handler(recordsvc.Conflict)
async def _conf(_, e):
    return err(409, "conflict", str(e), {"current": e.current})


@app.exception_handler(ValueError)
async def _ve(_, e):
    return err(400, "bad_request", str(e))


@app.exception_handler(Exception)
async def _any(_, e):
    log.error("unhandled %s", type(e).__name__)  # no request data, tokens or payloads in logs
    return err(500, "server_error", "Something went wrong. The error has been logged.")


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH") and request.url.path.startswith("/api/"):
        body = await request.body()
        given = request.headers.get("x-amz-content-sha256")
        if given is None and settings().require_payload_hash:
            return err(400, "payload_hash_required", "Write requests must include x-amz-content-sha256.")
        if given is not None and given != "UNSIGNED-PAYLOAD" and given != hashlib.sha256(body).hexdigest():
            return err(400, "payload_hash_mismatch", "The request body does not match x-amz-content-sha256.")
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, private"
        resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


MFA_EXEMPT = ("/api/me", "/api/me/mfa/refresh")


class MfaRequired(Exception):
    pass


@app.exception_handler(MfaRequired)
async def _mfa(_, e):
    return err(403, "mfa_setup_required", "Set up your authenticator app to continue.")


def principal(request: Request) -> Principal:
    p = authenticate(request.headers)
    if p.mfa_required and not p.mfa_enabled and request.url.path not in MFA_EXEMPT:
        raise MfaRequired()
    return p


def ds_param(dataset: str = "real") -> str:
    if dataset not in recordsvc.DATASETS:
        raise ValidationError({"dataset": "must be real"})
    return dataset


# --------------------------------------------------------------------------- session
@app.get("/api/health")
def health():
    from .model_interface import status
    return {"ok": True, "prediction": status()}


@app.get("/api/auth/config")
def auth_config():
    s = settings()
    out = {"mode": s.auth_mode}
    if s.auth_mode == "local-demo":
        out["demo_personas"] = [{"username": p["username"], "display_name": p["display_name"]} for p in seed.PERSONAS]
        out["notice"] = "Local demonstration sign-in. Not available in AWS deployments."
    return out


@app.post("/api/auth/local/login")
async def local_login(request: Request):
    if settings().auth_mode != "local-demo":
        return err(404, "not_found", "Not found")
    body = await request.json()
    username = str(body.get("username", ""))
    sub = f"local-{username}"
    from .auth import load_principal
    if username not in {p["username"] for p in seed.PERSONAS} and not db.table().get(f"USER#{sub}", "PROFILE"):
        return err(401, "unauthenticated", "Unknown local account")
    load_principal(sub)
    return {"token": issue_local(sub)}


@app.post("/api/me/mfa/refresh")
def mfa_refresh(p: Principal = Depends(principal)):
    """Called after the browser enables the authenticator app with Cognito, so the new state applies at once."""
    from .auth import clear_principal_cache, load_principal
    clear_principal_cache(p.sub)
    q = load_principal(p.sub)
    audit.log(q, "mfa.status_checked", "user", q.username, {"enabled": q.mfa_enabled})
    return {"mfa": {"enabled": q.mfa_enabled, "required": q.mfa_required}}


# --------------------------------------------------------------------------- student self-registration (public)
@app.post("/api/register/start")
async def register_start(request: Request):
    from . import registration
    b = await request.json()
    return registration.start(b.get("student_id", ""), b.get("date_of_birth", ""), b.get("email", ""))


@app.post("/api/register/complete", status_code=201)
async def register_complete(request: Request):
    from . import registration
    b = await request.json()
    return registration.complete(b.get("student_id", ""), b.get("email", ""), b.get("code", ""), b.get("username", ""),
                                 b.get("password", ""))


@app.get("/api/me")
def me(p: Principal = Depends(principal)):
    m = role_matrix()
    perms = sorted({f"{g['resource']}:{g['action']}" for r in p.roles for g in m["roles"][r]["permissions"]})
    cfg = insights.active_config() if p.roles - {"system_admin"} else None
    return {"user": p.public(), "permissions": perms, "periods": insights.periods(),
            "current_period": insights.current_period(), "departments": curriculum()["departments"],
            "scoring_version": cfg["version"] if cfg else None,
            "datasets": [d for d in recordsvc.DATASETS if d in p.datasets]}


# --------------------------------------------------------------------------- students
@app.get("/api/students")
def students(p: Principal = Depends(principal), dataset: str = Depends(ds_param), department: str | None = None,
             year: int | None = None, period: str | None = None, risk: str | None = None, segment: str | None = None,
             status: str | None = None, q: str | None = None, sort: str = "name", limit: int = Query(50, le=200),
             cursor: str | None = None):
    rows = views.apply_filters(views.visible_rows(p, dataset, department, year, period),
                               {"risk": risk, "segment": segment, "status": status, "q": q})
    page, nxt = views.paginate(rows, limit, cursor, sort if sort in ("name", "student_id", "score", "department") else "name")
    return {"items": page, "total": len(rows), "next_cursor": nxt}


@app.post("/api/students", status_code=201)
async def create_student(request: Request, p: Principal = Depends(principal)):
    return recordsvc.create_master(p, await request.json())


@app.get("/api/students/{dataset}/{sid}")
def student(dataset: str, sid: str, p: Principal = Depends(principal)):
    out = views.profile(p, dataset, sid)
    audit.log(p, "student.viewed", "student", sid, dataset=dataset)
    return out


@app.patch("/api/students/{dataset}/{sid}")
async def update_student(dataset: str, sid: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return recordsvc.update_master(p, dataset, sid, b.get("data") or {}, b.get("version"))


@app.get("/api/students/{dataset}/{sid}/records")
def records(dataset: str, sid: str, category: str | None = None, period: str | None = None, p: Principal = Depends(principal)):
    return {"items": recordsvc.list_records(p, dataset, sid, category, period)}


@app.put("/api/students/{dataset}/{sid}/records/{category}/{period}")
async def put_record(dataset: str, sid: str, category: str, period: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    res = recordsvc.upsert(p, dataset, sid, category, period, b.get("data") or {}, b.get("version"))
    code = {"created": 201, "pending_correction": 202}.get(res["status"], 200)
    return JSONResponse(res, status_code=code)


@app.post("/api/students/{dataset}/{sid}/verify")
async def verify(dataset: str, sid: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return recordsvc.verify(p, dataset, sid, b.get("category"), b.get("record_key"), b.get("decision"), b.get("version"))


@app.get("/api/verifications")
def verifications(p: Principal = Depends(principal), dataset: str = Depends(ds_param)):
    if not (grants(p, "record.certification", "verify") or grants(p, "record.engagement", "verify")):
        raise Denied("Your role doesn't verify submissions.")
    return {"items": recordsvc.verification_queue(p, dataset)}


@app.put("/api/students/{dataset}/{sid}/mentor")
async def set_mentor(dataset: str, sid: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return accounts.assign_mentor(p, dataset, sid, b.get("mentor_sub"), b.get("version"))


# --------------------------------------------------------------------------- data entry helpers
@app.get("/api/entry/categories")
def entry_categories(p: Principal = Depends(principal)):
    """Record categories this user may enter, with field definitions for forms."""
    out = []
    for c in describe():
        acts = sorted({g["action"] for a in ("create", "update", "submit") for g in grants(p, f"record.{c['category']}", a)})
        if acts:
            out.append({**c, "actions": acts, "scopes": sorted({g["scope"] for a in acts for g in grants(p, f"record.{c['category']}", a)})})
    return {"categories": out, "periods": insights.periods()}


@app.get("/api/entry/classes")
def classes(p: Principal = Depends(principal)):
    return {"classes": [{"department": d, "year": y, "subject": s} for d, y, s in sorted(p.subjects)]}


@app.get("/api/entry/roster")
def roster(category: str, period: str, dataset: str = Depends(ds_param), department: str | None = None, year: int | None = None,
           subject: str | None = None, p: Principal = Depends(principal)):
    """Students this user may enter `category` for (in a class or college-wide), with existing values for `period`."""
    if category not in CATEGORIES:
        raise ValidationError({"category": "unknown category"})
    if not any(grants(p, f"record.{category}", a) for a in ("create", "update")):
        raise Denied("Your role can't enter this kind of data.")
    out = []
    depts = [department] if department else list(curriculum()["departments"])
    for dept in depts:
        for r in insights.listing(dataset, dept, year):
            m = {"dataset": dataset, "student_id": r["student_id"], "department": r["department"], "year": int(r["year"])}
            t = {**m, "subject": subject} if subject else m
            if decide(p, f"record.{category}", "create", t) is None:
                continue
            existing = [x for x in recordsvc.list_records(p, dataset, r["student_id"], category, period)
                        if not subject or x.get("subject") == subject]
            out.append({"student_id": r["student_id"], "name": r["name"], "department": r["department"], "year": r["year"],
                        "existing": existing})
    return {"items": sorted(out, key=lambda x: x["student_id"])}


# --------------------------------------------------------------------------- dashboards
@app.get("/api/dashboard")
def dashboard(p: Principal = Depends(principal), dataset: str = Depends(ds_param), department: str | None = None,
              year: int | None = None, period: str | None = None):
    if not grants(p, "student_insight", "read") or p.roles == {"student"}:
        raise Denied("Dashboards are for staff roles.")
    return views.dashboard(p, dataset, department, year, period)


@app.get("/api/analytics")
def analytics(p: Principal = Depends(principal), dataset: str = Depends(ds_param), department: str | None = None,
              year: int | None = None):
    if not grants(p, "student_insight", "read") or p.roles == {"student"}:
        raise Denied("Insights are for staff roles.")
    return views.analytics(p, dataset, department, year)


@app.get("/api/risk/academic")
def academic_risk(p: Principal = Depends(principal), dataset: str = Depends(ds_param), department: str | None = None,
                  year: int | None = None, period: str | None = None, level: str | None = None):
    rows = views.visible_rows(p, dataset, department, year, period)
    order = {"high": 0, "medium": 1, "insufficient_data": 2, "low": 3}
    rows = [r for r in rows if views._risk_level(r, "academic") and (not level or views._risk_level(r, "academic") == level)]
    out = sorted(rows, key=lambda r: (order.get(views._risk_level(r, "academic"), 9), r.get("score") or 0))
    return {"items": out[:300], "total": len(out)}


@app.get("/api/placement")
def placement(p: Principal = Depends(principal), dataset: str = Depends(ds_param), department: str | None = None,
              year: int | None = None):
    rows = [r for r in views.visible_rows(p, dataset, department, year)
            if views._risk_level(r, "placement") not in (None, "not_applicable")]
    from collections import Counter
    return {"items": sorted(rows, key=lambda r: ({"high": 0, "medium": 1, "insufficient_data": 2, "low": 3}.get(
        views._risk_level(r, "placement"), 9), r["student_id"])),
            "levels": dict(Counter(views._risk_level(r, "placement") for r in rows)),
            "segment_strong_academics_low_placement": sum("strong_academics_low_placement" in (r.get("segments") or []) for r in rows)}


@app.get("/api/segments")
def segments(p: Principal = Depends(principal), dataset: str = Depends(ds_param), department: str | None = None,
             year: int | None = None, period: str | None = None):
    cfg = insights.active_config()
    rows = views.visible_rows(p, dataset, department, year, period)
    out = []
    for key, s in cfg["segments"].items():
        members = [r for r in rows if key in (r.get("segments") or [])]
        out.append({"key": key, "label": s["label"], "count": len(members),
                    "members": [{"student_id": r["student_id"], "name": r.get("name"), "department": r["department"],
                                 "year": r["year"], "score": r.get("score")} for r in members[:200]]})
    return {"segments": out, "students": len(rows)}


# --------------------------------------------------------------------------- interventions
@app.get("/api/interventions")
def list_interventions(p: Principal = Depends(principal), dataset: str = Depends(ds_param), owner: str | None = None,
                       status: str | None = None, department: str | None = None, overdue: bool = False,
                       limit: int = Query(100, le=200), cursor: str | None = None):
    items, nxt = interventions.listing(p, dataset, owner=p.sub if owner == "me" else owner, status=status, dept=department,
                                       overdue_only=overdue, limit=limit, cursor=cursor)
    return {"items": items, "next_cursor": nxt}


@app.post("/api/students/{dataset}/{sid}/interventions", status_code=201)
async def create_intervention(dataset: str, sid: str, request: Request, p: Principal = Depends(principal)):
    return interventions.create(p, dataset, sid, await request.json())


@app.patch("/api/students/{dataset}/{sid}/interventions/{iid}")
async def update_intervention(dataset: str, sid: str, iid: str, request: Request, p: Principal = Depends(principal)):
    return interventions.update(p, dataset, sid, iid, await request.json())


@app.post("/api/students/{dataset}/{sid}/interventions/{iid}/notes", status_code=201)
async def add_note(dataset: str, sid: str, iid: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return interventions.add_note(p, dataset, sid, iid, b.get("text"), b.get("visibility", "staff"))


@app.get("/api/staff")
def staff(role: str | None = None, p: Principal = Depends(principal)):
    return {"items": accounts.staff_directory(p, role)}


# --------------------------------------------------------------------------- corrections
@app.get("/api/corrections")
def corrections(p: Principal = Depends(principal), dataset: str = Depends(ds_param), status: str = "pending"):
    return {"items": recordsvc.list_corrections(p, dataset, status)}


@app.post("/api/students/{dataset}/{sid}/corrections/{cid}")
async def decide_correction(dataset: str, sid: str, cid: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return recordsvc.decide_correction(p, dataset, sid, cid, bool(b.get("approve")), (b.get("reason") or "")[:500])


# --------------------------------------------------------------------------- imports
@app.get("/api/templates")
def templates(p: Principal = Depends(principal)):
    return {"categories": describe() + [{"category": imports.MASTER, "label": "Student master records",
                                         "fields": [{"name": f} for f in imports.MASTER_FIELDS]}]}


@app.get("/api/templates/{category}.csv", response_class=PlainTextResponse)
def template(category: str, p: Principal = Depends(principal)):
    if category != imports.MASTER and category not in CATEGORIES:
        return err(404, "not_found", "Unknown template")
    return PlainTextResponse(imports.template(category), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{category}_template.csv"'})


@app.get("/api/imports")
def list_imports(p: Principal = Depends(principal)):
    return {"items": imports.listing(p)}


@app.post("/api/imports/preview")
async def preview(request: Request, category: str, filename: str = "upload.csv", p: Principal = Depends(principal),
                  dataset: str = Depends(ds_param)):
    raw = await request.body()
    if len(raw) > 2 * 1024 * 1024:
        raise ValidationError({"file": "files must be under 2 MB; split larger files"})
    return imports.preview(p, category, dataset, filename, raw)


@app.post("/api/imports/{iid}/commit")
def commit(iid: str, p: Principal = Depends(principal)):
    return imports.commit(p, iid)


@app.get("/api/imports/{iid}")
def get_import(iid: str, p: Principal = Depends(principal)):
    return imports.get(p, iid)


# --------------------------------------------------------------------------- configuration, policy, audit
@app.get("/api/role-matrix")
def get_role_matrix(p: Principal = Depends(principal)):
    if not grants(p, "role_matrix", "read"):
        raise Denied()
    return role_matrix()


@app.get("/api/config/scoring")
def get_scoring(p: Principal = Depends(principal)):
    if not grants(p, "scoring_config", "read") and not grants(p, "student_insight", "read"):
        raise Denied()
    return {"active": insights.active_config(), "versions": insights.config_versions() if grants(p, "scoring_config", "read") else []}


@app.post("/api/config/scoring/propose")
async def propose(request: Request, p: Principal = Depends(principal)):
    require(p, "scoring_config", "propose")
    b = await request.json()
    reason = (b.get("reason") or "").strip()
    if len(reason) < 5:
        raise ValidationError({"reason": "explain the change (at least 5 characters)"})
    return insights.propose_config(p, b.get("config") or {}, reason)


@app.post("/api/config/scoring/activate")
async def activate(request: Request, p: Principal = Depends(principal)):
    require(p, "scoring_config", "activate")
    b = await request.json()
    reason = (b.get("reason") or "").strip()
    if len(reason) < 5:
        raise ValidationError({"reason": "explain the approval (at least 5 characters)"})
    sysc = db.table().get("CONFIG#SYSTEM", "CURRENT") or {}
    out = insights.activate_config(p, b.get("version"), reason, bool(sysc.get("require_second_approver")))
    for ds in recordsvc.DATASETS:
        insights.repair(ds, budget_seconds=0, everyone=True)  # mark everyone stale; recompute runs via /api/admin/recompute
    return out


@app.post("/api/admin/recompute")
async def recompute(request: Request, p: Principal = Depends(principal)):
    require(p, "insight", "recompute")
    b = await request.json()
    ds = b.get("dataset", "real")
    if ds not in recordsvc.DATASETS:
        raise ValidationError({"dataset": "must be real"})
    out = insights.repair(ds, budget_seconds=12.0, everyone=bool(b.get("all")))
    audit.log(p, "insight.recomputed", "dataset", ds, out, dataset=ds)
    return out


@app.get("/api/audit")
def get_audit(category: str = "academic", limit: int = Query(50, le=200), cursor: str | None = None,
              p: Principal = Depends(principal)):
    if category not in ("academic", "technical"):
        raise ValidationError({"category": "must be academic or technical"})
    require(p, f"audit.{category}", "read")
    items, nxt = audit.list_entries(category, limit, cursor)
    return {"items": [{k: v for k, v in i.items() if k not in ("pk", "sk", "gsi2pk", "gsi2sk")} for i in items],
            "next_cursor": nxt}


@app.get("/api/system/config")
def get_system_config(p: Principal = Depends(principal)):
    require(p, "system_config", "read")
    return db.table().get("CONFIG#SYSTEM", "CURRENT") or {"require_second_approver": False, "version": 0}


@app.put("/api/system/config")
async def put_system_config(request: Request, p: Principal = Depends(principal)):
    require(p, "system_config", "update")
    b = await request.json()
    cur = db.table().get("CONFIG#SYSTEM", "CURRENT")
    from .store import C, ConditionFailed
    item = {"pk": "CONFIG#SYSTEM", "sk": "CURRENT", "require_second_approver": bool(b.get("require_second_approver")),
            "version": (cur["version"] + 1) if cur else 1, "updated_by": p.sub, "updated_at": db.now()}
    try:
        db.table().put(item, C.version(b.get("version")) if cur else C.not_exists())
    except ConditionFailed:
        raise recordsvc.Conflict("Settings changed since you loaded them.") from None
    audit.log(p, "system.config_updated", "system_config", "CURRENT", {"require_second_approver": item["require_second_approver"]})
    return item


# --------------------------------------------------------------------------- accounts (system administrator)
@app.get("/api/users")
def users(p: Principal = Depends(principal)):
    return {"items": accounts.list_users(p)}


@app.post("/api/users", status_code=201)
async def create_user(request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return accounts.create_user(p, b.get("username"), b.get("display_name", ""), b.get("email", ""))


@app.put("/api/users/{sub}/roles")
async def set_roles(sub: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return accounts.set_roles(p, sub, b.get("assignments") or [], b.get("version"))


@app.post("/api/users/{sub}/mfa-reset")
def mfa_reset(sub: str, p: Principal = Depends(principal)):
    """System Administrator: clear a lost authenticator so the user can set up a new one."""
    require(p, "user_account", "update")
    if sub == p.sub:
        raise Denied("You can't reset your own authenticator.")
    prof = db.table().get(f"USER#{sub}", "PROFILE")
    if not prof:
        raise recordsvc.NotFound("Account not found")
    if settings().auth_mode == "cognito":
        from .auth import reset_mfa
        reset_mfa(prof["username"])
    from .auth import clear_principal_cache
    clear_principal_cache(sub)
    audit.log(p, "mfa.reset", "user", prof["username"])
    return {"ok": True}


@app.put("/api/users/{sub}/status")
async def set_status(sub: str, request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return accounts.set_status(p, sub, b.get("status"), b.get("version"))


@app.get("/api/assignments/{sub}")
def get_assignments(sub: str, p: Principal = Depends(principal)):
    if not grants(p, "mentor_assignment", "read") and sub != p.sub:
        raise Denied()
    return accounts.assignments_for(p, sub)


@app.post("/api/assignments/subjects")
async def subject_assignment(request: Request, p: Principal = Depends(principal)):
    b = await request.json()
    return accounts.assign_subject(p, b.get("mentor_sub"), b.get("department"), int(b.get("year", 0)), b.get("subject"),
                                   bool(b.get("remove")))

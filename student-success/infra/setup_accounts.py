"""Create Cognito accounts and their server-side role assignments (operator only, with AWS credentials).

There is no public registration, and nobody can grant themselves a role in the app, so the first
System Administrator and College Administrator are created here by the AWS account operator.

    python infra/setup_accounts.py --admin it.admin --name "IT Admin" --email it@college.example
    python infra/setup_accounts.py --college-admin principal.office --name "Principal's Office" --email po@college.example
    python infra/setup_accounts.py --demo-personas        # demonstration accounts + synthetic dataset (150 students)

Each new account gets a random temporary password, printed ONCE here (never stored, logged or committed).
Share it securely; Cognito forces a new password at first sign-in. Accounts are not created for the
150 synthetic students; only the two student personas can sign in.
"""

from __future__ import annotations

import sys

from common import app_env, boto, outputs, parser


def ensure_user(accounts, seed, username: str, name: str, email: str) -> tuple[str, str | None]:
    """Create the Cognito user and profile, or reuse them. Returns (sub, temporary password or None)."""
    from app import db
    from app.recordsvc import Conflict
    for u in db.table().query("USERS", index="gsi2", limit=500)[0]:
        if u["username"] == username.lower():
            return u["sub"], None
    try:
        out = accounts.create_user(seed.SYSTEM, username, name, email, system=True)
        return out["sub"], out.get("temporary_password")
    except Conflict:
        raise
    except Exception as e:
        if "UsernameExists" not in str(e):
            raise
        # Cognito user exists from an interrupted run: link it.
        from app.settings import settings
        r = boto("cognito-idp", settings().region).admin_get_user(UserPoolId=settings().cognito_pool_id, Username=username)
        sub = next(a["Value"] for a in r["UserAttributes"] if a["Name"] == "sub")
        accounts.create_user(seed.SYSTEM, username, name, email, sub=sub, system=True)
        return sub, None


def main() -> int:
    p = parser("Create admin-provisioned accounts")
    p.add_argument("--admin", help="username for a System Administrator (no student-data access)")
    p.add_argument("--college-admin", help="username for a College Administrator")
    p.add_argument("--name", default="")
    p.add_argument("--email", default="")
    p.add_argument("--demo-personas", action="store_true", help="create the 9 demonstration accounts and load the demo dataset")
    a = p.parse_args()
    if not (a.admin or a.college_admin or a.demo_personas):
        p.error("choose --admin, --college-admin or --demo-personas")
    out = outputs(boto("cloudformation", a.region), a.stack)
    if not out:
        sys.exit(f"Stack {a.stack} not found in {a.region}. Deploy first.")
    app_env(out, a.region)
    from app import accounts, seed

    passwords = []
    for username, role in ((a.admin, "system_admin"), (a.college_admin, "college_admin")):
        if not username:
            continue
        sub, temp = ensure_user(accounts, seed, username, a.name or username, a.email)
        from app import db
        prof = db.table().get(f"USER#{sub}", "PROFILE")
        if not prof.get("roles"):
            accounts.set_roles(seed.SYSTEM, sub, [{"role": role}], prof["version"], system=True)
        passwords.append((username, role, temp))

    if a.demo_personas:
        subs = {}
        for per in seed.PERSONAS:
            sub, temp = ensure_user(accounts, seed, per["username"], per["display_name"], "")
            subs[per["username"]] = sub
            passwords.append((per["username"], ", ".join(r["role"] for r in per["roles"]), temp))
        print("Loading the synthetic demo dataset (idempotent; at 8 WCU this takes several minutes)…")
        s = seed.run(with_accounts=False)
        print(f"  {s['students']} students, {s['records']} records: {s['written']} written, {s['skipped']} unchanged")
        seed.assign_persona_roles(subs)

    print("\nAccounts (temporary passwords are shown once; share them securely):")
    for username, role, temp in passwords:
        print(f"  {username:18} {role:30} {temp or '(existing account; password unchanged)'}")
    print("\nSign in at", out["SiteUrl"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build locally and deploy with CloudFormation plus direct Lambda ZIP uploads (no S3, no CI service).

    python infra/deploy.py --build-only                      # package only; nothing touches AWS
    python infra/deploy.py --approve --pricing-verified 2026-10-12 [--budget-email you@example.org]

Deployment refuses to run unless:
  * --approve is given (explicit human approval; there is no default),
  * --pricing-verified names the date (within 7 days) a person checked the official pages listed by preflight,
  * preflight.py reports no STOP (zero-spend checks, local-auth bypass checks),
  * the packages contain no local development server and no local demo sign-in configuration.
The first deploy runs twice: once to learn the CloudFront address, then again to register it with Cognito.
"""

from __future__ import annotations

import datetime as dt
import io
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from common import BUILD, INFRA, ROOT, TEMPLATE, boto, outputs, parser, stack

API_INDEX = "from lambda_api import handler  # noqa: F401\n"
WEB_INDEX = "from web_handler import handler  # noqa: F401\n"
MAX_DIRECT_ZIP = 50 * 1024 * 1024  # Lambda direct upload limit


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("  $", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def zip_dir(src: Path, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                info = zipfile.ZipInfo(str(f.relative_to(src)), date_time=(2020, 1, 1, 0, 0, 0))  # reproducible
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, f.read_bytes())
    return dest.stat().st_size


def build(arch: str = "aarch64", frontend: bool = True) -> dict[str, Path]:
    """Return {'api': zip, 'web': zip}. arch=x86_64 builds a copy that can be smoke-tested on a laptop."""
    if frontend:
        print("Building the Angular app")
        run(["npm", "run", "build"], cwd=ROOT / "frontend")
    web_src = ROOT / "frontend" / "dist" / "campus" / "browser"
    if not (web_src / "index.html").exists():
        sys.exit("Frontend build missing: cd frontend && npm ci && npm run build")
    out = BUILD / arch
    shutil.rmtree(out, ignore_errors=True)

    print("Packaging the API")
    api = out / "api"
    run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(ROOT / "backend" / "requirements.txt"),
         "--target", str(api), "--platform", f"manylinux2014_{arch}", "--implementation", "cp", "--python-version", "3.12",
         "--only-binary=:all:", "--no-compile"])
    shutil.copytree(ROOT / "backend" / "app", api / "app", ignore=shutil.ignore_patterns("__pycache__", "tools"))
    shutil.copy(ROOT / "backend" / "lambda_api.py", api / "lambda_api.py")
    (api / "config").mkdir()
    for f in ("role-matrix.json", "scoring.json", "curriculum.json"):
        shutil.copy(ROOT / "config" / f, api / "config" / f)
    (api / "index.py").write_text(API_INDEX)

    print("Packaging the web app")
    web = out / "web"
    shutil.copytree(web_src, web / "web")
    shutil.copy(ROOT / "backend" / "web_handler.py", web / "web_handler.py")
    (web / "index.py").write_text(WEB_INDEX)

    check_package(api, web)
    zips = {"api": out / "api.zip", "web": out / "web.zip"}
    for k, d in (("api", api), ("web", web)):
        size = zip_dir(d, zips[k])
        print(f"  {zips[k].relative_to(ROOT)}: {size / 1024 / 1024:.1f} MB")
        if size > MAX_DIRECT_ZIP:
            sys.exit(f"{k} package is over the 50 MB direct-upload limit")
    return zips


def check_package(api: Path, web: Path) -> None:
    """Fail if a local authentication bypass could reach AWS."""
    bad = []
    if (api / "local_server.py").exists():
        bad.append("local_server.py is packaged")
    for f in list(api.rglob("*.py")) + list(web.rglob("*.py")):
        if "site-packages" in f.parts or f.parts[len(api.parts)] not in ("app", "lambda_api.py", "index.py", "web_handler.py"):
            continue
        t = f.read_text(errors="ignore")
        if "os.environ.setdefault(\"AUTH_MODE\"" in t or "LOCAL_DEMO_SECRET=" in t:
            bad.append(f"{f.name} sets a local authentication default")
    cfg = (web / "web").rglob("config.json")
    if any(cfg):
        bad.append("a static config.json is packaged (it must come from APP_CONFIG)")
    settings = (api / "app" / "settings.py").read_text()
    if "in_lambda" not in settings or "cognito" not in settings:
        bad.append("settings.py no longer refuses non-Cognito mode in Lambda")
    if bad:
        sys.exit("Refusing to deploy: " + "; ".join(bad))
    print("  package checks passed (no local sign-in bypass)")


def params(cfn, name: str, site_url: str, budget_email: str | None) -> list[dict]:
    p = [{"ParameterKey": "AppName", "ParameterValue": name}, {"ParameterKey": "SiteUrl", "ParameterValue": site_url}]
    s = stack(cfn, name)
    existing = {x["ParameterKey"] for x in (s or {}).get("Parameters", [])}
    if budget_email is not None:
        p.append({"ParameterKey": "BudgetEmail", "ParameterValue": budget_email})
    elif "BudgetEmail" in existing:
        p.append({"ParameterKey": "BudgetEmail", "UsePreviousValue": True})
    for k in ("ApiReservedConcurrency", "WebReservedConcurrency", "UserPoolTier"):
        if k in existing:
            p.append({"ParameterKey": k, "UsePreviousValue": True})
    return p


def apply_stack(cfn, name: str, parameters: list[dict], extra: list[dict]) -> None:
    by_key = {x["ParameterKey"]: x for x in parameters}
    for x in extra:
        by_key[x["ParameterKey"]] = x
    exists = stack(cfn, name) is not None
    cs = f"deploy-{int(time.time())}"
    cfn.create_change_set(StackName=name, ChangeSetName=cs, ChangeSetType="UPDATE" if exists else "CREATE",
                          TemplateBody=TEMPLATE.read_text(), Parameters=list(by_key.values()),
                          Capabilities=["CAPABILITY_IAM"], Tags=[{"Key": "app", "Value": name}])
    try:
        cfn.get_waiter("change_set_create_complete").wait(StackName=name, ChangeSetName=cs, WaiterConfig={"Delay": 5})
    except Exception:
        d = cfn.describe_change_set(StackName=name, ChangeSetName=cs)
        if "didn't contain changes" in d.get("StatusReason", "") or "No updates" in d.get("StatusReason", ""):
            print("  no infrastructure changes")
            cfn.delete_change_set(StackName=name, ChangeSetName=cs)
            return
        raise SystemExit(f"Change set failed: {d.get('StatusReason')}")
    for c in cfn.describe_change_set(StackName=name, ChangeSetName=cs)["Changes"]:
        r = c["ResourceChange"]
        print(f"  {r['Action']:7} {r['ResourceType']:40} {r['LogicalResourceId']}"
              + (f"  (replacement: {r.get('Replacement')})" if r.get("Replacement") not in (None, "False") else ""))
    cfn.execute_change_set(StackName=name, ChangeSetName=cs)
    waiter = "stack_update_complete" if exists else "stack_create_complete"
    print("  waiting for CloudFormation (a new CloudFront distribution can take several minutes)…")
    cfn.get_waiter(waiter).wait(StackName=name, WaiterConfig={"Delay": 15, "MaxAttempts": 240})


def upload(lam, fn: str, zip_path: Path) -> None:
    prev = BUILD / "previous" / f"{fn}.zip"
    try:
        loc = lam.get_function(FunctionName=fn)["Code"].get("Location")
        if loc:
            import urllib.request
            data = urllib.request.urlopen(loc, timeout=60).read()
            if len(data) > 2048:  # skip the inline placeholder
                prev.parent.mkdir(parents=True, exist_ok=True)
                prev.write_bytes(data)
    except Exception as e:
        print(f"  (could not keep a rollback copy of {fn}: {type(e).__name__})")
    lam.update_function_code(FunctionName=fn, ZipFile=zip_path.read_bytes(), Publish=False)
    lam.get_waiter("function_updated_v2").wait(FunctionName=fn)
    print(f"  uploaded {fn}")


def main() -> int:
    p = parser("Build and deploy (requires explicit approval)")
    p.add_argument("--approve", action="store_true", help="explicit approval to create or change AWS resources")
    p.add_argument("--pricing-verified", help="YYYY-MM-DD you checked the official pricing pages listed by preflight")
    p.add_argument("--budget-email", help="optional: email for a USD 1 monthly cost alert")
    p.add_argument("--build-only", action="store_true", help="package only; no AWS calls")
    p.add_argument("--arch", default="aarch64", choices=["aarch64", "x86_64"], help="x86_64 only for local package tests")
    p.add_argument("--skip-frontend-build", action="store_true")
    a = p.parse_args()

    if a.build_only:
        build(a.arch, frontend=not a.skip_frontend_build)
        return 0
    if not a.approve:
        sys.exit("Not deploying: pass --approve after reviewing docs/aws-cost-and-preflight.md and the preflight output.")
    try:
        checked = dt.date.fromisoformat(a.pricing_verified or "")
    except ValueError:
        sys.exit("Not deploying: pass --pricing-verified YYYY-MM-DD (the date you checked the official AWS pricing pages).")
    if (dt.date.today() - checked).days > 7 or checked > dt.date.today():
        sys.exit("Not deploying: pricing must have been verified within the last 7 days.")
    if a.arch != "aarch64":
        sys.exit("Deploy packages must target arm64 (aarch64).")

    print("Running preflight")
    if subprocess.run([sys.executable, str(INFRA / "preflight.py"), "--region", a.region, "--stack", a.stack]).returncode:
        sys.exit("Preflight reported STOP. Nothing was deployed.")
    zips = build(frontend=not a.skip_frontend_build)

    cfn, lam = boto("cloudformation", a.region), boto("lambda", a.region)
    site = outputs(cfn, a.stack).get("SiteUrl", "")
    print(f"Deploying stack {a.stack} to {a.region}")
    apply_stack(cfn, a.stack, params(cfn, a.stack, site, a.budget_email), [])
    out = outputs(cfn, a.stack)
    if out["SiteUrl"] != site:
        print("Registering the CloudFront address with Cognito (second pass)")
        apply_stack(cfn, a.stack, params(cfn, a.stack, out["SiteUrl"], a.budget_email), [])
        out = outputs(cfn, a.stack)
    upload(lam, out["ApiFunctionName"], zips["api"])
    upload(lam, out["WebFunctionName"], zips["web"])

    print(f"""
Deployed. Site: {out['SiteUrl']}

Next steps (see docs/deployment.md):
  1. Accounts:   python infra/setup_accounts.py --region {a.region} --stack {a.stack} --admin <username> --email <you>
                 (add --demo-personas to create the demonstration accounts and load the synthetic dataset)
  2. Smoke test: python infra/smoke_test.py --region {a.region} --stack {a.stack} --token <ID token>
  3. Optional:   in the CloudFront console, subscribe distribution {out['DistributionId']} to the Free flat-rate plan
                 if your account is eligible. Without it, pay-as-you-go always-free allowances apply.
  4. Watch the Billing console and Free Tier usage for the first days.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())

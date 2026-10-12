"""Roll back application code to the previous upload.

    python infra/rollback.py --approve

deploy.py keeps the code each upload replaced in infra/.build/previous/. This re-uploads it.
Infrastructure: a failed stack update is rolled back by CloudFormation automatically; to undo a
successful but unwanted change, check out the previous infra/template.yaml from git and run deploy.py.
Data is not rolled back (no paid backups are enabled; see docs/deployment.md, "Backups").
"""

from __future__ import annotations

import sys

from common import BUILD, boto, outputs, parser


def main() -> int:
    p = parser("Restore the previous Lambda code")
    p.add_argument("--approve", action="store_true")
    a = p.parse_args()
    if not a.approve:
        sys.exit("Pass --approve to change the deployed code.")
    out = outputs(boto("cloudformation", a.region), a.stack)
    lam = boto("lambda", a.region)
    done = 0
    for fn in (out["ApiFunctionName"], out["WebFunctionName"]):
        prev = BUILD / "previous" / f"{fn}.zip"
        if not prev.exists():
            print(f"  no previous code kept for {fn}; skipping")
            continue
        lam.update_function_code(FunctionName=fn, ZipFile=prev.read_bytes(), Publish=False)
        lam.get_waiter("function_updated_v2").wait(FunctionName=fn)
        print(f"  restored {fn}")
        done += 1
    print("Rolled back." if done else "Nothing to roll back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Generate docs/role-matrix.md from config/role-matrix.json.

    python -m app.tools.render_role_matrix          # write the file
    python -m app.tools.render_role_matrix --check  # fail if the file is out of date (used in tests/CI)
"""

from __future__ import annotations

import sys
from collections import defaultdict

from ..settings import ROOT, role_matrix

OUT = ROOT / "docs" / "role-matrix.md"


def render() -> str:
    m = role_matrix()
    lines = [
        "# Role matrix",
        "",
        "<!-- GENERATED from config/role-matrix.json by `python -m app.tools.render_role_matrix`. Do not edit by hand. -->",
        "",
        f"Policy version **{m['version']}**. {m['description']}",
        "",
        "## Scopes",
        "",
        "| Scope | Meaning |",
        "|---|---|",
    ]
    lines += [f"| `{k}` | {v} |" for k, v in m["scopes"].items()]
    lines += ["", "## Field sets", "", "| Field set | Fields |", "|---|---|"]
    lines += [f"| `{k}` | {', '.join(f'`{x}`' for x in v)} |" for k, v in m["field_sets"].items()]
    for key, role in m["roles"].items():
        lines += ["", f"## {role['label']} (`{key}`)", "", role["summary"], "", "| Resource | Action | Scope | Fields |",
                  "|---|---|---|---|"]
        grouped = defaultdict(list)
        for p in role["permissions"]:
            grouped[(p["resource"], p["scope"], p["fields"] if isinstance(p["fields"], str) else ", ".join(p["fields"]))].append(p["action"])
        for (res, scope, fields), actions in grouped.items():
            lines.append(f"| `{res}` | {', '.join(actions)} | `{scope}` | `{fields}` |")
        if role.get("constraints"):
            lines += ["", "Constraints: " + "; ".join(f"`{k}` = {', '.join(v)}" for k, v in role["constraints"].items())]
    lines += ["", "## Separation of duties", ""] + [f"- {r}" for r in m["separation_of_duties"]["rules"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            raise SystemExit("docs/role-matrix.md is out of date. Run: python -m app.tools.render_role_matrix")
        print("docs/role-matrix.md is up to date")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

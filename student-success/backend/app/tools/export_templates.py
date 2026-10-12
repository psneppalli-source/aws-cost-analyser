"""Write the CSV import templates to docs/csv-templates/ (same content as GET /api/templates/{category}.csv).

    python -m app.tools.export_templates [--check]
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.categories import CATEGORIES
from app.imports import MASTER, template

OUT = Path(__file__).resolve().parents[3] / "docs" / "csv-templates"


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for cat in [MASTER, *CATEGORIES]:
        f = OUT / f"{cat}.csv"
        text = template(cat)
        if check:
            if not f.exists() or f.read_text() != text:
                stale.append(f.name)
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
    if stale:
        print("Out of date:", ", ".join(stale), "- run python -m app.tools.export_templates")
        return 1
    print("CSV templates", "are up to date" if check else f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run the upstream Agent Skills validator over many skill directories in one process.

`skills-ref validate` takes a single path, and each `uvx` start re-checks the git
remote, so one call per skill costs about a second of waiting each. Importing the
package once and looping keeps the cost at one lookup however many skills there are.

Usage: skills-ref-all.py DIR [DIR ...]      (run it through uvx, see validate.sh)
"""
import sys
from pathlib import Path

from skills_ref import validate

# The Windows console defaults to cp1252, which cannot print the check mark below.
sys.stdout.reconfigure(encoding="utf-8")

failed = 0
for arg in sys.argv[1:]:
    path = Path(arg)
    errors = validate(path)
    if errors:
        failed += 1
        print(f"  ✘ {path.name}")
        for e in errors:
            print(f"    {e}")
    else:
        print(f"  ✔ {path.name}")

sys.exit(1 if failed else 0)

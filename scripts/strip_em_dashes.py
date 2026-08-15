"""Replace em dashes and en dashes with ASCII punctuation across the project.

Two rules, applied with literal character operations rather than a regex:

    between digits   "5104<en>5203"   ->  "5104-5203"   (numeric range)
    everywhere else  "a <em> b"       ->  "a, b"        (clause break)

Design notes, both of which come from bugs this script has already caused once:

1.  The general replacement is a comma, never " - ". Emitting a hyphen made the transformation
    non-idempotent: a second run re-matched the script's own output and expanded every ASCII
    hyphen in the repository. The current version removes the two dash characters and emits a
    hyphen only between digits, so repeat runs are inert.

2.  No cleanup rule may delete a comma that was already in the file. An earlier version mapped
    ",\\n" to "\\n" to tidy a dash at end of line, which silently stripped the trailing commas
    from every multi-line Python and TypeScript literal and broke the build. Cleanup is limited
    to whitespace around a comma this script itself inserted.

The script excludes itself from the scan, because it necessarily contains the dash characters
it is looking for.

Usage:
    python scripts/strip_em_dashes.py            # dry run
    python scripts/strip_em_dashes.py --apply    # write
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EM = "—"  # em dash, written as an escape so this file contains no literal dash
EN = "–"  # en dash

SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "dist", "build", "v1_data", "data", ".ipynb_checkpoints",
}
SKIP_PATH_PARTS = [("models", "artifacts")]  # trained binaries, not source
SKIP_FILES = {"strip_em_dashes.py"}
TEXT_SUFFIXES = {".py", ".md", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".yaml", ".yml",
                 ".toml", ".txt", ".sql", ".sh"}


def substitute(text: str) -> str:
    """Return text with em/en dashes replaced. Idempotent: emits no dash except between digits."""
    if EM not in text and EN not in text:
        return text

    out: list[str] = []
    for i, ch in enumerate(text):
        if ch not in (EM, EN):
            out.append(ch)
            continue

        left = text[:i].rstrip()
        right = text[i + 1:].lstrip()

        if left and right and left[-1].isdigit() and right[0].isdigit():
            while out and out[-1] == " ":
                out.pop()
            out.append("-")
            # Swallow spaces that followed the dash so "5104 - 5203" becomes "5104-5203".
            continue

        # Clause break. Drop spaces before the comma; the space after is already in the text.
        while out and out[-1] == " ":
            out.pop()
        # A dash at end of line becomes nothing rather than a dangling comma.
        if right.startswith("\n") or not right:
            continue
        out.append(",")

    result = "".join(out)
    # Only whitespace tidying, and only patterns this function can itself produce.
    while ",  " in result:
        result = result.replace(",  ", ", ")
    while " ," in result:
        result = result.replace(" ,", ",")
    return result


def _has_dash(text: str) -> bool:
    return EM in text or EN in text


def process_notebook(path: Path, apply: bool) -> int:
    raw = path.read_text(encoding="utf-8")
    if not _has_dash(raw):
        return 0
    nb = json.loads(raw)
    count = 0
    for cell in nb.get("cells", []):
        source = cell.get("source")
        if isinstance(source, list):
            new = [substitute(line) for line in source]
            count += sum(1 for a, b in zip(source, new) if a != b)
            cell["source"] = new
        elif isinstance(source, str):
            new_s = substitute(source)
            count += new_s != source
            cell["source"] = new_s
    if apply and count:
        path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return count


def process_text(path: Path, apply: bool) -> int:
    raw = path.read_text(encoding="utf-8")
    if not _has_dash(raw):
        return 0
    new = substitute(raw)
    count = raw.count(EM) + raw.count(EN)
    if apply and new != raw:
        path.write_text(new, encoding="utf-8")
    return count


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    args = [a for a in argv if not a.startswith("--")]
    root = Path(args[0] if args else ".")

    files = marks = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(all(seg in path.parts for seg in combo) for combo in SKIP_PATH_PARTS):
            continue
        try:
            if path.suffix == ".ipynb":
                n = process_notebook(path, apply)
            elif path.suffix in TEXT_SUFFIXES:
                n = process_text(path, apply)
            else:
                continue
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"  skipped {path}: {exc}")
            continue
        if n:
            files += 1
            marks += n
            print(f"  {path.relative_to(root)}: {n}")

    print(f"\n{files} files {'changed' if apply else 'would change'}, {marks} dashes")
    if not apply:
        print("dry run. re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

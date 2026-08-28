#!/usr/bin/env python3
"""Export the retired mnemopi memory banks to a readable markdown archive.

Why this exists (ADR-0012, "Memory"): mnemopi was omp's native memory backend and
exists only as the fork's ``@oh-my-pi/pi-mnemopi``. Nothing upstream can read its
store, and no pi memory extension ships an importer — so the banks are the only
part of the omp retirement that cannot be re-derived from a config file. This turns
them into markdown under ``~/.agents/memory-archive/`` so they survive as something
a human can read and any agent can grep.

Deliberately NOT auto-loaded as context: 430 rows of accumulated project notes in
every session's prompt would cost more than it returns. Read it on purpose.

Run this BEFORE deleting ``<stateRoot>/.omp``. Dropping the ``.omp`` env link only
removes the ``$HOME`` symlink and leaves the data, so there is no rush — but the
export has to precede the cleanup, not follow it.

Usage:
    python3 scripts/export-mnemopi-banks.py [--banks-dir DIR] [--out DIR] [--dry-run]

Defaults to the reference host's layout and is safe to re-run: each bank is written
whole, so a second run just refreshes the file.
"""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

DEFAULT_BANKS = pathlib.Path.home() / ".omp" / "agent" / "memories" / "mnemopi" / "banks"
DEFAULT_OUT = pathlib.Path.home() / ".agents" / "memory-archive"

# The tables worth keeping, in the order they are written, with the columns that
# carry meaning. Measured on 2026-08-28 across 13 banks / 430 rows:
#
#   - `memoria_facts` and `facts` hold IDENTICAL counts in every bank — two
#     representations of the same extraction — so only one is exported or every
#     archive doubles. `memoria_facts` wins: it carries fact_type and a context
#     snippet where `facts` has only a bare triple.
#   - `working_memory` is largely raw transcript, including some rows that still
#     carry `--- pi-extension-context:start ---` markers. Kept, but last and
#     clearly labelled, so the extracted knowledge reads first.
#   - the five empty banks (dotfiles, shared, lz-playground, viztrace-runner, tmp)
#     produce no file at all rather than an empty one.
SECTIONS = (
    ("Facts", "memoria_facts",
     "SELECT fact_type, key, value, context_snippet FROM memoria_facts "
     "ORDER BY importance DESC, id"),
    ("Instructions", "memoria_instructions",
     "SELECT instruction, topic, context_snippet FROM memoria_instructions "
     "WHERE active != 0 ORDER BY id"),
    ("Preferences", "memoria_preferences",
     "SELECT preference, topic, evolution FROM memoria_preferences ORDER BY id"),
    ("Knowledge graph", "memoria_kg",
     "SELECT subject, predicate, object, confidence FROM memoria_kg "
     "ORDER BY confidence DESC, id"),
    ("Timeline", "memoria_timelines",
     "SELECT date, description, source FROM memoria_timelines ORDER BY date, event_id"),
    ("Triples", "triples",
     "SELECT subject, predicate, object FROM triples ORDER BY id"),
    ("Gists", "gists", "SELECT text, timestamp FROM gists ORDER BY id"),
    # Last on purpose — see the note above.
    ("Raw working memory (mostly transcript)", "working_memory",
     "SELECT content, importance, timestamp FROM working_memory "
     "ORDER BY importance DESC, id"),
)


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}


def _cell(value: object) -> str:
    """One field, flattened onto a single markdown line."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").strip()
    # Collapse to one line: these land in bullets, and a stray newline would
    # silently end the list item.
    return " ".join(text.split())


def export_bank(db: pathlib.Path, out: pathlib.Path, dry_run: bool) -> int:
    """Write one bank's markdown. Returns the number of rows exported."""
    # Read-only URI so an export can never be what corrupts the thing it is
    # preserving, even if omp is somehow still running.
    conn = sqlite3.connect("file:{}?mode=ro".format(db), uri=True)
    try:
        present = _existing_tables(conn)
        blocks: list[str] = []
        total = 0
        for title, table, query in SECTIONS:
            if table not in present:
                continue
            rows = list(conn.execute(query))
            if not rows:
                continue
            total += len(rows)
            blocks.append("## {} ({})\n".format(title, len(rows)))
            # Suppress any column whose value never varies in this section: it
            # carries no information but costs a phrase on every line. In the
            # measured data `memoria_facts.fact_type` is always "entity" and its
            # `key` always "fact", so without this every fact reads
            # "**entity** — fact · <the actual fact>".
            constant = {
                i for i in range(len(rows[0]))
                if len(rows) > 1 and len({_cell(r[i]) for r in rows}) == 1
            }
            rows = [tuple(v for i, v in enumerate(r) if i not in constant) for r in rows]
            for row in rows:
                # Drop empties AND repeats. mnemopi stores the same string in
                # several columns — `value` and `context_snippet` are identical in
                # every row measured, as are `instruction` and its snippet — so
                # joining naively prints each fact two or three times. Comparison
                # is case-folded because a few rows differ only in capitalisation.
                fields: list[str] = []
                seen: set[str] = set()
                for value in row:
                    text = _cell(value)
                    if not text or text.casefold() in seen:
                        continue
                    seen.add(text.casefold())
                    fields.append(text)
                if not fields:
                    continue
                head, *rest = fields
                if rest:
                    blocks.append("- **{}** — {}".format(head, " · ".join(rest)))
                else:
                    blocks.append("- {}".format(head))
            blocks.append("")
    finally:
        conn.close()

    if not total:
        return 0

    # The bank dir name is `<project>-<hash>`; keep the whole thing. The hash is
    # how omp scoped per project and dropping it could collide two worktrees of the
    # same repo, which is exactly the kind of silent merge an archive must not do.
    name = db.parent.name
    header = [
        "# Memory archive — {}".format(name),
        "",
        "Exported from omp's mnemopi store by `scripts/export-mnemopi-banks.py`",
        "(ADR-0012). mnemopi is omp-only and nothing upstream can read its store,",
        "so this markdown is the surviving form.",
        "",
        "Source: `{}`".format(db),
        "",
        "**Not auto-loaded as context** — read or grep it on purpose.",
        "",
    ]
    text = "\n".join(header + blocks).rstrip() + "\n"
    target = out / "{}.md".format(name)
    if dry_run:
        print("[DRY-RUN] {} rows -> {}".format(total, target))
        return total
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    print("{:5d} rows -> {}".format(total, target))
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--banks-dir", type=pathlib.Path, default=DEFAULT_BANKS,
                    help="mnemopi banks dir (default: %(default)s)")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT,
                    help="archive dir (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be written, write nothing")
    args = ap.parse_args()

    if not args.banks_dir.is_dir():
        print("no banks dir at {} — nothing to export".format(args.banks_dir),
              file=sys.stderr)
        return 1

    dbs = sorted(args.banks_dir.glob("*/mnemopi.db"))
    if not dbs:
        print("no mnemopi.db under {}".format(args.banks_dir), file=sys.stderr)
        return 1

    exported = skipped = rows = 0
    for db in dbs:
        n = export_bank(db, args.out, args.dry_run)
        if n:
            exported += 1
            rows += n
        else:
            skipped += 1
            print("      empty, skipped: {}".format(db.parent.name))
    print("\n{} bank(s), {} rows -> {}{}".format(
        exported, rows, args.out, " (dry run)" if args.dry_run else ""))
    if skipped:
        print("{} empty bank(s) produced no file".format(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())

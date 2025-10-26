#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="Strip class tokens matching a regex from HTML files under a root directory")
    ap.add_argument("--root", required=True, help="Root directory containing HTML files")
    ap.add_argument("--pattern", required=True, help=r"Regex for a single class token to remove (e.g., ^about__block(?:_\\d+)?$)")
    ap.add_argument("--dry-run", action="store_true", help="Only report, do not modify files")
    ap.add_argument("--backup", action="store_true", help="Write .bak once per file before first change")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Root not found: {root}")

    token_re = re.compile(args.pattern)
    class_attr_re = re.compile(r'(class=\")([^\"]+)(\")')

    total_changed = 0
    files_changed = 0

    for html_path in root.rglob("*.html"):
        try:
            src = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        changed_this = 0

        def repl(m: re.Match) -> str:
            nonlocal changed_this
            before, classes, after = m.group(1), m.group(2), m.group(3)
            toks = [c for c in classes.split() if c]
            kept = [c for c in toks if not token_re.fullmatch(c)]
            if kept == toks:
                return m.group(0)
            changed_this += 1
            return before + (" ".join(kept)) + after

        out = class_attr_re.sub(repl, src)
        if changed_this > 0 and not args.dry_run:
            if args.backup:
                bak = html_path.with_suffix(html_path.suffix + ".bak")
                if not bak.exists():
                    try:
                        bak.write_text(src, encoding="utf-8")
                    except Exception:
                        pass
            try:
                html_path.write_text(out, encoding="utf-8")
            except Exception:
                continue
            files_changed += 1
            total_changed += changed_this

    print(f"[STRIP-CLASS] files_changed={files_changed}, class_attrs_modified={total_changed}")


if __name__ == "__main__":
    main()

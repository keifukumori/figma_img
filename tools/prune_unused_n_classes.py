#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def collect_defined_n_classes(css_text: str) -> set[str]:
    s: set[str] = set()
    # match .n-xxxxx in simple selectors; be permissive
    for m in re.finditer(r"\.n-([a-zA-Z0-9_-]+)", css_text):
        s.add("n-" + m.group(1))
    return s


def main():
    ap = argparse.ArgumentParser(description="Remove n-* class tokens from HTML if they have no CSS rule in the project root")
    ap.add_argument("--root", required=True, help="Root directory containing index.html/style.css")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backup", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit("root not found")

    # Collect CSS-defined n- classes from all CSS files under root (non-recursive + immediate children)
    css_text = ""
    for p in list(root.glob("*.css")) + list(root.glob("*/*.css")):
        try:
            css_text += p.read_text(encoding="utf-8", errors="ignore") + "\n"
        except Exception:
            pass
    defined = collect_defined_n_classes(css_text)

    class_attr_re = re.compile(r'(class=\")([^\"]+)(\")')
    removed_total = 0
    files_changed = 0

    for html in root.rglob("*.html"):
        try:
            src = html.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        removed_here = 0

        def repl(m: re.Match) -> str:
            nonlocal removed_here
            before, classes, after = m.group(1), m.group(2), m.group(3)
            toks = [c for c in classes.split() if c]
            kept = []
            for c in toks:
                if c.startswith('n-') and c not in defined:
                    removed_here += 1
                    continue
                kept.append(c)
            if removed_here == 0:
                return m.group(0)
            return before + (" ".join(kept)) + after

        out = class_attr_re.sub(repl, src)
        if removed_here > 0 and not args.dry_run:
            if args.backup:
                bak = html.with_suffix(html.suffix + ".prune_n.bak")
                if not bak.exists():
                    try:
                        bak.write_text(src, encoding="utf-8")
                    except Exception:
                        pass
            try:
                html.write_text(out, encoding="utf-8")
            except Exception:
                continue
            removed_total += removed_here
            files_changed += 1

    print(f"[PRUNE-N] files_changed={files_changed}, n_tokens_removed={removed_total}")


if __name__ == "__main__":
    main()


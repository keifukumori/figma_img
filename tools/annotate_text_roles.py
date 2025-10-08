#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


T_SIZE_RE = re.compile(r"\bt-(\d+)\b")
TX_W_RE = re.compile(r"\btx-w(\d+)\b")


def role_from_tokens(tag: str, classes: list[str]) -> str | None:
    tag = tag.lower()
    if tag in ("h1", "h2", "h3", "h4"):
        return "role-h"
    size = None
    w = None
    for c in classes:
        m = T_SIZE_RE.search(c)
        if m:
            try:
                size = int(m.group(1))
            except Exception:
                pass
        m2 = TX_W_RE.search(c)
        if m2:
            try:
                w = int(m2.group(1))
            except Exception:
                pass
    if size is None and w is None:
        return None
    if (size is not None and size >= 20) or (w is not None and w >= 600):
        return "role-h"
    if (size is not None and size <= 12) and (w is None or w <= 500):
        return "role-note"
    return "role-body"


def annotate_roles(html: str) -> tuple[str, int]:
    changed = 0
    # regex to find opening tags with a class attribute: capture tag name and class content
    pat = re.compile(r"<(h1|h2|h3|h4|h5|h6|p)\b([^>]*)class=\"([^\"]+)\"([^>]*)>", re.I)
    def repl(m: re.Match) -> str:
        nonlocal changed
        tag = m.group(1)
        before = m.group(2)
        cls = m.group(3)
        after = m.group(4)
        classes = [c for c in cls.split() if c]
        if any(c.startswith('role-') for c in classes):
            return m.group(0)
        role = role_from_tokens(tag, classes)
        if not role:
            return m.group(0)
        classes.append(role)
        changed += 1
        return f"<{tag}{before}class=\"{' '.join(classes)}\"{after}>"
    new_html = pat.sub(repl, html)
    return new_html, changed


def main():
    ap = argparse.ArgumentParser(description='Annotate text elements with role classes based on typography tokens (role-h/role-body/role-note)')
    ap.add_argument('--root', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    html_path = Path(args.root) / 'index.html'
    if not html_path.exists():
        raise SystemExit('index.html not found')
    html = html_path.read_text(encoding='utf-8', errors='ignore')
    new_html, changed = annotate_roles(html)
    if args.dry_run:
        print(f"[TEXT-ROLES] would annotate={changed}")
        return
    if changed:
        bak = html_path.with_suffix(html_path.suffix + '.text_roles.bak')
        if not bak.exists():
            bak.write_text(html, encoding='utf-8')
        html_path.write_text(new_html, encoding='utf-8')
    print(f"[TEXT-ROLES] annotated={changed}")


if __name__ == '__main__':
    main()


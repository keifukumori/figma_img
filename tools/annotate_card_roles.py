#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


TAG_RE = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>')
CLASS_RE = re.compile(r'class="([^"]*)"')


def has_card_class(class_str: str) -> bool:
    arr = class_str.split()
    for c in arr:
        if c == 'card' or c.endswith('__card') or c == 'card-surface':
            return True
    return False


def add_card_role(class_str: str, tag: str) -> str:
    arr = [c for c in class_str.split() if c]
    s = set(arr)
    # map role-* to card__*
    if 'role-h' in s and 'card__title' not in s:
        arr.append('card__title')
    elif 'role-note' in s and 'card__meta' not in s:
        arr.append('card__meta')
    elif 'role-body' in s and 'card__body' not in s:
        arr.append('card__body')
    else:
        # heuristic fallback by tag
        tl = tag.lower()
        if tl in ('h1','h2','h3','h4') and 'card__title' not in s:
            arr.append('card__title')
        elif tl in ('p','li','span') and 'card__body' not in s:
            arr.append('card__body')
    return ' '.join(arr)


def annotate_card_roles(html: str) -> tuple[str, int]:
    edits: list[tuple[int, int, str]] = []
    stack: list[bool] = []  # card-context stack
    changed = 0
    for m in TAG_RE.finditer(html):
        closing, tag, attrs = m.group(1), m.group(2), m.group(3)
        if closing:
            # end tag
            if stack:
                stack.pop()
            continue
        # opening or self-closing
        cm = CLASS_RE.search(attrs)
        cls_val = cm.group(1) if cm else ''
        parent_ctx = stack[-1] if stack else False
        is_card_here = has_card_class(cls_val)
        ctx = parent_ctx or is_card_here

        # self-closing?
        self_closing = attrs.strip().endswith('/')

        # annotate if inside card context and this is a text container
        if ctx and cm and tag.lower() in ('h1','h2','h3','h4','h5','h6','p','li','span'):
            new_classes = add_card_role(cls_val, tag)
            if new_classes != cls_val:
                # compute absolute positions for replacement
                attr_abs_start = m.start(3)
                cls_abs_start = attr_abs_start + cm.start(1)
                cls_abs_end = attr_abs_start + cm.end(1)
                edits.append((cls_abs_start, cls_abs_end, new_classes))
                changed += 1

        # push context for nested children
        stack.append(ctx)
        if self_closing and stack:
            stack.pop()

    if not edits:
        return html, 0
    # apply edits in reverse order
    out = html
    for s, e, repl in sorted(edits, key=lambda x: x[0], reverse=True):
        out = out[:s] + repl + out[e:]
    return out, changed


def main():
    ap = argparse.ArgumentParser(description='Annotate card inner elements with card__title/body/meta based on role-* or tag heuristics')
    ap.add_argument('--root', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    html_path = root / 'index.html'
    if not html_path.exists():
        raise SystemExit('index.html not found')
    src = html_path.read_text(encoding='utf-8', errors='ignore')
    out, changed = annotate_card_roles(src)
    if args.dry_run:
        print(f"[CARD-ROLES] would annotate={changed}")
        return
    if changed:
        bak = html_path.with_suffix(html_path.suffix + '.card_roles.bak')
        if not bak.exists():
            bak.write_text(src, encoding='utf-8')
        html_path.write_text(out, encoding='utf-8')
    print(f"[CARD-ROLES] annotated={changed}")


if __name__ == '__main__':
    main()


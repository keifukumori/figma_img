#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Set, Tuple


def collect_used_n_tokens(root: Path) -> Set[str]:
    used: Set[str] = set()
    class_re = re.compile(r'class=\"([^\"]+)\"')
    for hp in root.rglob('*.html'):
        try:
            text = hp.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for m in class_re.finditer(text):
            for c in m.group(1).split():
                if c.startswith('n-'):
                    used.add(c)
    return used


def find_media_blocks(text: str) -> List[Tuple[int, int, str, str]]:
    blocks = []
    i = 0
    while True:
        m = re.search(r"@media[^\{]+\{", text[i:])
        if not m:
            break
        start = i + m.start()
        header_end = i + m.end()
        depth = 1
        j = header_end
        n = len(text)
        while j < n and depth > 0:
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            j += 1
        body = text[header_end:j-1]
        header = text[start:header_end]
        blocks.append((start, j-1, header, body))
        i = j
    return blocks


def prune_in_block(css: str, used: Set[str]) -> Tuple[str, int]:
    """Prune .n-* rules within a CSS text (no @media level changes). Returns (new_css, removed_count)."""
    removed = 0

    def repl_rule(m: re.Match) -> str:
        nonlocal removed
        sel = (m.group(2) or '').strip()
        body = (m.group(3) or '').strip()
        if not sel:
            return m.group(0)
        # Handle multi selectors: split, remove unused n- selectors
        parts = [s.strip() for s in sel.split(',') if s.strip()]
        new_parts: List[str] = []
        drop_entire = False
        changed = False
        for p in parts:
            # simple n- selector forms we can remove: .n-xxx or :where(.n-xxx)
            m1 = re.fullmatch(rf"\.n-[a-zA-Z0-9_-]+", p)
            m2 = re.fullmatch(rf":where\(\.n-[a-zA-Z0-9_-]+\)", p)
            if m1 or m2:
                ncls = p.split('.')[-1].rstrip(')')  # crude extract
                if ncls not in used:
                    changed = True
                    removed += 1
                    continue  # drop this selector
            new_parts.append(p)
        if changed and not new_parts:
            # if we removed the only selector(s), drop whole rule
            removed += 1
            return ''
        if changed:
            return m.group(1) + ', '.join(new_parts) + '{' + body + '}'
        return m.group(0)

    # Remove generic guards like [class^="n-"] when no n- used at all
    if not used:
        css = re.sub(r"\s*\[[^\]]*class\^=\"n-\"[^\]]*\][^{]*\{[^}]*\}", "", css)
        css = re.sub(r"\s*\[[^\]]*class\*\=\"\sn-\"[^\]]*\][^{]*\{[^}]*\}", "", css)

    new_css = re.sub(r"(^|\n)\s*([^@\n][^{]+?)\s*\{([^}]*)\}", repl_rule, css)
    return new_css, removed


def prune_unused_n_rules(css_path: Path, used: Set[str], backup: bool) -> int:
    if not css_path.exists():
        return 0
    css = css_path.read_text(encoding='utf-8', errors='ignore')
    orig = css
    # prune top-level
    css1, rem1 = prune_in_block(css, used)
    # prune inside media blocks
    blocks = find_media_blocks(css1)
    offset = 0
    rem2 = 0
    for s, e, header, body in blocks:
        start = s + offset
        end = e + offset
        new_body, r = prune_in_block(body, used)
        rem2 += r
        if new_body != body:
            css1 = css1[:start] + header + new_body + '}' + css1[end:]
            offset += (len(header) + len(new_body) + 1) - (end - start)
    # If nothing changed and no n-* are used anywhere, apply a conservative fallback to drop any simple
    # top-level .n-* rules that may have been missed by the generic parser (formatting anomalies, etc.).
    fallback_removed = 0
    if rem1 + rem2 == 0 and not used:
        css2 = re.sub(r"(^|\n)\s*\.n-[a-zA-Z0-9_-]+\s*\{[^}]*\}\s*", "\n", css1)
        if css2 != css1:
            fallback_removed = 1
            css1 = css2

    if css1 != orig or fallback_removed:
        if backup:
            bak = css_path.with_suffix(css_path.suffix + '.prune_n_css.bak')
            if not bak.exists():
                bak.write_text(orig, encoding='utf-8')
        css_path.write_text(css1, encoding='utf-8')
    return rem1 + rem2 + fallback_removed


def main():
    ap = argparse.ArgumentParser(description='Prune .n-* CSS rules/selectors that are no longer referenced in HTML')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    used = collect_used_n_tokens(root)
    total_removed = 0
    total_removed += prune_unused_n_rules(root / 'style.css', used, backup=args.backup)
    total_removed += prune_unused_n_rules(root / 'style-pc.css', used, backup=args.backup)
    total_removed += prune_unused_n_rules(root / 'style-sp.css', used, backup=args.backup)
    print(f"[PRUNE-N-CSS] selectors_or_rules_removed={total_removed}, used_n_tokens={len(used)}")


if __name__ == '__main__':
    main()

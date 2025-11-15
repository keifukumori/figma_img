#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


OPEN_TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)>", re.I)
CLASS_RE = re.compile(r"class=\"([^\"]+)\"")
SECTION_RE = re.compile(r"<section\b[^>]*\bclass=\"([^\"]+)\"", re.I)


def nearest_section(lines: List[str], up_to_idx: int) -> str | None:
    j = up_to_idx
    while j >= 0:
        m = SECTION_RE.search(lines[j])
        if m:
            classes = m.group(1).split()
            return classes[0] if classes else None
        j -= 1
    return None


def collect_n_alias_map(root: Path) -> Tuple[Dict[str, Counter], Dict[str, Counter]]:
    n_to_sections: Dict[str, Counter] = defaultdict(Counter)
    n_to_aliases: Dict[str, Counter] = defaultdict(Counter)
    for hp in sorted(root.rglob('*.html')):
        try:
            lines = hp.read_text(encoding='utf-8', errors='ignore').splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            m = OPEN_TAG_RE.search(line)
            if not m:
                continue
            cm = CLASS_RE.search(m.group(2))
            if not cm:
                continue
            classes = cm.group(1).split()
            ns = [c for c in classes if c.startswith('n-')]
            if not ns:
                continue
            sec = nearest_section(lines, i) or 'section'
            aliases = [c for c in classes if '__' in c and (c.startswith(sec + '__') or c.endswith('__row-item') or c.endswith('__card'))]
            if not aliases and 'row-item' in classes:
                aliases = [f"{sec}__row-item"]
            if not aliases and 'card' in classes:
                aliases = [f"{sec}__card"]
            for n in ns:
                n_to_sections[n][sec] += 1
                for al in aliases:
                    n_to_aliases[n][al] += 1
    return n_to_sections, n_to_aliases


def choose_alias(n_to_sections: Dict[str, Counter], n_to_aliases: Dict[str, Counter], width: int = 2, min_support: float = 0.7) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    # generate fallback per section counters
    fallback_counters: Dict[str, int] = defaultdict(int)
    for n, sects in n_to_sections.items():
        total = sum(sects.values())
        if total == 0:
            continue
        alias_counts = n_to_aliases.get(n) or Counter()
        if alias_counts:
            al, cnt = alias_counts.most_common(1)[0]
            if cnt / total >= min_support:
                mapping[n] = al
                continue
        # fallback to first section
        sec = sects.most_common(1)[0][0]
        fallback_counters[sec] += 1
        idx = fallback_counters[sec]
        alias = f"{sec}__block-{str(idx).zfill(width)}"
        mapping[n] = alias
    return mapping


def append_alias_to_html(root: Path, mapping: Dict[str, str], backup: bool) -> int:
    files = 0
    for hp in sorted(root.rglob('*.html')):
        try:
            lines = hp.read_text(encoding='utf-8', errors='ignore').splitlines()
        except Exception:
            continue
        changed = False
        for i, line in enumerate(lines):
            m = OPEN_TAG_RE.search(line)
            if not m:
                continue
            cm = CLASS_RE.search(m.group(2))
            if not cm:
                continue
            classes = cm.group(1).split()
            new = classes[:]
            add_any = False
            for c in classes:
                al = mapping.get(c)
                if al and al not in new:
                    new.append(al)
                    add_any = True
            if add_any:
                attrs = m.group(2)
                new_attrs = attrs[:cm.start()] + f'class="{' '.join(new)}"' + attrs[cm.end():]
                # Preserve the rest of the line after the matched tag
                prefix = line[:m.start()]
                suffix = line[m.end():]
                lines[i] = prefix + f"<{m.group(1)}{new_attrs}>" + suffix
                changed = True
        if changed:
            if backup:
                hp.with_suffix(hp.suffix + '.graft.bak').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            hp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            files += 1
    return files


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


def comma_join_simple_selectors(sel: str, ncls: str, alias: str) -> str | None:
    parts = [s.strip() for s in sel.split(',') if s.strip()]
    changed = False
    new_parts: List[str] = []
    for p in parts:
        new_parts.append(p)
        if p == f'.{ncls}' or p == f':where(.{ncls})':
            if f'.{alias}' not in parts and f':where(.{alias})' not in parts:
                new_parts.append(f'.{alias}')
                changed = True
    if changed:
        return ', '.join(new_parts)
    return None


def _has_text_color(body: str) -> bool:
    # Detect standalone color: ... declarations (avoid background-color)
    return bool(re.search(r"(^|;)\s*color\s*:\s*[^;]+", body or "", flags=re.I))

def _has_spacing(body: str) -> bool:
    # Detect margin/padding declarations
    return bool(re.search(r"(^|;|\{)\s*(margin|padding)(-[a-z]+)?\s*:\s*[^;]+", body or "", flags=re.I))


def graft_css(root: Path, mapping: Dict[str, str], backup: bool) -> int:
    css_path = root / 'style.css'
    if not css_path.exists():
        return 0
    css = css_path.read_text(encoding='utf-8', errors='ignore')
    orig = css
    added = 0
    # Process top-level rules
    def repl_top(m: re.Match) -> str:
        nonlocal added
        sel = (m.group(2) or '').strip()
        body = (m.group(3) or '').strip()
        if not sel:
            return m.group(0)
        # Do not comma-join alias into rules that include text color to avoid
        # propagating instance text colors to shared aliases.
        if _has_text_color(body) or _has_spacing(body):
            return m.group(0)
        for ncls, alias in mapping.items():
            new_sel = comma_join_simple_selectors(sel, ncls, alias)
            if new_sel:
                added += 1
                return m.group(1) + new_sel + '{' + body + '}'
        return m.group(0)

    css = re.sub(r"(^|\n)\s*([^@\n][^{]+?)\s*\{([^}]*)\}", repl_top, css)

    # Process media blocks bodies similarly
    blocks = find_media_blocks(css)
    # Rebuild css by replacing block bodies where needed
    offset = 0
    for s, e, header, body in blocks:
        body_text = body
        def repl_body(m: re.Match) -> str:
            nonlocal added
            sel = (m.group(2) or '').strip()
            b = (m.group(3) or '').strip()
            if not sel:
                return m.group(0)
            if _has_text_color(b) or _has_spacing(b):
                return m.group(0)
            for ncls, alias in mapping.items():
                new_sel = comma_join_simple_selectors(sel, ncls, alias)
                if new_sel:
                    added += 1
                    return m.group(1) + new_sel + '{' + b + '}'
            return m.group(0)
        new_body = re.sub(r"(^|\n)\s*([^@\n][^{]+?)\s*\{([^}]*)\}", repl_body, body_text)
        if new_body != body_text:
            # replace in css
            start = s + offset
            end = e + offset
            css = css[:start] + header + new_body + '}' + css[end:]
            offset += (len(header) + len(new_body) + 1) - (end - start)

    if css != orig:
        if backup:
            bak = css_path.with_suffix(css_path.suffix + '.graft.bak')
            if not bak.exists():
                bak.write_text(orig, encoding='utf-8')
        css_path.write_text(css, encoding='utf-8')
    return added


def main():
    ap = argparse.ArgumentParser(description='Alias graft for residual n-* classes: append section alias to HTML and comma-join CSS rules for simple selectors')
    ap.add_argument('--root', required=True)
    ap.add_argument('--min-support', type=float, default=0.7)
    ap.add_argument('--enum-width', type=int, default=2)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    n_to_sections, n_to_aliases = collect_n_alias_map(root)
    mapping = choose_alias(n_to_sections, n_to_aliases, width=args.enum_width, min_support=args.min_support)
    files = append_alias_to_html(root, mapping, backup=args.backup)
    added = graft_css(root, mapping, backup=args.backup)
    print(f"[GRAFT] html_files_changed={files}, css_rules_updated={added}, aliases={len(mapping)}")


if __name__ == '__main__':
    main()

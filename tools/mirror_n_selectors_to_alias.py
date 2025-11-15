#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Set


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
    """Scan HTML under root and build maps:
    - n_to_sections: n -> Counter of section names where it appears
    - n_to_aliases: n -> Counter of alias tokens seen on same element (prefer section-scoped aliases)
    """
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
            n_tokens = [c for c in classes if c.startswith('n-')]
            if not n_tokens:
                continue
            sec = nearest_section(lines, i) or 'section'
            # prefer aliases that are section-scoped (contain '__' and start with section__)
            aliases = [c for c in classes if '__' in c and (c.startswith(sec + '__') or c.endswith('__row-item') or c.endswith('__card'))]
            # fallback: infer SECTION__row-item if row-item present
            if not aliases and 'row-item' in classes:
                aliases = [f"{sec}__row-item"]
            if not aliases and 'card' in classes:
                aliases = [f"{sec}__card"]
            for n in n_tokens:
                n_to_sections[n][sec] += 1
                for al in aliases:
                    n_to_aliases[n][al] += 1

    return n_to_sections, n_to_aliases


def choose_alias(n_to_sections: Dict[str, Counter], n_to_aliases: Dict[str, Counter], min_support: float = 0.7) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for n, sects in n_to_sections.items():
        total = sum(sects.values())
        if total == 0:
            continue
        # local to a single section is ideal
        local = len(sects) == 1
        alias_counts = n_to_aliases.get(n) or Counter()
        if not alias_counts:
            # no alias context observed; skip for safety
            continue
        al, cnt = alias_counts.most_common(1)[0]
        if cnt / total >= min_support:
            # if not local but alias is dominant across sections, still accept
            mapping[n] = al
    return mapping


def extract_rules(css_text: str) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Extract (selector, body) lists for top-level and per-media blocks.
    Returns (top_rules, media_blocks) where media_blocks is list of (header, body_text).
    """
    # strip comments for robustness
    css = re.sub(r"/\*.*?\*/", "", css_text or "", flags=re.S)
    media_blocks: List[Tuple[str, str]] = []
    out_top: List[Tuple[str, str]] = []

    # Extract @media blocks
    def find_media_blocks(text: str) -> List[Tuple[str, int, int, str, str]]:
        res = []
        i = 0
        while True:
            m = re.search(r"@media[^\{]+\{", text[i:])
            if not m:
                break
            start = i + m.start()
            header_end = i + m.end()
            # find matching closing brace for this block
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
            res.append((header, start, j-1, header, body))
            i = j
        return res

    medias = find_media_blocks(css)
    # Remove media bodies from top-level scan area by replacing with placeholders
    placeholder_css = css
    for idx, (_h, s, e, header, body) in enumerate(medias):
        placeholder_css = placeholder_css[:s] + f"/*@MEDIA{idx}@*/" + placeholder_css[e:]
        media_blocks.append((header, body))

    # Extract top-level rules (very simple selector { body } that don't start with @)
    for m in re.finditer(r"(^|\n)\s*([^@\n][^{]+?)\s*\{([^}]*)\}", placeholder_css):
        sel = (m.group(2) or '').strip()
        body = (m.group(3) or '').strip()
        if not sel:
            continue
        if '/*@MEDIA' in sel:
            continue
        out_top.append((sel, body))

    return out_top, media_blocks


def mirror_selectors(sel: str, alias_map: Dict[str, str]) -> List[str]:
    # Find n- tokens in selector
    found = set(re.findall(r"(?<![a-zA-Z0-9_-])\.(n-[a-zA-Z0-9_-]+)(?![a-zA-Z0-9_-])", sel))
    found |= set(re.findall(r":where\(\.(n-[a-zA-Z0-9_-]+)\)", sel))
    if not found:
        return []
    # Only mirror those we have mappings for (allow partial)
    s2 = sel
    for n in found:
        al = alias_map.get(n)
        if not al:
            # leave as is
            continue
        s2 = re.sub(rf":where\(\.{re.escape(n)}\)", f".{al}", s2)
        s2 = re.sub(rf"(?<![a-zA-Z0-9_-])\.{re.escape(n)}(?![a-zA-Z0-9_-])", f".{al}", s2)
    if s2 != sel:
        # Split combined selectors and return list of mirrored ones
        return [p.strip() for p in s2.split(',') if p.strip()]
    return []


def _strip_text_color(body: str) -> str:
    """Remove text color declarations (color: ...) from a CSS rule body.
    Keeps background-color and other props intact.
    Also strips margin/padding to avoid spacing bleed onto shared aliases.
    """
    # Split by semicolons but preserve formatting roughly
    parts = re.split(r";", body or "")
    kept = []
    for p in parts:
        seg = p.strip()
        if not seg:
            continue
        # Match standalone color: ... (avoid background-color/...)
        if re.match(r"^color\s*:\s*[^;]+$", seg, re.I):
            continue
        # Drop margin/padding on alias mirror
        if re.match(r"^(margin(-top|-right|-bottom|-left)?|padding(-top|-right|-bottom|-left)?)\s*:\s*[^;]+$", seg, re.I):
            continue
        kept.append(seg)
    return ("; ".join(kept) + (";" if kept else "")).strip()


def append_rules(css_path: Path, top_new: List[Tuple[str, str]], media_new: List[Tuple[str, List[Tuple[str, str]]]], backup: bool = False) -> int:
    css = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    orig = css
    additions = []
    if top_new:
        additions.append("\n/* mirrored from .n-* selectors (top) */\n")
        for sel, body in top_new:
            fbody = _strip_text_color(body)
            if fbody:
                additions.append(f"{sel}{{{fbody}}}\n")
    for header, rules in media_new:
        if not rules:
            continue
        additions.append("\n/* mirrored from .n-* selectors (media) */\n")
        additions.append(header)
        additions.append("\n")
        for sel, body in rules:
            fbody = _strip_text_color(body)
            if fbody:
                additions.append(f"  {sel}{{{fbody}}}\n")
        additions.append("}\n")
    if additions:
        if backup:
            bak = css_path.with_suffix(css_path.suffix + '.mirror.bak')
            if not bak.exists():
                bak.write_text(orig, encoding='utf-8')
        css += ''.join(additions)
        css_path.write_text(css, encoding='utf-8')
        return len(additions)
    return 0


def main():
    ap = argparse.ArgumentParser(description='Mirror CSS selectors that reference .n-* to section-scoped aliases based on HTML context')
    ap.add_argument('--root', required=True)
    ap.add_argument('--min-support', type=float, default=0.7, help='Min ratio of alias presence on elements with n-* to accept mapping')
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    if not css_path.exists():
        raise SystemExit('style.css not found under root')

    n_to_sections, n_to_aliases = collect_n_alias_map(root)
    alias_map = choose_alias(n_to_sections, n_to_aliases, min_support=args.min_support)

    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    top_rules, media_blocks = extract_rules(css_text)

    # Build new mirrored rules
    top_new: List[Tuple[str, str]] = []
    media_new: List[Tuple[str, List[Tuple[str, str]]]] = []

    # Track seen to avoid duplicates
    seen_rules: Set[Tuple[str, str]] = set()

    for sel, body in top_rules:
        sels = [s.strip() for s in sel.split(',') if s.strip()]
        new_sels: List[str] = []
        for s in sels:
            ms = mirror_selectors(s, alias_map)
            new_sels.extend(ms)
        if new_sels:
            joined = ','.join(new_sels)
            key = (joined, body)
            if key not in seen_rules:
                top_new.append((joined, body))
                seen_rules.add(key)

    for header, body in media_blocks:
        rules = []
        for m in re.finditer(r"(^|\n)\s*([^@\n][^{]+?)\s*\{([^}]*)\}", body):
            sel = (m.group(2) or '').strip()
            rbody = (m.group(3) or '').strip()
            if not sel:
                continue
            sels = [s.strip() for s in sel.split(',') if s.strip()]
            new_sels: List[str] = []
            for s in sels:
                ms = mirror_selectors(s, alias_map)
                new_sels.extend(ms)
            if new_sels:
                joined = ','.join(new_sels)
                key = (joined, rbody)
                if key not in seen_rules:
                    rules.append((joined, rbody))
                    seen_rules.add(key)
        media_new.append((header, rules))

    added = append_rules(css_path, top_new, media_new, backup=args.backup)
    # Write small report
    report = {
        'mapped': alias_map,
        'top_rules_added': len(top_new),
        'media_blocks_added': sum(1 for _, r in media_new if r),
        'total_rules_appended': added,
    }
    (root / 'mirror_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[MIRROR] aliases={len(alias_map)} top_rules={len(top_new)} media_blocks_with_additions={report['media_blocks_added']}")


if __name__ == '__main__':
    main()

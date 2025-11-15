#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set


CLASS_RE = re.compile(r"class=\"([^\"]*)\"")


def load_breaks(path: Path) -> Dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    return data if isinstance(data, dict) else {}


def select_candidates(cands: List[Dict], reasons: Set[str], min_gap: int = 2) -> List[int]:
    """Return list of line numbers to apply as breaks (1-based),
    filtered by reasons and deduped by a small gap window.
    """
    out: List[int] = []
    last = -999
    for c in cands:
        rs = set(c.get('reasons') or [])
        if not rs & reasons:
            continue
        ln = int(c.get('line') or 0)
        if ln <= 0:
            continue
        if ln - last <= min_gap:
            continue
        out.append(ln)
        last = ln
    return out


def add_token_to_line(line: str, token: str) -> str:
    m = CLASS_RE.search(line)
    if m:
        classes = m.group(1)
        arr = classes.split()
        if token not in arr:
            arr.append(token)
        new = ' '.join(arr)
        return line[:m.start()] + f'class="{new}"' + line[m.end():]
    # no class attribute, insert one right after tag name
    m2 = re.match(r"(\s*<[^\s>]+)([^>]*)>", line)
    if m2:
        return f"{m2.group(1)} class=\"{token}\"{m2.group(2)}>"
    return line


def apply_breaks_to_file(html_path: Path, section: str, lines_to_mark: List[int], enum_width: int = 2, backup: bool = False) -> int:
    if not lines_to_mark:
        return 0
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    lines = text.splitlines()
    changed = 0
    for i, ln in enumerate(lines_to_mark, start=1):
        idx = ln - 1
        if 0 <= idx < len(lines):
            token = f"{section}-{str(i).zfill(enum_width)}"
            new_line = add_token_to_line(lines[idx], token)
            if new_line != lines[idx]:
                lines[idx] = new_line
                changed += 1
    if changed:
        out = '\n'.join(lines) + '\n'
        if backup:
            html_path.with_suffix(html_path.suffix + '.sectsplit.bak').write_text(text, encoding='utf-8')
        html_path.write_text(out, encoding='utf-8')
    return changed


def main():
    ap = argparse.ArgumentParser(description='Apply pseudo section breaks (about-01/02/...) to HTML based on section_breaks.json')
    ap.add_argument('--root', required=True)
    ap.add_argument('--in', dest='infile', help='Input JSON from propose_section_breaks (default: <root>/section_breaks.json)')
    ap.add_argument('--reasons', default='heading,typography,background,rule', help='Comma-separated reasons to pick (e.g., heading,typography,background,rule,layout,large-gap)')
    ap.add_argument('--enum-width', type=int, default=2)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    infile = Path(args.infile) if args.infile else (root / 'section_breaks.json')
    if not infile.exists():
        raise SystemExit(f'breaks json not found: {infile}')
    data = load_breaks(infile)
    pick = {s.strip() for s in (args.reasons or '').split(',') if s.strip()}

    total_changed = 0
    for rel, proposals in data.items():
        hp = root / rel
        if not hp.exists():
            continue
        # proposals is a list of { section, file, candidates }
        for sec in proposals:
            section = sec.get('section') or 'section'
            cands = sec.get('candidates') or []
            lines = select_candidates(cands, pick)
            if not lines:
                continue
            total_changed += apply_breaks_to_file(hp, section, lines, enum_width=args.enum_width, backup=args.backup)
    print(f"[APPLY-SECT] files_changed={(1 if total_changed>0 else 0)}, lines_marked={total_changed}")


if __name__ == '__main__':
    main()


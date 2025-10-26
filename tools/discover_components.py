#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


LAYOUT_KEYS = (
    "display", "flex-direction", "gap", "justify-content", "align-items", "flex-wrap", "align-self",
    # safe signals
    "width", "height", "min-width", "min-height",
)

VISUAL_FLAGS = (
    "background-color", "box-shadow", "border-radius", "overflow",
)

TOKEN_PREFIXES = (
    "fx-", "g-", "ai-", "jc-", "fw-", "px-", "py-", "pt-", "pr-", "pb-", "pl-",
    "w-", "h-", "as-", "min-w-0", "min-h-0", "clip", "card",
)


def parse_css_classes(css_text: str) -> Dict[str, Dict[str, str]]:
    cmap: Dict[str, Dict[str, str]] = {}
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css_text):
        sels = m.group(1)
        body = m.group(2)
        decls: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if not k:
                continue
            decls[k] = v
        if not decls:
            continue
        for cls in re.findall(r"\.([a-zA-Z0-9_-]+)", sels):
            d = cmap.setdefault(cls, {})
            d.update(decls)
    return cmap


def quant_px(val: str, step: int = 4) -> str:
    m = re.search(r"(-?\d+)", val or "")
    if not m:
        return val
    try:
        n = int(m.group(1))
        q = int(round(n / step) * step)
        return f"{q}px"
    except Exception:
        return val


def split_padding(val: str) -> Tuple[str, str, str, str]:
    parts = re.split(r"\s+", (val or '').strip())
    if not parts:
        return ("", "", "", "")
    # normalize to 4 values (t, r, b, l)
    def _q(x: str) -> str:
        return quant_px(x)
    if len(parts) == 1:
        p = _q(parts[0]); return (p, p, p, p)
    if len(parts) == 2:
        pt = _q(parts[0]); pr = _q(parts[1]); return (pt, pr, pt, pr)
    if len(parts) == 3:
        pt = _q(parts[0]); pr = _q(parts[1]); pb = _q(parts[2]); return (pt, pr, pb, pr)
    pt = _q(parts[0]); pr = _q(parts[1]); pb = _q(parts[2]); pl = _q(parts[3])
    return (pt, pr, pb, pl)


def signature_for(n_class: str, css: Dict[str, Dict[str, str]], present_tokens: List[str]) -> Tuple:
    kv = css.get(n_class, {})
    # layout core
    sig = []
    for k in LAYOUT_KEYS:
        v = kv.get(k)
        if v:
            if k in ("gap", "min-width", "min-height"):
                v = quant_px(v)
            if k == "width" and v not in ("auto", "100%"):
                v = None
            if k == "height" and v not in ("auto", "100%"):
                v = None
        if v:
            sig.append((k, v))
    # padding
    pad = kv.get("padding")
    if pad:
        t, r, b, l = split_padding(pad)
        sig.append(("pt", t)); sig.append(("pr", r)); sig.append(("pb", b)); sig.append(("pl", l))
    for side in ("padding-top", "padding-right", "padding-bottom", "padding-left"):
        if kv.get(side):
            sig.append((side.replace('padding-', 'p'), quant_px(kv.get(side))))
    # visuals as flags
    for vf in VISUAL_FLAGS:
        if kv.get(vf):
            flag = vf if vf != 'overflow' else ('clip' if 'hidden' in kv.get(vf) else None)
            if flag:
                sig.append((flag, True))
    # tokens present (fx/g/ai/jc/fw/px…)
    toks = tuple(sorted([t for t in present_tokens if any(t.startswith(p) for p in TOKEN_PREFIXES)]))
    sig.append(("tokens", toks))
    # normalize ordering
    sig = tuple(sorted(sig))
    return sig


def discover_and_apply(root: Path, apply: bool = False, min_cluster: int = 2) -> Dict:
    css_path = root / 'style.css'
    if not css_path.exists():
        raise SystemExit('style.css not found under root')
    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    css_map = parse_css_classes(css_text)

    cluster_map: Dict[Tuple[str, Tuple], List[Tuple[Path, int, str]]] = {}
    section_name: str | None = None

    # scan all html files
    for hp in sorted(root.rglob('*.html')):
        lines = hp.read_text(encoding='utf-8', errors='ignore').splitlines()
        sec_re = re.compile(r"<section\b[^>]*\bclass=\"([^\"]+)\"", re.I)
        tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*?)>", re.I)
        class_re = re.compile(r"class=\"([^\"]+)\"")
        for i, line in enumerate(lines):
            msec = sec_re.search(line)
            if msec:
                sec_classes = msec.group(1).split()
                section_name = sec_classes[0] if sec_classes else None
            m = tag_re.search(line)
            if not m:
                continue
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                continue
            classes = cm.group(1).split()
            n_tokens = [c for c in classes if c.startswith('n-')]
            if not n_tokens:
                continue
            # present tokens for signature
            present = [c for c in classes if any(c.startswith(p) for p in TOKEN_PREFIXES)]
            # prefer first n-token
            n0 = n_tokens[0]
            sig = signature_for(n0, css_map, present)
            key = (section_name or 'section', sig)
            cluster_map.setdefault(key, []).append((hp, i, n0))

    # build suggestions
    result = {
        'clusters': []
    }
    edits_by_file: Dict[Path, List[Tuple[int, str]]] = {}
    for (sec, sig), items in cluster_map.items():
        if len(items) < min_cluster:
            continue
        # heuristics: determine base alias by visuals + direction
        props = dict(sig)
        tokens = set(props.get('tokens') or [])
        alias_base = None
        if props.get('background-color') or props.get('box-shadow') or 'card' in tokens:
            alias_base = 'card'
        else:
            fd = None
            for k, v in sig:
                if k == 'flex-direction':
                    fd = v
                    break
            alias_base = 'stack' if fd == 'column' else ('row' if fd == 'row' else 'block')
        alias = f"{sec}__{alias_base}"
        result['clusters'].append({
            'section': sec,
            'count': len(items),
            'alias': alias,
        })
        if apply:
            # append alias where missing
            for hp, line_idx, _ in items:
                lines = edits_by_file.setdefault(hp, None)
                if lines is None:
                    lines = hp.read_text(encoding='utf-8', errors='ignore').splitlines()
                    edits_by_file[hp] = lines
                line = edits_by_file[hp][line_idx]
                m = re.search(r"class=\"([^\"]+)\"", line)
                if not m:
                    continue
                classes = m.group(1).split()
                if alias not in classes:
                    classes.append(alias)
                    new_line = line[:m.start()] + f'class="{" ".join(classes)}"' + line[m.end():]
                    edits_by_file[hp][line_idx] = new_line

    if apply and edits_by_file:
        for hp, lines in edits_by_file.items():
            if lines is None:
                continue
            bak = hp.with_suffix(hp.suffix + '.discover.bak')
            if not bak.exists():
                bak.write_text('\n'.join(hp.read_text(encoding='utf-8', errors='ignore').splitlines()) + '\n', encoding='utf-8')
            hp.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    return result


def main():
    ap = argparse.ArgumentParser(description='Discover repeated component patterns and annotate with section-scoped BEM aliases')
    ap.add_argument('--root', required=True, help='Project root containing index.html/style.css')
    ap.add_argument('--apply', action='store_true', help='Apply aliases to HTML (append classes)')
    ap.add_argument('--min-cluster', type=int, default=2, help='Minimum occurrences per signature in a section')
    args = ap.parse_args()

    root = Path(args.root)
    res = discover_and_apply(root, apply=args.apply, min_cluster=args.min_cluster)
    (root / 'component_clusters.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[DISCOVER] clusters={len(res['clusters'])}, written: {root/'component_clusters.json'}")


if __name__ == '__main__':
    main()


#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple


def parse_css_class_props(css_text: str) -> Dict[str, Dict[str, str]]:
    cmap: Dict[str, Dict[str, str]] = {}
    # .class { ... } and multi-selectors; include :where(.class)
    for m in re.finditer(r"(^|\n)\s*([^@\n][^{]+?)\s*\{([^}]*)\}", css_text):
        sel = (m.group(2) or '').strip()
        body = (m.group(3) or '').strip()
        if not sel:
            continue
        decls: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if k:
                decls[k] = v
        if not decls:
            continue
        sels = [s.strip() for s in sel.split(',') if s.strip()]
        for s in sels:
            if s.startswith('.'):
                cmap.setdefault(s[1:], {}).update(decls)
            elif s.startswith(':where(.') and s.endswith(')'):
                cls = s[len(':where(.'):-1]
                cmap.setdefault(cls, {}).update(decls)
    return cmap


def coverage_from_tokens(tokens: List[str]) -> Dict[str, str | Tuple[str, ...]]:
    cov: Dict[str, str | Tuple[str, ...]] = {}
    for t in tokens:
        if t in ('d-flex', 'fx-row', 'fx-col'):
            cov['display'] = 'flex'
            cov['flex-direction'] = 'row' if t == 'fx-row' else ('column' if t == 'fx-col' else cov.get('flex-direction','row'))
        elif t.startswith('g-'):
            try:
                n = int(t.split('-',1)[1]); cov['gap'] = f'{n}px'
            except Exception:
                pass
        elif t.startswith('ai-'):
            cov['align-items'] = t[3:].replace('-', ' ')
        elif t.startswith('jc-'):
            cov['justify-content'] = t[3:].replace('-', ' ')
        elif t.startswith('fw-'):
            cov['flex-wrap'] = t[3:].replace('-', ' ')
        elif t == 'min-w-0':
            cov['min-width'] = '0'
        elif t == 'min-h-0':
            cov['min-height'] = '0'
        elif t == 'clip':
            cov['overflow'] = 'hidden'
        elif t == 'card':
            # generic card baseline visuals
            cov['background-color'] = '*'
            cov['box-shadow'] = '*'
            # padding/border-radius are common; keep wildcard to avoid strict miss
            cov['padding'] = '*'
            cov['border-radius'] = '*'
    return cov


def covered_all(kv: Dict[str, str], cov: Dict[str, str | Tuple[str, ...]]) -> bool:
    for k, v in (kv or {}).items():
        # Ignore commented/neutralized lines captured by naive CSS parsing
        if str(k).strip().startswith('/*'):
            continue
        if k.startswith('--'):
            continue
        if k in ('transform','transform-origin'):
            return False
        # Flex is often redefined by broader aliases (e.g., __row-item) later in CSS.
        # If any flex is present in coverage, treat it as covered to avoid false negatives
        # due to global CSS ordering differences.
        if k == 'flex' and ('flex' in cov):
            continue
        # Treat benign defaults as covered
        if k == 'justify-content' and v.strip() == 'flex-start':
            continue
        if k == 'flex-wrap' and v.strip() == 'nowrap':
            continue
        if k == 'padding':
            # allow wildcard coverage from 'card' or expanded sides from other classes
            if 'padding' in cov:
                continue
            if not any(s in cov for s in ('padding-left','padding-right','padding-top','padding-bottom')):
                return False
            else:
                continue
        cv = cov.get(k)
        if cv is None:
            return False
        if isinstance(cv, str) and cv != '*' and v.strip() != cv.strip():
            return False
    return True


def main():
    ap = argparse.ArgumentParser(description='Prune redundant classes (utilities/aliases) if their CSS is covered by other classes on the same element')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    ap.add_argument('--strict', action='store_true', help='Only drop when selector usage is simple and coverage is exact-ish')
    ap.add_argument('--prefer', choices=['alias','generic'], default='generic', help='When both SECTION__card and card exist, keep which one (default: generic card)')
    args = ap.parse_args()

    root = Path(args.root)
    css_text = (root / 'style.css').read_text(encoding='utf-8', errors='ignore') if (root/'style.css').exists() else ''
    sc_text = (root / 'style-common.css').read_text(encoding='utf-8', errors='ignore') if (root/'style-common.css').exists() else ''
    pc_text = (root / 'style-pc.css').read_text(encoding='utf-8', errors='ignore') if (root/'style-pc.css').exists() else ''
    sp_text = (root / 'style-sp.css').read_text(encoding='utf-8', errors='ignore') if (root/'style-sp.css').exists() else ''
    cmap = parse_css_class_props("\n".join([css_text, sc_text, pc_text, sp_text]))

    tag_re = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')

    pruned_files = 0
    total_drops = 0

    # Flex dependency guard: tokens that require a flex container to be effective
    def has_flex_dependents(tokens: List[str]) -> bool:
        for t in tokens:
            if t == 'eq-cols':
                return True
            if t.startswith(('g-','ai-','jc-','fw-')):
                return True
        return False

    # Helper to decide pair-specific pruning (card vs SECTION__card)
    def prune_card_pair(classes: List[str]) -> List[str]:
        out = classes[:]
        if 'card' in out:
            local_cards = [c for c in out if c.endswith('__card')]
            if local_cards:
                # compute props
                card_kv = cmap.get('card', {})
                for lc in local_cards:
                    lc_kv = cmap.get(lc, {})
                    # If local card has no props or subset of generic card, drop local card (prefer generic)
                    if args.prefer == 'generic':
                        if not lc_kv or covered_all(lc_kv, card_kv):
                            out = [c for c in out if c != lc]
                    else:
                        # prefer alias: if generic adds nothing over alias, drop card
                        cov = lc_kv.copy();
                        if covered_all(card_kv, cov):
                            out = [c for c in out if c != 'card']
        return out

    for html in root.rglob('*.html'):
        src = html.read_text(encoding='utf-8', errors='ignore')
        edits: List[Tuple[int, int, str, int]] = []
        for m in tag_re.finditer(src):
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                continue
            classes = cm.group(1).split()
            if not classes:
                continue
            # Skip links to stylesheets etc.
            tag_name = m.group(1).lower()
            if tag_name in ('link','meta','script','style'):
                continue
            original = classes[:]
            # First, prune card vs SECTION__card pairs (record drops)
            before = classes[:]
            classes = prune_card_pair(classes)
            pair_drops = [c for c in before if c not in classes]

            # Build cumulative coverage of all classes except candidate
            def build_cov(klass_list: List[str], exclude: str | None = None) -> Dict[str, str | Tuple[str, ...]]:
                toks = [k for k in klass_list if k != exclude]
                cov = coverage_from_tokens(toks)
                for c in toks:
                    kv_c = cmap.get(c)
                    if kv_c:
                        # expand padding shorthand into sides for coverage
                        if 'padding' in kv_c:
                            parts = re.split(r"\s+", kv_c['padding'])
                            nums = [p for p in parts if p]
                            if len(nums) == 1:
                                cov['padding-top'] = nums[0]; cov['padding-right'] = nums[0]; cov['padding-bottom'] = nums[0]; cov['padding-left'] = nums[0]
                            elif len(nums) == 2:
                                cov['padding-top'] = nums[0]; cov['padding-bottom'] = nums[0]; cov['padding-left'] = nums[1]; cov['padding-right'] = nums[1]
                            elif len(nums) == 3:
                                cov['padding-top'] = nums[0]; cov['padding-left'] = nums[1]; cov['padding-right'] = nums[1]; cov['padding-bottom'] = nums[2]
                            elif len(nums) >= 4:
                                cov['padding-top'] = nums[0]; cov['padding-right'] = nums[1]; cov['padding-bottom'] = nums[2]; cov['padding-left'] = nums[3]
                        for k, v in kv_c.items():
                            # For generic 'card', keep wildcard coverage for background/box-shadow
                            if c == 'card' and k in ('background-color','box-shadow'):
                                continue
                            if k == 'padding':
                                continue
                            cov[k] = v
                return cov

            drops: List[str] = []
            for c in list(classes):
                # Never prune structural aliases by default (keep __row-item)
                if c.endswith('__row-item'):
                    continue
                # Safety: keep fx-row/fx-col when gap/align/wrap/eq-cols utilities are present.
                # These tokens depend on display:flex; dropping fx-* can silently disable them
                # if no other class guarantees flex (and some aliases may have neutralized flex).
                if c in ('fx-row','fx-col') and has_flex_dependents(classes):
                    continue
                # Evaluate redundancy
                kv = cmap.get(c) or {}
                if not kv:
                    # If class has no CSS and is not a known utility token, consider pruning
                    if not (c in ('card','clip','min-w-0','min-h-0') or c.startswith(('fx-','g-','ai-','jc-','fw-'))):
                        # Allow pruning of empty SECTION__card when card present handled above
                        if c.endswith('__card'):
                            drops.append(c)
                        # Drop empty BEM aliases (section__*) that have no CSS attached,
                        # except for structural aliases we intentionally keep.
                        elif ('__' in c) and not (c.endswith('__row') or c.endswith('__row-item') or c.endswith('__card')):
                            drops.append(c)
                    continue
                cov = build_cov(classes, exclude=c)
                if covered_all(kv, cov):
                    drops.append(c)

            all_drops = pair_drops + drops
            if all_drops:
                kept = [c for c in classes if c not in drops]  # pair drops already applied in classes
                new_cls = ' '.join(kept)
                new_attrs = attrs[:cm.start()] + f'class="{new_cls}"' + attrs[cm.end():]
                new_tag = f"<{m.group(1)}{new_attrs}>"
                edits.append((m.start(), m.end(), new_tag, len(all_drops)))

        if edits:
            edits.sort(reverse=True)
            out = src
            count_removed = 0
            for s, e, rep, nrm in edits:
                out = out[:s] + rep + out[e:]
                count_removed += nrm
            if args.backup:
                bak = html.with_suffix(html.suffix + '.prune_dups.bak')
                if not bak.exists():
                    bak.write_text(src, encoding='utf-8')
            html.write_text(out, encoding='utf-8')
            pruned_files += 1
            total_drops += count_removed

    print(f"[PRUNE-DUPS] files_changed={pruned_files}, classes_removed={total_drops}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
import json
import os
import re
from html import escape

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, '..'))

# Match typical placeholder strings, including repeated forms
PLACEHOLDER_RE = re.compile(
    r"^(?:\s*(?:テキスト(?:が入ります。?)?)+\s*|TEXT|Lorem|Dummy|Sample|フリー素材|画像をご指定御支給ください)$",
    re.I,
)

def style_from_autolayout(al):
    if not al:
        return {}
    st = {}
    mode = al.get('layoutMode')
    if mode in ('HORIZONTAL','VERTICAL'):
        st['display'] = 'flex'
        st['flex-direction'] = 'row' if mode=='HORIZONTAL' else 'column'
    gap = al.get('itemSpacing')
    if isinstance(gap, (int, float)):
        g = int(round(gap))
        if g < 0:
            g = 0
        st['gap'] = f"{g}px"
    pad = (al.get('padding') or {})
    for side in ('top','right','bottom','left'):
        val = pad.get(side)
        if isinstance(val, (int, float)):
            st[f'padding-{side}'] = f"{int(round(val))}px"
    return st

def style_from_fills(fills, for_text=False):
    st = {}
    if not fills:
        return st
    f = fills[0] or {}
    val = f.get('value') or {}
    hexv = val.get('hex')
    opacity = val.get('opacity', 1)
    if hexv and (opacity is None or opacity > 0):
        if for_text:
            st['color'] = hexv
        else:
            st['background-color'] = hexv
            if opacity is not None and opacity < 1:
                # could add rgba if needed; keep hex for now
                pass
    return st

def style_from_text_style(ts):
    st = {}
    v = (ts or {}).get('value') or {}
    fs = v.get('fontSize')
    if isinstance(fs, (int, float)):
        st['font-size'] = f"{int(round(fs))}px"
    fw = v.get('fontWeight')
    if isinstance(fw, (int, float)):
        st['font-weight'] = str(int(fw))
    lh = v.get('lineHeightPx')
    if isinstance(lh, (int, float)):
        # use px to match Figma
        st['line-height'] = f"{lh:.1f}px"
    ff = v.get('fontFamily')
    if ff:
        st['font-family'] = ff
    ls = v.get('letterSpacing')
    if isinstance(ls, (int, float)) and ls:
        st['letter-spacing'] = f"{ls}px"
    return st

def style_str(st):
    if not st:
        return ''
    return '; '.join(f"{k}: {v}" for k,v in st.items())

def sanitize_class(name):
    s = re.sub(r"[^a-zA-Z0-9_-]+", '-', name or '').strip('-').lower()
    if not s:
        s = 'node'
    return s

def render_node(n, depth=0, breadcrumbs=False):
    t = n.get('type')
    role = n.get('roleHint')
    name = n.get('name') or ''
    html = []

    if t == 'TEXT':
        text = n.get('characters')
        if text is None or not str(text).strip():
            text = name
        if not text or PLACEHOLDER_RE.match(text.strip()):
            return ''
        st = {}
        st.update(style_from_text_style(n.get('textStyle')))
        st.update(style_from_fills(n.get('fills'), for_text=True))
        tag = 'span' if breadcrumbs else 'p'
        html.append(f"<{tag} style=\"{style_str(st)}\">{escape(str(text))}</{tag}>")
        return '\n'.join(html)

    # Skip pure decoration primitives
    if role == 'decoration' and t in ('VECTOR','RECTANGLE','ELLIPSE','LINE'):
        return ''

    # Breadcrumbs special handling
    if name == 'Breadcrumbs' or role == 'nav':
        # collect text leaves
        labels = []
        stack = [n]
        while stack:
            cur = stack.pop()
            if cur.get('type') == 'TEXT':
                tx = cur.get('characters') or cur.get('name') or ''
                tx = tx.strip()
                if tx and not PLACEHOLDER_RE.match(tx):
                    labels.append((tx, cur))
            for c in (cur.get('children') or []):
                stack.append(c)
        if labels:
            al = n.get('autoLayout') or {}
            st = style_from_autolayout(al)
            st.update(style_from_fills(n.get('fills'), for_text=False))
            nav_style = style_str(st)
            html.append(f"<nav class=\"about__breadcrumbs\" aria-label=\"breadcrumb\" style=\"{nav_style}\">")
            html.append("  <ol class=\"breadcrumbs\" style=\"display:flex; gap:8px; padding:0; margin:0; list-style:none;\">")
            for i,(tx, cur) in enumerate(labels):
                tx_html = render_node(cur, breadcrumbs=True)
                if i < len(labels)-1:
                    html.append(f"    <li class=\"breadcrumbs__item\">{tx_html}</li>")
                else:
                    html.append(f"    <li class=\"breadcrumbs__item\" aria-current=\"page\">{tx_html}</li>")
            html.append("  </ol>")
            html.append("</nav>")
        return '\n'.join(html)

    # Generic container (FRAME/INSTANCE)
    if t in ('FRAME','INSTANCE'):
        st = {}
        st.update(style_from_autolayout(n.get('autoLayout')))
        st.update(style_from_fills(n.get('fills'), for_text=False))

        # Flatten wrappers with no visual effect and single child
        children = [render_node(c, depth+1) for c in (n.get('children') or [])]
        children = [c for c in children if c]
        if not st and len(children) == 1:
            return children[0]

        cls = f"about__{sanitize_class(name)}"
        html.append(f"<div class=\"{cls}\" style=\"{style_str(st)}\">")
        html.extend(children)
        html.append("</div>")
        return '\n'.join(html)

    # Unknowns: skip
    return ''

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('json_path')
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'out', 'r-8_mens_about_pc'))
    args = ap.parse_args()

    with open(args.json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Build HTML
    head = (
        "<!doctype html>\n"
        "<html lang=\"ja\">\n"
        "  <head>\n"
        "    <meta charset=\"utf-8\" />\n"
        "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "    <title>r-8_mens_about_pc</title>\n"
        "    <link rel=\"stylesheet\" href=\"./styles.css\" />\n"
        "  </head>\n"
        "  <body>\n"
        "    <main class=\"about\">\n"
    )
    foot = (
        "    </main>\n"
        "  </body>\n"
        "</html>\n"
    )

    html_parts = [head]
    for root in data.get('requirements', []):
        html_parts.append(render_node(root))
    html_parts.append(foot)
    html = '\n'.join(p for p in html_parts if p is not None)

    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)

    # Minimal CSS reset + body baseline; most styles inline per JSON
    css = (
        ":root{--maxw:1200px;}\n"
        "*{box-sizing:border-box;}\n"
        "html,body{height:100%;}\n"
        "body{margin:0;background:#fff;color:#1A1A1A;font-family:'Noto Sans JP', system-ui, -apple-system, 'Hiragino Kaku Gothic ProN', Meiryo, sans-serif;}\n"
        ".about{max-width:var(--maxw);margin:0 auto;padding:16px;}\n"
        ".breadcrumbs__item{color:#666;}\n"
    )
    with open(os.path.join(args.outdir, 'styles.css'), 'w', encoding='utf-8') as f:
        f.write(css)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
import argparse
import json
import os
import re
from html import escape


def find_node_by_id(node, target):
    if not isinstance(node, dict):
        return None
    if node.get('id') == target or node.get('nodeId') == target:
        return node
    for c in node.get('children') or []:
        f = find_node_by_id(c, target)
        if f:
            return f
    return None


def safe_class(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", '-', (name or '').strip().lower())
    return s.strip('-') or 'node'


def add(d, prop):
    if prop and ':' in prop:
        k = prop.split(':', 1)[0].strip().lower()
        d[k] = prop


def node_display_style(n):
    out = {}
    mode = (n.get('layoutMode') or '').upper()
    if mode in ('HORIZONTAL', 'VERTICAL'):
        add(out, 'display:flex')
        add(out, f"flex-direction:{'row' if mode=='HORIZONTAL' else 'column'}")
        gap = n.get('itemSpacing')
        if isinstance(gap, (int, float)) and gap:
            g = int(round(gap))
            if g < 0:
                g = 0
            add(out, f'gap:{g}px')
        # padding
        for fig, css in (
            ('paddingLeft','padding-left'),('paddingRight','padding-right'),
            ('paddingTop','padding-top'),('paddingBottom','padding-bottom'),
        ):
            v = n.get(fig)
            if isinstance(v, (int, float)) and v:
                add(out, f'{css}:{int(round(v))}px')
        # align
        def map_align(v):
            m={'MIN':'flex-start','MAX':'flex-end','CENTER':'center','SPACE_BETWEEN':'space-between'}
            return m.get((v or '').upper())
        pa = map_align(n.get('primaryAxisAlignItems'))
        ca = map_align(n.get('counterAxisAlignItems'))
        if pa:
            add(out, f'justify-content:{pa}')
        if ca:
            add(out, f'align-items:{ca}')
    return out


def node_visual_style(n):
    out = {}
    # fills (SOLID or value.hex)
    fills = n.get('fills') or []
    node_op = float(n.get('opacity', 1) or 1)
    if isinstance(fills, list):
        for f in reversed(fills):
            if not isinstance(f, dict) or f.get('visible') is False:
                continue
            if f.get('type') == 'SOLID' and isinstance(f.get('color'), dict):
                c = f['color']; r=int(round(c.get('r',0)*255)); g=int(round(c.get('g',0)*255)); b=int(round(c.get('b',0)*255)); a=float(c.get('a',1))*node_op
                add(out, f'background-color:rgba({r},{g},{b},{a:.2f})')
                break
            v = f.get('value') or {}
            hx = v.get('hex')
            if isinstance(hx, str):
                op = float(v.get('opacity',1))*node_op
                if op >= 1:
                    add(out, f'background-color:{hx}')
                else:
                    s = hx.lstrip('#'); s = s if len(s)!=3 else ''.join(ch*2 for ch in s)
                    r=int(s[0:2],16); g=int(s[2:4],16); b=int(s[4:6],16)
                    add(out, f'background-color:rgba({r},{g},{b},{op:.2f})')
                break
    # radius
    rr = n.get('rectangleCornerRadii')
    if isinstance(rr, list) and len(rr)==4:
        try:
            vals = [int(round(float(x))) for x in rr]
            add(out, f'border-radius:{vals[0]}px {vals[1]}px {vals[2]}px {vals[3]}px')
        except Exception:
            pass
    else:
        try:
            cr = float(n.get('cornerRadius') or 0)
            if cr>0: add(out, f'border-radius:{int(round(cr))}px')
        except Exception:
            pass
    return out


def child_flex_hint(parent, child):
    # layoutGrow -> flex-grow; layoutAlign -> align-self
    out = {}
    lg = child.get('layoutGrow')
    if isinstance(lg, (int, float)) and lg>0:
        add(out, 'flex:1 1 auto')
    la = (child.get('layoutAlign') or '').upper()
    if la == 'STRETCH':
        add(out, 'align-self:stretch')
    return out


def text_style(n):
    out = {}
    st = n.get('style') or {}
    if isinstance(st, dict):
        fs = st.get('fontSize')
        if isinstance(fs, (int, float)): add(out, f'font-size:{int(round(fs))}px')
        fw = st.get('fontWeight')
        if isinstance(fw, (int, float)): add(out, f'font-weight:{int(round(fw))}')
        lh = st.get('lineHeightPx')
        if isinstance(lh, (int, float)): add(out, f'line-height:{lh:.1f}px')
        ls = st.get('letterSpacing')
        if isinstance(ls, (int, float)) and ls: add(out, f'letter-spacing:{ls}px')
    # color from fills
    fills = n.get('fills') or []
    if isinstance(fills, list):
        for f in reversed(fills):
            if not isinstance(f, dict) or f.get('visible', True) is False: continue
            if f.get('type')=='SOLID' and isinstance(f.get('color'), dict):
                c=f['color']; r=int(round(c.get('r',0)*255)); g=int(round(c.get('g',0)*255)); b=int(round(c.get('b',0)*255)); a=float(c.get('a',1))
                add(out, f'color:rgba({r},{g},{b},{a:.2f})')
                break
    return out


def build_html(node, css_rules, block='section', depth=0, parent=None):
    if not isinstance(node, dict) or node.get('visible') is False:
        return ''
    t = (node.get('type') or '').upper()
    name = node.get('name') or t.title()
    base = f"{block}__{safe_class(name)}" if depth>0 else block

    # container styles
    disp = node_display_style(node)
    vis = node_visual_style(node)
    styles = {}
    styles.update(disp); styles.update(vis)
    if styles:
        css_rules.append((f'.{base}', list(styles.values())))

    if t == 'TEXT':
        tx = node.get('characters') or ''
        ts = text_style(node)
        if ts:
            css_rules.append((f'.{base}', list(ts.values())))
        return f'<p class="{base}">{escape(str(tx))}</p>'

    # children
    html_children = []
    for c in node.get('children') or []:
        # child flex hints
        ch_style = child_flex_hint(node, c)
        if ch_style:
            css_rules.append((f'.{base} > .{safe_class(c.get("name") or c.get("type") or "child")}', list(ch_style.values())))
        html_children.append(build_html(c, css_rules, block=block, depth=depth+1, parent=node))

    tag = 'section' if depth==0 else 'div'
    return f'<{tag} class="{base}">\n' + '\n'.join(h for h in html_children if h) + f'\n</{tag}>'


def emit_css(css_rules):
    out = ['*{box-sizing:border-box}','img{max-width:100%;height:auto;display:block}','body{margin:0;color:#222;font-family:-apple-system,BlinkMacSystemFont,"Noto Sans JP",sans-serif;}']
    for sel, props in css_rules:
        uniq = {}
        for p in props:
            k = p.split(':',1)[0].strip().lower(); uniq[k]=p
        out.append(sel+'{\n  '+';\n  '.join(uniq.values())+'\n}')
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description='Render flex (Auto Layout) HTML from full Figma JSON')
    ap.add_argument('--json', required=True)
    ap.add_argument('--frame-id', required=True)
    ap.add_argument('--out', default='figma-json-minimal-renderer/dist/flex')
    ap.add_argument('--block', default='section', help='Block name for BEM (e.g., c-staff-education)')
    args = ap.parse_args()

    with open(args.json,'r',encoding='utf-8') as f:
        data=json.load(f)
    frame=find_node_by_id(data.get('document') or {}, args.frame_id)
    if not frame:
        raise SystemExit(f'Frame not found: {args.frame_id}')
    css_rules=[]
    html=build_html(frame, css_rules, block=args.block, depth=0)
    css=emit_css(css_rules)
    os.makedirs(args.out, exist_ok=True)
    out=os.path.join(args.out, f'flex_{args.frame_id.replace(":","_")}.html')
    with open(out,'w',encoding='utf-8') as f:
        f.write('<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8"/>\n<meta name="viewport" content="width=device-width, initial-scale=1"/>\n')
        f.write('<style>'+css+'</style>\n')
        f.write('</head>\n<body>\n')
        f.write(html+'\n')
        f.write('</body>\n</html>\n')
    print(out)


if __name__=='__main__':
    main()


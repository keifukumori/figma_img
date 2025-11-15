#!/usr/bin/env python3
import argparse
import json
import os
import re
from html import escape


def find_node_by_id(node: dict, target_id: str):
    if not isinstance(node, dict):
        return None
    # match both id and nodeId
    if node.get('id') == target_id or node.get('nodeId') == target_id:
        return node
    for c in node.get('children') or []:
        found = find_node_by_id(c, target_id)
        if found:
            return found
    return None


def rgba_from_solid(fill: dict, node_opacity: float = 1.0):
    try:
        if fill.get('type') == 'SOLID' and isinstance(fill.get('color'), dict):
            c = fill['color']
            r = int(round(float(c.get('r', 0)) * 255))
            g = int(round(float(c.get('g', 0)) * 255))
            b = int(round(float(c.get('b', 0)) * 255))
            a = float(c.get('a', 1)) * node_opacity
            return f'rgba({r},{g},{b},{a:.2f})'
        v = fill.get('value') or {}
        hx = v.get('hex')
        if isinstance(hx, str):
            op = float(v.get('opacity', 1)) * node_opacity
            if op >= 1:
                return hx
            # parse hex
            s = hx.lstrip('#')
            if len(s) == 3:
                s = ''.join(ch*2 for ch in s)
            r = int(s[0:2], 16)
            g = int(s[2:4], 16)
            b = int(s[4:6], 16)
            return f'rgba({r},{g},{b},{op:.2f})'
    except Exception:
        return None
    return None


def style_from_node(node: dict):
    styles = []
    node_op = float(node.get('opacity', 1) or 1)
    # background from fills (take top-most visible SOLID)
    fills = node.get('fills') or []
    if isinstance(fills, list):
        for f in reversed(fills):
            if isinstance(f, dict) and f.get('visible', True):
                col = rgba_from_solid(f, node_op)
                if col:
                    styles.append(f'background-color:{col}')
                    break
    # stroke
    sw = node.get('strokeWeight')
    try:
        swv = int(round(float(swv)))  # noqa
    except Exception:
        swv = None
    strokes = node.get('strokes') or []
    if strokes and isinstance(strokes, list):
        for s in reversed(strokes):
            if isinstance(s, dict) and s.get('visible', True):
                col = rgba_from_solid(s, 1.0)
                if col and swv and swv > 0:
                    styles.append(f'border:{swv}px solid {col}')
                break
    # radius
    if node.get('rectangleCornerRadii') and isinstance(node.get('rectangleCornerRadii'), list):
        try:
            rr = [int(round(float(x))) for x in node['rectangleCornerRadii']]
            if len(rr) == 4:
                styles.append(f'border-radius:{rr[0]}px {rr[1]}px {rr[2]}px {rr[3]}px')
        except Exception:
            pass
    else:
        try:
            cr = float(node.get('cornerRadius') or 0)
            if cr > 0:
                styles.append(f'border-radius:{int(round(cr))}px')
        except Exception:
            pass
    # text styles
    if (node.get('type') or '').upper() == 'TEXT':
        st = node.get('style') or {}
        if isinstance(st, dict):
            fs = st.get('fontSize')
            if isinstance(fs, (int, float)):
                styles.append(f'font-size:{int(round(fs))}px')
            fw = st.get('fontWeight')
            if isinstance(fw, (int, float)):
                styles.append(f'font-weight:{int(round(fw))}')
            lh = st.get('lineHeightPx')
            if isinstance(lh, (int, float)):
                styles.append(f'line-height:{lh:.1f}px')
            ls = st.get('letterSpacing')
            if isinstance(ls, (int, float)) and ls:
                styles.append(f'letter-spacing:{ls}px')
            tc = st.get('textAlignHorizontal')
            if isinstance(tc, str):
                m = {'LEFT':'left','CENTER':'center','RIGHT':'right','JUSTIFIED':'justify'}
                if tc in m:
                    styles.append(f'text-align:{m[tc]}')
    return styles


def render_abs(frame: dict):
    # frame bounds
    fb = frame.get('absoluteBoundingBox') or {}
    fx = float(fb.get('x', 0) or 0)
    fy = float(fb.get('y', 0) or 0)
    fw = int(round(float(fb.get('width', 1200) or 1200)))
    fh = int(round(float(fb.get('height', 800) or 800)))
    # container
    html_parts = []
    html_parts.append(f'<div class="abs-canvas" style="position:relative;width:{fw}px;height:{fh}px;overflow:hidden;background:#fff;">')
    z = 0

    def walk(n):
        nonlocal z
        if not isinstance(n, dict):
            return
        t = (n.get('type') or '').upper()
        b = n.get('absoluteBoundingBox') or {}
        if b:
            x = int(round(float(b.get('x', 0) or 0) - fx))
            y = int(round(float(b.get('y', 0) or 0) - fy))
            w = int(round(float(b.get('width', 0) or 0)))
            h = int(round(float(b.get('height', 0) or 0)))
        else:
            x = y = 0
            w = h = 0
        style = [f'position:absolute', f'left:{x}px', f'top:{y}px']
        if w > 0:
            style.append(f'width:{w}px')
        if h > 0:
            style.append(f'height:{h}px')
        style.append(f'z-index:{z}')
        z += 1
        style += style_from_node(n)
        css = ';'.join(style)
        if t == 'TEXT':
            text = n.get('characters') or ''
            html_parts.append(f'<div class="text" style="{css}">{escape(str(text))}</div>')
        elif t in ('RECTANGLE','ELLIPSE','VECTOR','LINE','FRAME','GROUP','COMPONENT','INSTANCE'):
            # render container and traverse children
            html_parts.append(f'<div class="node {t.lower()}" style="{css}">')
            for c in n.get('children') or []:
                walk(c)
            html_parts.append('</div>')
        else:
            # skip unsupported types silently
            pass

    for c in frame.get('children') or []:
        walk(c)
    html_parts.append('</div>')
    return '\n'.join(html_parts)


def main():
    ap = argparse.ArgumentParser(description='Render absolute-positioned HTML from full Figma file JSON')
    ap.add_argument('--json', required=True, help='Path to full Figma file JSON (files API output)')
    ap.add_argument('--frame-id', required=True, help='Target frame id (e.g., 7291:125529)')
    ap.add_argument('--out', default='figma-json-minimal-renderer/dist/abs', help='Output directory')
    ap.add_argument('--inline-css', action='store_true', help='Inline base CSS and node styles')
    args = ap.parse_args()

    with open(args.json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    frame = find_node_by_id(data.get('document') or {}, args.frame_id)
    if not frame:
        raise SystemExit(f'Frame not found: {args.frame_id}')

    body = render_abs(frame)

    base_css = (
        '*{box-sizing:border-box}\n'
        'body{margin:0;background:#f9f9f9;color:#111;font-family:-apple-system, BlinkMacSystemFont, "Noto Sans JP", sans-serif;}\n'
        '.abs-canvas{margin:40px auto;box-shadow:0 0 0 1px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.08);}\n'
    )

    html = (
        '<!doctype html>\n'
        '<html lang="ja">\n'
        '  <head>\n'
        '    <meta charset="utf-8"/>\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f'    <title>{escape(frame.get("name") or "Frame")}</title>\n'
        f'    <style>{base_css}</style>\n'
        '  </head>\n'
        '  <body>\n'
        f'{body}\n'
        '  </body>\n'
        '</html>\n'
    )

    os.makedirs(args.out, exist_ok=True)
    safe_id = re.sub(r'[^a-zA-Z0-9_-]+','_', args.frame_id.replace(':','_'))
    out_path = os.path.join(args.out, f'abs_{safe_id}.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(out_path)


if __name__ == '__main__':
    main()


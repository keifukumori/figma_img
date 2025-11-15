#!/usr/bin/env python3
import argparse
import json
import os
import re
from html import escape


def css_safe_identifier(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = s.replace(":", "-")
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", s)
    if not s:
        s = "node"
    return s


def _hex_to_rgba_tuple(hex_code: str, alpha: float = 1.0):
    try:
        hx = hex_code.strip()
        if hx.startswith('#'):
            hx = hx[1:]
        if len(hx) == 3:
            hx = ''.join(ch*2 for ch in hx)
        r = int(hx[0:2], 16)
        g = int(hx[2:4], 16)
        b = int(hx[4:6], 16)
        a = max(0.0, min(1.0, float(alpha)))
        return r, g, b, a
    except Exception:
        return None


def rgba_from_solid_fill(node):
    fills = node.get("fills") or []
    if not isinstance(fills, list):
        return None
    node_op = float(node.get("opacity", 1) or 1)
    for f in reversed(fills):
        if not isinstance(f, dict):
            continue
        if f.get("visible") is False:
            continue
        # Figma native structure
        if f.get("type") == "SOLID" and isinstance(f.get("color"), dict):
            c = f.get("color") or {}
            r = int(round(float(c.get("r", 0)) * 255))
            g = int(round(float(c.get("g", 0)) * 255))
            b = int(round(float(c.get("b", 0)) * 255))
            a = float(c.get("a", 1)) * node_op
            return f"rgba({r}, {g}, {b}, {a:.2f})"
        # Alternate compact structure: { value: { hex: "#...", opacity: 1 } }
        v = f.get("value")
        if isinstance(v, dict) and isinstance(v.get("hex"), str):
            op = v.get("opacity", 1)
            tpl = _hex_to_rgba_tuple(v.get("hex"), op)
            if tpl:
                r, g, b, a = tpl
                if a >= 1:
                    return f"#{v.get('hex').lstrip('#')}"
                return f"rgba({r}, {g}, {b}, {a:.2f})"
    return None


def stroke_decl_from_node(node):
    strokes = node.get("strokes") or []
    if not isinstance(strokes, list) or not strokes:
        return None
    w = node.get("strokeWeight")
    try:
        wv = int(round(float(w))) if w is not None else None
    except Exception:
        wv = None
    color = None
    for s in reversed(strokes):
        if not isinstance(s, dict):
            continue
        if s.get("visible") is False:
            continue
        if s.get("type") == "SOLID":
            c = s.get("color") or {}
            r = int(round(float(c.get("r", 0)) * 255))
            g = int(round(float(c.get("g", 0)) * 255))
            b = int(round(float(c.get("b", 0)) * 255))
            a = float(c.get("a", 1))
            color = f"rgba({r}, {g}, {b}, {a:.2f})"
            break
    if color and wv and wv > 0:
        return f"border:{wv}px solid {color}"
    return None


def corner_radius_decl(node):
    rr = node.get("rectangleCornerRadii")
    if isinstance(rr, list) and len(rr) == 4:
        try:
            vals = [int(round(float(x))) for x in rr]
            return f"border-radius:{vals[0]}px {vals[1]}px {vals[2]}px {vals[3]}px"
        except Exception:
            pass
    r = node.get("cornerRadius")
    try:
        rv = float(r)
        if rv > 0:
            return f"border-radius:{int(round(rv))}px"
    except Exception:
        pass
    return None


def effects_decl(node):
    eff = node.get("effects") or []
    if not isinstance(eff, list) or not eff:
        return None
    shadows = []
    filters = []
    for e in eff:
        if not isinstance(e, dict) or e.get("visible") is False:
            continue
        t = e.get("type")
        if t in ("DROP_SHADOW", "INNER_SHADOW"):
            c = e.get("color") or {}
            r = int(round(float(c.get("r", 0)) * 255))
            g = int(round(float(c.get("g", 0)) * 255))
            b = int(round(float(c.get("b", 0)) * 255))
            a = float(c.get("a", 1))
            off = e.get("offset") or {}
            x = float(off.get("x", 0))
            y = float(off.get("y", 0))
            rad = float(e.get("radius", 0))
            spr = float(e.get("spread", 0))
            seg = f"{x:.0f}px {y:.0f}px {rad:.0f}px {spr:.0f}px rgba({r}, {g}, {b}, {a:.2f})"
            if t == "INNER_SHADOW":
                seg = "inset " + seg
            shadows.append(seg)
        elif t == "LAYER_BLUR":
            rad = float(e.get("radius", 0))
            if rad > 0:
                filters.append(f"blur({rad:.0f}px)")
        elif t == "BACKGROUND_BLUR":
            rad = float(e.get("radius", 0))
            if rad > 0:
                filters.append(f"blur({rad:.0f}px)")
    decls = []
    if shadows:
        decls.append(f"box-shadow:{', '.join(shadows)}")
    if filters:
        decls.append(f"filter:{' '.join([f for f in filters if f.startswith('blur(')])}")
    return "; ".join(decls) if decls else None


def autolayout_decls(node):
    out = []
    mode = (node.get("layoutMode") or "NONE").upper()
    if mode in ("HORIZONTAL", "VERTICAL"):
        out.append("display:flex")
        out.append("flex-direction:" + ("row" if mode == "HORIZONTAL" else "column"))
    gap = node.get("itemSpacing")
    try:
        if isinstance(gap, (int, float)):
            g = int(round(gap))
            if g < 0:
                g = 0  # clamp negative gaps (CSS gap does not support negatives)
            out.append(f"gap:{g}px")
    except Exception:
        pass
    for k, cssk in (
        ("paddingTop", "padding-top"),
        ("paddingRight", "padding-right"),
        ("paddingBottom", "padding-bottom"),
        ("paddingLeft", "padding-left"),
    ):
        v = node.get(k)
        try:
            if isinstance(v, (int, float)) and v:
                out.append(f"{cssk}:{int(round(v))}px")
        except Exception:
            pass
    # Alternate compact structure: autoLayout: { layoutMode, itemSpacing, padding: {top,right,bottom,left} }
    al = node.get("autoLayout") or {}
    if isinstance(al, dict):
        m = (al.get("layoutMode") or "").upper()
        if m in ("HORIZONTAL", "VERTICAL"):
            if not any(p.startswith("display:") for p in out):
                out.append("display:flex")
            if not any(p.startswith("flex-direction:") for p in out):
                out.append("flex-direction:" + ("row" if m == "HORIZONTAL" else "column"))
        g = al.get("itemSpacing")
        if isinstance(g, (int, float)):
            gg = int(round(g))
            if gg < 0:
                gg = 0
            if not any(p.startswith("gap:") for p in out):
                out.append(f"gap:{gg}px")
        pad = al.get("padding") or {}
        if isinstance(pad, dict):
            for side, cssk in (('top','padding-top'),('right','padding-right'),('bottom','padding-bottom'),('left','padding-left')):
                pv = pad.get(side)
                if isinstance(pv, (int, float)) and pv:
                    if not any(p.startswith(cssk+":") for p in out):
                        out.append(f"{cssk}:{int(round(pv))}px")
        # Align mapping
        def _map_align(v):
            if not v:
                return None
            s = str(v).upper()
            return {"CENTER": "center", "MIN": "flex-start", "MAX": "flex-end"}.get(s)
        pa = _map_align(al.get("primaryAxisAlignItems"))
        ca = _map_align(al.get("counterAxisAlignItems"))
        if m == "HORIZONTAL":
            if pa:
                out.append(f"justify-content:{pa}")
            if ca:
                out.append(f"align-items:{ca}")
        elif m == "VERTICAL":
            if pa:
                out.append(f"justify-content:{pa}")
            if ca:
                out.append(f"align-items:{ca}")
    return out


def text_style_decls(node):
    st = node.get("style") or {}
    out = []
    fs = st.get("fontSize")
    if isinstance(fs, (int, float)):
        out.append(f"font-size:{int(round(fs))}px")
    fw = st.get("fontWeight")
    if isinstance(fw, (int, float)):
        out.append(f"font-weight:{int(round(fw))}")
    lh_px = st.get("lineHeightPx")
    if isinstance(lh_px, (int, float)):
        out.append(f"line-height:{lh_px:.1f}px")
    ls = st.get("letterSpacing")
    if isinstance(ls, (int, float)) and ls:
        out.append(f"letter-spacing:{ls}px")
    td = st.get("textDecoration")
    if td:
        m = {"UNDERLINE": "underline", "STRIKETHROUGH": "line-through", "NONE": "none"}
        v = m.get(str(td).upper())
        if v:
            out.append(f"text-decoration:{v}")
    tc = st.get("textCase")
    if tc:
        m = {"UPPER": "uppercase", "LOWER": "lowercase", "TITLE": "capitalize"}
        v = m.get(str(tc).upper())
        if v:
            out.append(f"text-transform:{v}")
    if st.get("italic") is True or str(st.get("fontStyle", "")).lower() == "italic":
        out.append("font-style:italic")
    ps = st.get("paragraphSpacing")
    if isinstance(ps, (int, float)) and ps:
        out.append(f"margin:0 0 {int(round(ps))}px 0")
    # Alternate: textStyle: { value: {...} }
    ts = node.get("textStyle") or {}
    if isinstance(ts, dict):
        val = ts.get("value") or {}
        if isinstance(val, dict):
            if isinstance(val.get("fontSize"), (int, float)):
                out.append(f"font-size:{int(round(val['fontSize']))}px")
            if isinstance(val.get("fontWeight"), (int, float)):
                out.append(f"font-weight:{int(round(val['fontWeight']))}")
            if isinstance(val.get("lineHeightPx"), (int, float)):
                out.append(f"line-height:{val['lineHeightPx']:.1f}px")
            if isinstance(val.get("letterSpacing"), (int, float)) and val.get("letterSpacing"):
                out.append(f"letter-spacing:{val['letterSpacing']}px")
    return out


class MinimalRenderer:
    def __init__(self, image_mode: str = 'name_only', drop_n: bool = True, flatten: bool = True, strip_text: bool = False, strip_images: bool = False):
        self.rules = []
        self._seq = 0
        # image_mode: off | name_only | aggressive
        self.image_mode = image_mode
        # active section key (BEM block) for alias classes
        self._section_key = 'section'
        self.drop_n = drop_n
        self.flatten = flatten
        self.override_block = None
        self.image_src_override = None
        self._image_override_used = False
        self.strip_text = strip_text
        self.strip_images = strip_images

    def _next_auto_id(self):
        self._seq += 1
        return f"auto-{self._seq:04d}"

    def _pick_node_id(self, node):
        for k in ("id", "node_id", "nodeId", "nid"):
            v = node.get(k)
            if isinstance(v, str) and v.strip():
                return v
        # fallback to name for stability
        nm = node.get("name")
        if isinstance(nm, str) and nm.strip():
            return f"name-{nm}"
        return self._next_auto_id()

    def add_rule(self, selectors, props):
        # selectors: str or list[str]
        if isinstance(selectors, str):
            selectors = [selectors]
        clean = [p.strip() for p in (props or []) if p and ":" in p]
        if not clean:
            return
        d = {}
        for p in clean:
            k = p.split(":", 1)[0].strip().lower()
            d[k] = p
        uniq = []
        seen = set()
        for s in selectors:
            if not s:
                continue
            if s in seen:
                continue
            uniq.append(s)
            seen.add(s)
        if not uniq:
            return
        self.rules.append((uniq, list(d.values())))

    def node_class(self, node):
        nid = self._pick_node_id(node)
        return "n-" + css_safe_identifier(nid)

    def node_box_decls(self, node):
        decls = []
        abb = node.get("absoluteBoundingBox") or {}
        try:
            w = abb.get("width")
            if isinstance(w, (int, float)) and w > 0:
                decls.append(f"width:{int(round(w))}px")
        except Exception:
            pass
        try:
            h = abb.get("height")
            if isinstance(h, (int, float)) and h > 0:
                decls.append(f"height:{int(round(h))}px")
        except Exception:
            pass
        if node.get("clipsContent"):
            decls.append("overflow:hidden")
        bg = rgba_from_solid_fill(node)
        if bg:
            decls.append(f"background-color:{bg}")
        br = stroke_decl_from_node(node)
        if br:
            decls.append(br)
        cr = corner_radius_decl(node)
        if cr:
            decls.append(cr)
        eff = effects_decl(node)
        if eff:
            decls.append(eff)
        bm = node.get("blendMode") or node.get("mixBlendMode")
        if bm:
            decls.append(f"mix-blend-mode:{bm}")
        decls += autolayout_decls(node)
        return decls

    def has_visual_or_layout_signal(self, node) -> bool:
        # Visual: fill/border/radius/effects/clip
        if rgba_from_solid_fill(node):
            return True
        if stroke_decl_from_node(node):
            return True
        if corner_radius_decl(node):
            return True
        if effects_decl(node):
            return True
        if node.get('clipsContent'):
            return True
        # Layout signals that matter even for 1 child (padding/gap)
        al = node.get('autoLayout') or {}
        pad = al.get('padding') or {}
        for k in ('top','right','bottom','left'):
            v = pad.get(k)
            if isinstance(v, (int, float)) and v:
                return True
        gap = al.get('itemSpacing')
        if isinstance(gap, (int, float)) and abs(gap) > 0:
            return True
        return False

    def node_size(self, node):
        abb = node.get("absoluteBoundingBox") or {}
        try:
            w = int(round(float(abb.get("width") or 0)))
        except Exception:
            w = 0
        try:
            h = int(round(float(abb.get("height") or 0)))
        except Exception:
            h = 0
        return max(0, w), max(0, h)

    def is_image_like(self, node, parent=None):
        mode = (self.image_mode or 'off').lower()
        if mode == 'off':
            return False
        # Figma IMAGE fill (native)
        fills = node.get("fills") or []
        if isinstance(fills, list):
            for f in fills:
                if isinstance(f, dict) and str(f.get("type")).upper() == "IMAGE":
                    return True
        nm = (node.get("name") or "").strip().lower()
        if mode == 'aggressive':
            if any(tok in nm for tok in ("image", "img", "picture", "photo", "画像", "写真")):
                return True
            if (node.get("type") or "").upper() in ("RECTANGLE", "FRAME") and node.get("roleHint") == "decoration":
                # Aggressive: treat decorative leaf containers as images
                if not node.get('children'):
                    return True
            return False
        # name_only (default): be strict; only clear image-like names and leaf
        if not nm:
            return False
        # Accept prefixes like: image, img, photo, picture, 画像, 写真
        prefixes = ("image", "img", "photo", "picture", "画像", "写真")
        is_name_image = any(nm == p or nm.startswith(p + ' ') for p in prefixes)
        if not is_name_image:
            return False
        # Leaf only
        if node.get('children'):
            return False
        # Optional: if parent provided and is HORIZONTAL 2-col, prefer this case
        if parent:
            ch = parent.get('children') or []
            if len(ch) == 2:
                pm = (parent.get('autoLayout', {}).get('layoutMode') or parent.get('layoutMode') or '').upper()
                if pm == 'HORIZONTAL':
                    return True
        return True

    def image_placeholder(self, node):
        w, h = self.node_size(node)
        if w <= 0 or h <= 0:
            w, h = 300, 200
        label = (node.get("name") or "IMG").strip()
        safe = re.sub(r"[^a-zA-Z0-9ぁ-んァ-ヶ一-龠ー_\-]+", " ", label)[:20]
        return f"https://via.placeholder.com/{w}x{h}/dddddd/888888?text={escape(safe)}", w, h

    # -------------------- Semantic / alias helpers --------------------
    def _safe_alias(self, name: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9_-]+", "-", (name or '').strip().lower())
        return s.strip('-') or 'node'

    def set_section_key(self, key: str | None):
        if key:
            self._section_key = self._safe_alias(key)
        else:
            self._section_key = 'section'

    def is_heading_text(self, node) -> bool:
        ts = (node.get('textStyle') or {}).get('value') or {}
        try:
            fs = float(ts.get('fontSize') or 0)
            fw = int(ts.get('fontWeight') or 0)
        except Exception:
            fs, fw = 0, 0
        return (fw >= 600 and fs >= 18)

    def semantic_alias_for_node(self, node, parent=None, depth=0) -> list[str]:
        aliases = []
        sk = self.override_block or self._section_key
        t = (node.get('type') or '').upper()
        # Root section block for the first content frame under root
        if depth == 1 and t == 'FRAME':
            aliases.append(sk)
        # Two-col media/content under horizontal parent
        if parent:
            ch = parent.get('children') or []
            pm = (parent.get('autoLayout', {}).get('layoutMode') or parent.get('layoutMode') or '').upper()
            if pm == 'HORIZONTAL' and len(ch) == 2:
                if self.is_image_like(node, parent=parent):
                    aliases.append(f"{sk}__image")
                else:
                    aliases.append(f"{sk}__content")
        # Text specifics
        if t == 'TEXT':
            if self.is_heading_text(node):
                aliases.append(f"{sk}__headline")
            else:
                aliases.append(f"{sk}__text")
        # Decorative rectangle
        if t == 'RECTANGLE' and (node.get('roleHint') == 'decoration'):
            aliases.append(f"{sk}__bg")
        # De-dup
        out = []
        seen = set()
        for a in aliases:
            a = self._safe_alias(a)
            if a and a not in seen:
                out.append(a)
                seen.add(a)
        return out

    def image_placeholder(self, node):
        w, h = self.node_size(node)
        if w <= 0 or h <= 0:
            w, h = 300, 200
        if self.image_src_override and not self._image_override_used:
            self._image_override_used = True
            return self.image_src_override, 0, 0
        label = (node.get("name") or "IMG").strip()
        safe = re.sub(r"[^a-zA-Z0-9ぁ-んァ-ヶ一-龠ー_\-]+", " ", label)[:20]
        return f"https://via.placeholder.com/{w}x{h}/dddddd/888888?text={escape(safe)}", w, h

    def _collect_phrases(self, node):
        out = []
        children = node.get('children') or []
        for ch in children:
            if not isinstance(ch, dict):
                continue
            if (ch.get('type') or '').upper() != 'FRAME':
                continue
            bg = None
            txt = None
            tstyle = None
            for gc in ch.get('children') or []:
                if (gc.get('type') or '').upper() == 'RECTANGLE':
                    col = rgba_from_solid_fill(gc)
                    if col:
                        bg = col
                elif (gc.get('type') or '').upper() == 'TEXT':
                    txt = gc.get('characters') or gc.get('name') or ''
                    tstyle = text_style_decls(gc)
            if bg and txt:
                out.append((bg, txt, tstyle or []))
        return out

    def render_node(self, node, parent=None, depth=0):
        if not isinstance(node, dict) or node.get("visible") is False:
            return ""
        t = (node.get("type") or "").upper()
        cls = self.node_class(node)
        aliases = self.semantic_alias_for_node(node, parent=parent, depth=depth)
        alias_selectors = ["." + a for a in aliases]
        # Flatten shallow wrappers: single child, no visual/layout signals, not text/image
        if self.flatten:
            children = node.get('children') or []
            if (t not in ('TEXT',) and not self.is_image_like(node, parent=parent)
                and len(children) == 1 and not self.has_visual_or_layout_signal(node)):
                # bypass wrapper
                return self.render_node(children[0], parent=parent, depth=depth)
        if t == "TEXT":
            props = text_style_decls(node)
            col = rgba_from_solid_fill(node)
            if col:
                props.append(f"color:{col}")
            sel = (alias_selectors or (["." + cls] if not self.drop_n else []))
            self.add_rule(sel, props)
            text = node.get("characters")
            if text is None:
                text = node.get("name") or ""
            if self.strip_text:
                text = ""
            # Pick semantic tag
            tag = 'h2' if self.is_heading_text(node) else 'p'
            class_tokens = aliases[:] if aliases else []
            if not self.drop_n:
                class_tokens.append(cls)
            if not class_tokens:
                # fallback alias when dropping n- with no semantic
                class_tokens = [self._safe_alias((node.get('name') or 'item'))]
            class_attr = " ".join(class_tokens)
            return f"<{tag} class=\"{class_attr}\">{escape(str(text))}</{tag}>\n"
        # Container/shape
        props = self.node_box_decls(node)
        sel = (alias_selectors or (["." + cls] if not self.drop_n else []))
        self.add_rule(sel, props)
        children_html = []
        # Heuristic: HORIZONTAL two-col with image-like + text container
        children = node.get("children") or []
        child_classes = [self.node_class(c) for c in children]
        mode = (node.get("autoLayout", {}).get("layoutMode") or node.get("layoutMode") or "").upper()
        if mode == "HORIZONTAL" and len(children) == 2:
            idx_img = 0 if self.is_image_like(children[0], parent=node) else (1 if self.is_image_like(children[1], parent=node) else -1)
            if idx_img != -1:
                idx_txt = 1 - idx_img
                img_cls = child_classes[idx_img]
                txt_cls = child_classes[idx_txt]
                # Also alias selectors
                img_alias = self.semantic_alias_for_node(children[idx_img], parent=node, depth=depth+1)
                txt_alias = self.semantic_alias_for_node(children[idx_txt], parent=node, depth=depth+1)
                img_sel = (["." + a for a in img_alias] or (["." + img_cls] if not self.drop_n else []))
                txt_sel = (["." + a for a in txt_alias] or (["." + txt_cls] if not self.drop_n else []))
                # 40/60 split baseline
                self.add_rule(img_sel, ["flex:0 0 40%", "max-width:40%"])
                self.add_rule(txt_sel, ["flex:1 1 0", "min-width:0"]) 
        # Phrase grouping: for vertical containers, group frames with rectangle+text
        phrase_html = ""
        if mode == "VERTICAL":
            phrases = self._collect_phrases(node)
            if len(phrases) >= 1:
                sk = self.override_block or self._section_key
                phrases_cls = f"{sk}__phrases"
                phrase_cls = f"{sk}__phrase"
                bg_cls = f"{sk}__bg"
                text_cls = f"{sk}__text"
                # phrase container rules
                self.add_rule("." + phrases_cls, ["display:flex", "flex-direction:column", "gap:6px"])
                # per phrase rules
                self.add_rule("." + phrase_cls, ["position:relative", "display:flex", "flex-direction:column", "align-items:center", "text-align:center"])
                self.add_rule("." + bg_cls, ["width:100%", "height:40px", "position:absolute", "top:50%", "left:0", "transform:translateY(-50%)", "z-index:0"])
                self.add_rule("." + text_cls, ["position:relative", "z-index:1", "margin:0"])
                rows = []
                for (bg, txt, tstyle) in phrases:
                    # background color per row
                    self.add_rule("." + bg_cls, [f"background-color:{bg}"])
                    # font props per row (merged)
                    font_props = [p for p in tstyle if p.startswith(('font-size', 'font-weight', 'line-height'))]
                    if font_props:
                        self.add_rule("." + text_cls, font_props)
                    txt_out = "" if self.strip_text else escape(str(txt))
                    rows.append(f"<div class=\"{phrase_cls}\">\n  <div class=\"{bg_cls}\"></div>\n  <p class=\"{text_cls}\">{txt_out}</p>\n</div>\n")
                phrase_html = f"<div class=\"{phrases_cls}\">\n{''.join(rows)}</div>\n"
        # If image-like, embed an <img> placeholder (or future local mapping)
        if self.is_image_like(node, parent=parent) and not self.strip_images:
            src, w, h = self.image_placeholder(node)
            wh_attr = (f" width=\"{w}\" height=\"{h}\"") if (w and h) else ""
            children_html.append(f"<img class=\"img-cover\" src=\"{src}\" alt=\"{escape(node.get('name') or 'image')}\"{wh_attr} />\n")
        for c in children:
            # Skip child frames already grouped into phrases
            if phrase_html and isinstance(c, dict) and (c.get('type') or '').upper() == 'FRAME':
                continue
            children_html.append(self.render_node(c, parent=node, depth=depth+1))
        if phrase_html:
            children_html.append(phrase_html)
        inner = "".join(children_html)
        # Pick tag: top-level content frame -> section; others -> div
        tag = 'section' if (depth == 1 and t == 'FRAME') else 'div'
        class_tokens = aliases[:] if aliases else []
        if not self.drop_n:
            class_tokens.append(cls)
        if not class_tokens:
            class_tokens = [self._safe_alias((node.get('name') or 'item'))]
        class_attr = " ".join(class_tokens)
        return f"<{tag} class=\"{class_attr}\">\n{inner}</{tag}>\n"

    def render(self, roots):
        html_parts = []
        for r in roots:
            # Set section key from root frame name if available
            sec_key = (r.get('name') or 'section') if isinstance(r, dict) else 'section'
            self.set_section_key(sec_key)
            html_parts.append(self.render_node(r, parent=None, depth=0))
        html = "".join(html_parts)
        css = self.build_css()
        return html, css

    def build_css(self):
        out = [
            "*{box-sizing:border-box}",
            "img{max-width:100%;height:auto;display:block}",
            ".img-cover{width:100%;height:100%;object-fit:cover;display:block}"
        ]
        for selectors, props in self.rules:
            sel = ", ".join(sorted(selectors))
            out.append(sel + "{\n    " + ";\n    ".join(props) + "\n}")
        return "\n".join(out) + "\n"


def detect_roots(data, frame_id=None):
    if isinstance(data, dict) and isinstance(data.get("requirements"), list):
        return [n for n in data["requirements"] if isinstance(n, dict)]
    if isinstance(data, dict) and isinstance(data.get("frame"), dict):
        return [data["frame"]]
    # full file JSON fallback
    if isinstance(data, dict) and isinstance(data.get("document"), dict):
        if not frame_id:
            raise SystemExit("This looks like a full Figma file JSON; pass --frame-id to pick a frame")
        def find(node, target):
            if not isinstance(node, dict):
                return None
            if node.get("id") == target:
                return node
            for ch in node.get("children", []) or []:
                res = find(ch, target)
                if res:
                    return res
            return None
        fr = find(data["document"], frame_id)
        if not fr:
            raise SystemExit(f"Frame not found: {frame_id}")
        return [fr]
    raise SystemExit("Unsupported JSON shape: expected {requirements:[]}, {frame:{}} or full file JSON with --frame-id")


def guess_project_name(data, fallback="Project"):
    for k in ("source_file_name", "name", "project_name"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return re.sub(r"[/\\:*?\"<>|]", "_", v.strip())
    return fallback


def main():
    ap = argparse.ArgumentParser(description="Minimal Figma JSON to HTML/CSS (preserve nesting; n-* classes)")
    ap.add_argument("--json", required=True, help="Path to JSON")
    ap.add_argument("--out", default="dist/minimal", help="Output directory")
    ap.add_argument("--frame-id", help="When passing a full file JSON, specify target frame id (e.g., 1:2)")
    ap.add_argument("--debug-outline", action="store_true", help="Append outline to all .n-* to verify class application")
    ap.add_argument("--image-mode", choices=["off","name_only","aggressive"], default="name_only", help="Placeholder image insertion policy")
    ap.add_argument("--inline-css", action="store_true", help="Embed CSS into HTML (single file output)")
    ap.add_argument("--block", help="Override section block name (e.g., c-staff-education)")
    ap.add_argument("--image-src", help="Override first image src for the section (e.g., path/to/image.jpg)")
    ap.add_argument("--strip-text", action="store_true", help="Remove text contents from TEXT nodes and phrases")
    ap.add_argument("--strip-images", action="store_true", help="Do not emit <img> tags (keep image containers only)")
    args = ap.parse_args()

    with open(args.json, "r", encoding="utf-8") as f:
        data = json.load(f)
    roots = detect_roots(data, frame_id=args.frame_id)
    renderer = MinimalRenderer(image_mode=args.image_mode, drop_n=True, flatten=True, strip_text=args.strip_text, strip_images=args.strip_images)
    if args.block:
        renderer.override_block = re.sub(r"[^a-zA-Z0-9_-]+", "-", args.block.strip().lower())
    if args.image_src:
        renderer.image_src_override = args.image_src
    html_body, css = renderer.render(roots)
    if args.debug_outline:
        css += "\n/* debug outline */\n[class^=\"n-\"], [class*=\" n-\"]{outline:1px solid rgba(0,0,0,.2)}\n"

    proj = guess_project_name(data)
    outdir = os.path.join(args.out, proj)
    os.makedirs(outdir, exist_ok=True)
    if args.inline_css:
        html = (
            "<!doctype html>\n"
            "<html lang=\"ja\">\n"
            "  <head>\n"
            "    <meta charset=\"utf-8\" />\n"
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
            f"    <title>{escape(proj)}</title>\n"
            "    <style>\n" + css + "    </style>\n"
            "  </head>\n"
            "  <body>\n"
            + html_body +
            "  </body>\n"
            "</html>\n"
        )
    else:
        html = (
            "<!doctype html>\n"
            "<html lang=\"ja\">\n"
            "  <head>\n"
            "    <meta charset=\"utf-8\" />\n"
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
            f"    <title>{escape(proj)}</title>\n"
            "    <link rel=\"stylesheet\" href=\"./style.css\" />\n"
            "  </head>\n"
            "  <body>\n"
            + html_body +
            "  </body>\n"
            "</html>\n"
        )
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    if not args.inline_css:
        with open(os.path.join(outdir, "style.css"), "w", encoding="utf-8") as f:
            f.write(css)
        print(f"[OK] Wrote {os.path.join(outdir, 'index.html')} and style.css")
    else:
        print(f"[OK] Wrote single HTML with inline CSS: {os.path.join(outdir, 'index.html')}")


if __name__ == "__main__":
    main()

import os
import requests
from dotenv import load_dotenv
import json
import re
from html import escape
from urllib.parse import urlparse, parse_qs, unquote

# ---------------- 環境変数読み込み ----------------
load_dotenv()

FIGMA_API_TOKEN = os.getenv("FIGMA_API_TOKEN")
FILE_KEY = os.getenv("FILE_KEY")
FRAME_NODE_ID = os.getenv("FRAME_NODE_ID")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "figma_layout")
SP_FRAME_NODE_ID = os.getenv("SP_FRAME_NODE_ID", None)  # SP版フレームID（オプション）
SAVE_RAW_DATA = os.getenv("SAVE_RAW_DATA", "false").lower() == "true"  # JSONバックアップの有効/無効
IMAGE_FORMAT = os.getenv("IMAGE_FORMAT", "png").lower()
IMAGE_SCALE = float(os.getenv("IMAGE_SCALE", "1"))
DOWNLOAD_IMAGES = os.getenv("DOWNLOAD_IMAGES", "true").lower() == "true"
USE_IMAGES = os.getenv("USE_IMAGES", "false").lower() == "true"
EXCLUDE_LAYER_NAMES = [s.strip().lower() for s in os.getenv("EXCLUDE_LAYER_NAMES", "").split(",") if s.strip()]
EXCLUDE_LAYER_IDS = {s.strip() for s in os.getenv("EXCLUDE_LAYER_IDS", "").split(",") if s.strip()}
EXCLUDE_HEADER_FOOTER = os.getenv("EXCLUDE_HEADER_FOOTER", "true").lower() == "true"
FORCE_IMAGE_REDOWNLOAD = os.getenv("FORCE_IMAGE_REDOWNLOAD", "false").lower() == "true"
PC_STRICT_CLAMP = os.getenv("PC_STRICT_CLAMP", "false").lower() == "true"
IMAGE_CONTAINER_SUPPRESS_LEAFS = os.getenv("IMAGE_CONTAINER_SUPPRESS_LEAFS", "true").lower() == "true"
try:
    SUPPRESS_IMAGE_OVERLAP_THRESHOLD = float(os.getenv("SUPPRESS_IMAGE_OVERLAP_THRESHOLD", "0.8"))
except Exception:
    SUPPRESS_IMAGE_OVERLAP_THRESHOLD = 0.8

# Include-like (shared/partial) exclusion settings
EXCLUDE_INCLUDES = os.getenv("EXCLUDE_INCLUDES", "true").lower() == "true"
INCLUDE_SCOPE = os.getenv("INCLUDE_SCOPE", "root_only").lower()  # root_only|all
INCLUDE_DRY_RUN = os.getenv("INCLUDE_DRY_RUN", "true").lower() == "true"
INCLUDE_MIN_REUSE_COUNT = int(os.getenv("INCLUDE_MIN_REUSE_COUNT", "3"))
INCLUDE_TOP_MARGIN = float(os.getenv("INCLUDE_TOP_MARGIN", "120"))
INCLUDE_BOTTOM_MARGIN = float(os.getenv("INCLUDE_BOTTOM_MARGIN", "160"))
INCLUDE_MIN_WIDTH_RATIO = float(os.getenv("INCLUDE_MIN_WIDTH_RATIO", "0.9"))
INCLUDE_SCORE_THRESHOLD = float(os.getenv("INCLUDE_SCORE_THRESHOLD", "3.5"))
INCLUDE_KEYWORDS = [s.strip().lower() for s in os.getenv(
    "INCLUDE_KEYWORDS",
    "include,inc,partial,shared,common,global,template,layout,base,nav,header,footer,breadcrumb"
).split(",") if s.strip()]
INCLUDE_DENYLIST_IDS = {s.strip() for s in os.getenv("INCLUDE_DENYLIST_IDS", "").split(",") if s.strip()}
INCLUDE_ALLOWLIST_IDS = {s.strip() for s in os.getenv("INCLUDE_ALLOWLIST_IDS", "").split(",") if s.strip()}

# Reuse maps built from whole file
REUSE_COMPONENT_COUNT = {}

# Utility class generation cache
UTILITY_CLASS_CACHE = {}

def generate_utility_class_name(property_type, value, direction=""):
    """役割別のユーティリティクラス名を生成"""
    try:
        # キャッシュキーを生成
        cache_key = f"{property_type}:{value}:{direction}"
        if cache_key in UTILITY_CLASS_CACHE:
            return UTILITY_CLASS_CACHE[cache_key]

        result = None

        # サイズ系 (Width/Height)
        if property_type in ['width', 'height', 'min-width', 'max-width', 'min-height', 'max-height']:
            prefix_map = {
                'width': 'w',
                'height': 'h',
                'min-width': 'min-w',
                'max-width': 'max-w',
                'min-height': 'min-h',
                'max-height': 'max-h'
            }
            prefix = prefix_map[property_type]

            if value == '100%':
                result = f"{prefix}-full"
            elif value == 'auto':
                result = f"{prefix}-auto"
            elif value.endswith('%'):
                result = f"{prefix}__{value.replace('%', 'p')}"
            elif value.endswith('px'):
                result = f"{prefix}__{value.replace('px', '')}"
            elif value.endswith('vh'):
                result = f"{prefix}__{value.replace('vh', 'vh')}"
            elif value.endswith('vw'):
                result = f"{prefix}__{value.replace('vw', 'vw')}"
            else:
                result = f"{prefix}__{value}"

        # スペーシング系 (Margin/Padding)
        elif property_type.startswith(('margin', 'padding')):
            is_margin = property_type.startswith('margin')
            prefix = 'm' if is_margin else 'p'

            # 方向指定
            if direction:
                direction_map = {
                    'top': 't', 'bottom': 'b', 'left': 'l', 'right': 'r'
                }
                if direction in direction_map:
                    prefix += direction_map[direction]
                elif direction == 'horizontal':
                    prefix += 'x'
                elif direction == 'vertical':
                    prefix += 'y'

            if value == '0':
                result = f"{prefix}-0"
            elif value == 'auto':
                result = f"{prefix}-auto"
            elif value.endswith('px'):
                result = f"{prefix}__{value.replace('px', '')}"
            else:
                result = f"{prefix}__{value}"

        # Display系
        elif property_type == 'display':
            display_map = {
                'flex': 'd-flex',
                'block': 'd-block',
                'inline': 'd-inline',
                'inline-block': 'd-inline-block',
                'grid': 'd-grid',
                'none': 'd-none'
            }
            result = display_map.get(value, f"d-{value}")

        # Flexbox系
        elif property_type == 'flex-direction':
            result = f"flex-{'row' if value == 'row' else 'col'}"
        elif property_type == 'justify-content':
            justify_map = {
                'flex-start': 'justify-start',
                'flex-end': 'justify-end',
                'center': 'justify-center',
                'space-between': 'justify-between',
                'space-around': 'justify-around'
            }
            result = justify_map.get(value, f"justify-{value}")
        elif property_type == 'align-items':
            align_map = {
                'flex-start': 'align-start',
                'flex-end': 'align-end',
                'center': 'align-center',
                'stretch': 'align-stretch'
            }
            result = align_map.get(value, f"align-{value}")
        elif property_type == 'flex-wrap':
            result = 'flex-wrap' if value == 'wrap' else 'flex-nowrap'

        # 背景色系
        elif property_type == 'background-color':
            if value == 'transparent':
                result = 'bg-transparent'
            elif value.startswith('#'):
                result = f"bg__{value[1:]}"  # #を除去
            elif value.startswith('rgba'):
                # rgba(255,255,255,1.00) -> bg__fff_100
                import re
                rgba_match = re.match(r'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)', value)
                if rgba_match:
                    r, g, b, a = rgba_match.groups()
                    hex_color = f"{int(r):02x}{int(g):02x}{int(b):02x}"
                    alpha = int(float(a) * 100)
                    result = f"bg__{hex_color}_{alpha}"
                else:
                    result = f"bg__{value.replace('(', '_').replace(')', '').replace(',', '_').replace(' ', '')}"
            else:
                result = f"bg-{value}"

        # フォントサイズ系
        elif property_type == 'font-size':
            if value.endswith('px'):
                result = f"text__{value.replace('px', '')}"
            elif value.endswith('rem'):
                result = f"text__{value.replace('rem', 'rem')}"
            else:
                result = f"text__{value}"

        # フォントウェイト系
        elif property_type == 'font-weight':
            weight_map = {
                'normal': 'fw-normal',
                'bold': 'fw-bold',
                '100': 'fw-thin',
                '300': 'fw-light',
                '400': 'fw-normal',
                '500': 'fw-medium',
                '600': 'fw-semibold',
                '700': 'fw-bold',
                '900': 'fw-black'
            }
            result = weight_map.get(str(value), f"fw__{value}")

        # テキスト整列
        elif property_type == 'text-align':
            result = f"text-{value}"

        # ボーダー系
        elif property_type == 'border-radius':
            if value == '0':
                result = 'rounded-none'
            elif value.endswith('px'):
                px_val = value.replace('px', '')
                if px_val == '50' or value == '50%':
                    result = 'rounded-full'
                else:
                    result = f"rounded__{px_val}"
            else:
                result = f"rounded__{value}"

        # ポジション系
        elif property_type == 'position':
            result = f"pos-{value}"

        # z-index系
        elif property_type == 'z-index':
            result = f"z__{value}"

        # overflow系
        elif property_type == 'overflow':
            result = f"overflow-{value}"

        # デフォルト
        if not result:
            safe_property = property_type.replace('-', '_')
            safe_value = str(value).replace('-', '_').replace('px', '').replace('%', 'p')
            result = f"util__{safe_property}__{safe_value}"

        # キャッシュに保存
        UTILITY_CLASS_CACHE[cache_key] = result
        return result

    except Exception:
        return f"util__{property_type.replace('-', '_')}__{str(value).replace('-', '_')}"

def detect_image_text_pattern(element):
    """画像とテキストの配置パターンを検出"""
    children = element.get("children", []) or []
    if len(children) < 2:
        return None

    # 子要素を位置でソート（X座標順）
    child_positions = []
    for child in children:
        if should_exclude_node(child):
            continue
        bounds = child.get("absoluteBoundingBox", {}) or {}
        child_positions.append({
            "element": child,
            "x": bounds.get("x", 0),
            "y": bounds.get("y", 0),
            "width": bounds.get("width", 0),
            "height": bounds.get("height", 0),
            "type": child.get("type", ""),
            "name": child.get("name", "")
        })

    if len(child_positions) < 2:
        return None

    # X座標でソート
    child_positions.sort(key=lambda c: c["x"])

    # 画像要素とテキスト要素を識別
    def is_image_element(child_info):
        element_type = child_info["type"]
        name = child_info["name"].lower()
        # 画像タイプ、またはrectangleで画像っぽい名前
        return (element_type in ["RECTANGLE", "FRAME"] and
                any(img_keyword in name for img_keyword in ["image", "img", "picture", "photo", "rectangle"]))

    def is_text_container(child_info):
        element_type = child_info["type"]
        name = child_info["name"].lower()
        # テキスト要素、またはFrameでテキストが含まれていそうな名前
        if element_type == "TEXT":
            return True
        if element_type == "FRAME":
            # フレーム内にテキストがあるかチェック
            children = child_info["element"].get("children", [])
            return any(c.get("type") == "TEXT" for c in children)
        return False

    # パターン検出
    first_child = child_positions[0]
    second_child = child_positions[1] if len(child_positions) > 1 else None

    if not second_child:
        return None

    # 横並びかチェック（Y座標の重なり）
    y_overlap_ratio = calculate_y_overlap(first_child, second_child)
    if y_overlap_ratio < 0.5:  # 横並びではない
        return None

    # 画像 + テキストパターン
    if is_image_element(first_child) and is_text_container(second_child):
        return "image-text"
    # テキスト + 画像パターン
    elif is_text_container(first_child) and is_image_element(second_child):
        return "text-image"

    return None

def calculate_y_overlap(child1, child2):
    """2つの要素のY軸重なり率を計算"""
    top = max(child1["y"], child2["y"])
    bottom = min(child1["y"] + child1["height"], child2["y"] + child2["height"])
    overlap = max(0, bottom - top)
    min_height = min(child1["height"], child2["height"])
    return overlap / max(1, min_height)

def generate_utility_classes_for_element(element):
    """要素から適用可能なユーティリティクラスを生成"""
    utility_classes = []

    try:
        # レイアウト情報の解析
        layout_info = analyze_layout_structure(element)

        # Display - check for Auto Layout and content patterns
        layout_mode = layout_info.get("layout_mode")

        # Special handling for image-text patterns
        content_pattern = detect_image_text_pattern(element)
        if content_pattern in ["image-text", "text-image"]:
            utility_classes.append("d-flex")
            utility_classes.append("flex-row")
            utility_classes.append("align-start")  # Align items to top
            utility_classes.append("gap-40")  # Standard gap for image-text layouts
            if content_pattern == "image-text":
                utility_classes.append("image-text-layout")
            else:
                utility_classes.append("text-image-layout")
        elif layout_mode == "HORIZONTAL":
            utility_classes.append("d-flex")
            utility_classes.append("flex-row")
        elif layout_mode == "VERTICAL":
            utility_classes.append("d-flex")
            utility_classes.append("flex-col")

        # Justify content
        if layout_info.get("justify"):
            justify_class = generate_utility_class_name("justify-content", layout_info["justify"])
            utility_classes.append(justify_class)

        # Align items
        if layout_info.get("align"):
            align_class = generate_utility_class_name("align-items", layout_info["align"])
            utility_classes.append(align_class)

        # Gap
        if layout_info.get("gap"):
            gap_value = str(layout_info["gap"])
            if gap_value != "0":
                utility_classes.append(f"gap__{gap_value}")

        # Padding (Auto Layout padding)
        padding = element.get("paddingLeft") or element.get("paddingTop") or element.get("paddingRight") or element.get("paddingBottom")
        if padding and padding > 0:
            utility_classes.append(f"p__{int(padding)}")

        # Border radius (cornerRadius)
        corner_radius = element.get("cornerRadius")
        if corner_radius and corner_radius > 0:
            utility_classes.append(f"rounded__{int(corner_radius)}")

        # サイズ情報
        bounds = element.get("absoluteBoundingBox", {})
        if bounds:
            width = bounds.get("width")
            height = bounds.get("height")

            if width:
                width_class = generate_utility_class_name("width", f"{width}px")
                utility_classes.append(width_class)

            if height:
                height_class = generate_utility_class_name("height", f"{height}px")
                utility_classes.append(height_class)

        # 背景色
        rgba = _pick_solid_fill_rgba(element)
        if rgba and rgba != "rgba(255, 255, 255, 1.00)":
            bg_class = generate_utility_class_name("background-color", rgba)
            utility_classes.append(bg_class)

        # パディング情報 (TODO: implement _analyze_container_styles or alternative)
        # import re
        # layout_style = _analyze_container_styles(element)
        # for prop in layout_style:
        #     if prop.startswith("padding:"):
        #         # padding: 16px -> p__16
        #         padding_match = re.match(r'padding:\s*(\d+)px', prop)
        #         if padding_match:
        #             padding_value = padding_match.group(1)
        #             padding_class = generate_utility_class_name("padding", f"{padding_value}px")
        #             utility_classes.append(padding_class)
        #         break

        # ボーダー半径 (TODO: implement _analyze_container_styles or alternative)
        # for prop in layout_style:
        #     if prop.startswith("border-radius:"):
        #         radius_match = re.match(r'border-radius:\s*(\d+)px', prop)
        #         if radius_match:
        #             radius_value = radius_match.group(1)
        #             radius_class = generate_utility_class_name("border-radius", f"{radius_value}px")
        #             utility_classes.append(radius_class)
        #         break

        # エフェクト（シャドウなど）
        effects_css = extract_effects_styles(element)
        if effects_css and "box-shadow" in effects_css:
            utility_classes.append("shadow")

        return utility_classes

    except Exception as e:
        return []
REUSE_NAME_COUNT = {}
INCLUDE_CANDIDATES = []
CURRENT_FRAME_NAME = ""

# Optional: URLs to auto-fill keys/ids
PC_FIGMA_URL = os.getenv("PC_FIGMA_URL") or os.getenv("FIGMA_URL")
SP_FIGMA_URL = os.getenv("SP_FIGMA_URL")
# File suffixes for PC/SP outputs
PC_SUFFIX = os.getenv("PC_SUFFIX", "-pc")
SP_SUFFIX = os.getenv("SP_SUFFIX", "-sp")
SINGLE_HTML = os.getenv("SINGLE_HTML", "true").lower() == "true"  # keep combined output
SINGLE_HTML_ONLY = os.getenv("SINGLE_HTML_ONLY", "true").lower() == "true"  # skip per-frame files

# Offline/Local input options
# - INPUT_JSON_FILE: PC用のローカルJSONを指定するとAPIを叩かずに解析
# - SP_INPUT_JSON_FILE: SP用のローカルJSON
# - OFFLINE_MODE=true: すべてのHTTPアクセスを抑止（画像URL取得/ダウンロードも行わない）
# - IMAGE_SOURCE: auto|local  localの場合はローカル画像のみを参照
INPUT_JSON_FILE = os.getenv("INPUT_JSON_FILE")
SP_INPUT_JSON_FILE = os.getenv("SP_INPUT_JSON_FILE")
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() == "true"
IMAGE_SOURCE = os.getenv("IMAGE_SOURCE", "auto").lower()
USE_LOCAL_IMAGES_ONLY = OFFLINE_MODE or (IMAGE_SOURCE == "local")

# Style scoping for node-specific (.n-*) rules
# conservative: safest; block cascading color on non-text; allow essential layout/visuals
# standard: block cascading color on non-text; otherwise allow
# aggressive: allow all collected props
NODE_STYLE_SCOPE = (os.getenv("NODE_STYLE_SCOPE", "conservative") or "conservative").lower()
SUPPRESS_CONTAINER_WIDTH = (os.getenv("SUPPRESS_CONTAINER_WIDTH", "true").lower() == "true")
SUPPRESS_FIXED_HEIGHT = (os.getenv("SUPPRESS_FIXED_HEIGHT", "true").lower() == "true")
USE_ASPECT_RATIO = (os.getenv("USE_ASPECT_RATIO", "true").lower() == "true")

# Heading policy
# single_h1: ページ全体でh1は1つまで（既定）
# per_section: セクション内はh2/h3ベース。h1は先頭セクションのみ許可（環境で切替）
# figma: 既存ロジックそのまま
HEADING_STRATEGY = (os.getenv("HEADING_STRATEGY", "single_h1") or "single_h1").lower()
ALLOW_H1_IN_FIRST_SECTION = (os.getenv("ALLOW_H1_IN_FIRST_SECTION", "true").lower() == "true")
SECTION_HEADING_BASE = int(os.getenv("SECTION_HEADING_BASE", "2") or 2)  # per_section時の基準レベル

# Section wrapper simplification
# full (default): section > .container > .inner
# compact:        section > .content-width-container (no .inner)
# minimal:        <section class="... content-width-container"> children ... </section>
SECTION_WRAPPER_MODE = (os.getenv("SECTION_WRAPPER_MODE", "compact") or "compact").lower()

# Flattening (conservative): remove shallow wrappers with no visual/layout role
FLATTEN_SHALLOW_WRAPPERS = (os.getenv("FLATTEN_SHALLOW_WRAPPERS", "false").lower() == "true")
PRUNE_UNUSED_CSS = (os.getenv("PRUNE_UNUSED_CSS", "false").lower() == "true")

# N-class aliasing (map .n-<id> styles to human-friendly classes safely)
# off (default):   何もしない
# add:             一意な別名クラスをHTMLに併記し、CSSセレクタを連結（.n-xxx, .alias { … }）
N_CLASS_ALIAS_MODE = (os.getenv("N_CLASS_ALIAS_MODE", "off") or "off").lower()
N_CLASS_ALIAS_SOURCE = (os.getenv("N_CLASS_ALIAS_SOURCE", "semantic") or "semantic").lower()  # semantic|safe-name
N_CLASS_ALIAS_NAMESPACE = (os.getenv("N_CLASS_ALIAS_NAMESPACE", "section") or "section").lower()  # none|section
N_CLASS_ALIAS_STYLE = (os.getenv("N_CLASS_ALIAS_STYLE", "bem") or "bem").lower()  # bem|flat
N_CLASS_ALIAS_DEDUP = (os.getenv("N_CLASS_ALIAS_DEDUP", "section_index") or "section_index").lower()  # none|section_index
N_CLASS_ALIAS_UNIQUE_ONLY = (os.getenv("N_CLASS_ALIAS_UNIQUE_ONLY", "true").lower() == "true")
N_CLASS_ALIAS_DROP_N_UNIQUE = (os.getenv("N_CLASS_ALIAS_DROP_N_UNIQUE", "false").lower() == "true")
N_CLASS_ALIAS_TOKEN_FILTER = (os.getenv("N_CLASS_ALIAS_TOKEN_FILTER", "none") or "none").lower()  # none|aggressive

# Semantic class output mode
# all:            レイヤー名ベースのセマンティッククラスを全要素に付与（従来）
# sections_only:  セクションタグにのみ付与（デフォルト）。内部要素は付与しない
# none:           どこにも付与しない（汎用クラス/レイアウト/ノード固有のみ）
SEMANTIC_CLASS_MODE = (os.getenv("SEMANTIC_CLASS_MODE", "sections_only") or "sections_only").lower()

# Horizontal padding normalization
HPAD_MODE = (os.getenv("HPAD_MODE", "none") or "none").lower()  # none|trim|clamp
HPAD_TRIM_MIN_PX = int(os.getenv("HPAD_TRIM_MIN_PX", "100") or 100)
HPAD_SYMM_TOL_PX = int(os.getenv("HPAD_SYMM_TOL_PX", "16") or 16)
HPAD_CLAMP_MIN_PX = int(os.getenv("HPAD_CLAMP_MIN_PX", "16") or 16)
HPAD_CLAMP_VW = float(os.getenv("HPAD_CLAMP_VW", "5") or 5.0)  # -> e.g., 5vw
HPAD_SCOPE = (os.getenv("HPAD_SCOPE", "wrapper_only") or "wrapper_only").lower()  # none|all|wrapper_only
try:
    HPAD_WRAPPER_MIN_WIDTH_RATIO = float(os.getenv("HPAD_WRAPPER_MIN_WIDTH_RATIO", "0.9") or 0.9)
except Exception:
    HPAD_WRAPPER_MIN_WIDTH_RATIO = 0.9

# Text-exact exclusion tokens (comma-separated). If a TEXT node's content exactly matches
# one of these tokens (after simple normalization), that TEXT node is excluded.
EXCLUDE_TEXT_EXACT = [s.strip() for s in (os.getenv("EXCLUDE_TEXT_EXACT", "") or "").split(",") if s.strip()]

# Child equalization and 2-col ABB ratio mapping
STOP_CHILD_EQUALIZE = (os.getenv("STOP_CHILD_EQUALIZE", "true").lower() == "true")
USE_ABB_RATIO_2COL = (os.getenv("USE_ABB_RATIO_2COL", "true").lower() == "true")
USE_AL_RATIO_2COL = (os.getenv("USE_AL_RATIO_2COL", "true").lower() == "true")

# Margin inference between siblings (non Auto Layout parents)
INFER_SIBLING_MARGINS = (os.getenv("INFER_SIBLING_MARGINS", "true").lower() == "true")
try:
    MARGIN_INFER_MIN_PX = int(os.getenv("MARGIN_INFER_MIN_PX", "4") or 4)
    MARGIN_INFER_MAX_PX = int(os.getenv("MARGIN_INFER_MAX_PX", "240") or 240)
except Exception:
    MARGIN_INFER_MIN_PX = 4
    MARGIN_INFER_MAX_PX = 240

# Fullbleed inner wrapper policy for image-fill containers: content|none
BG_FULLBLEED_INNER = (os.getenv("BG_FULLBLEED_INNER", "content") or "content").lower()

# 2-col equalization fallback when no ratio class detected
EQUALIZE_2COL_FALLBACK = (os.getenv("EQUALIZE_2COL_FALLBACK", "true").lower() == "true")
DETECT_EQUAL_2COL = (os.getenv("DETECT_EQUAL_2COL", "true").lower() == "true")

# Track node kind for filtering and reporting: text|container|rect|image|line|other
NODE_KIND_MAP = {}

def set_node_kind(node_id, kind):
    if not node_id:
        return
    try:
        safe_id = css_safe_identifier(node_id)
        if safe_id:
            NODE_KIND_MAP[safe_id] = kind
    except Exception:
        pass

def parse_figma_url(url):
    try:
        p = urlparse(url)
        parts = [s for s in p.path.split('/') if s]
        file_key = None
        for i, seg in enumerate(parts):
            if seg in ("file", "design") and i + 1 < len(parts):
                file_key = parts[i + 1]
                break
        q = parse_qs(p.query)
        node_id = None
        for k in ("node-id", "node_id"):
            if k in q and len(q[k]) > 0:
                raw = unquote(q[k][0])
                node_id = raw
                if ':' not in node_id and re.match(r"^\d+-\d+$", node_id):
                    node_id = node_id.replace('-', ':', 1)
                break
        return file_key, node_id
    except Exception:
        return None, None

# Prefer URL-based config if provided
if PC_FIGMA_URL:
    fk, nid = parse_figma_url(PC_FIGMA_URL)
    if fk:
        FILE_KEY = fk
    if nid:
        FRAME_NODE_ID = nid

SP_FILE_KEY = FILE_KEY
if SP_FIGMA_URL:
    sp_fk, sp_nid = parse_figma_url(SP_FIGMA_URL)
    if sp_fk:
        SP_FILE_KEY = sp_fk
    if sp_nid:
        SP_FRAME_NODE_ID = sp_nid

# 入力検証：オフライン入力（ローカルJSON）ならAPIトークン/ファイルキーは不要
if INPUT_JSON_FILE:
    if not FRAME_NODE_ID:
        raise ValueError("ローカルJSONを使用する場合でも FRAME_NODE_ID は必要です。")
else:
    if not all([FIGMA_API_TOKEN, FILE_KEY, FRAME_NODE_ID]):
        raise ValueError("APIトークン、ファイルキー、フレームIDを .env に設定してください。")

headers = {"X-Figma-Token": FIGMA_API_TOKEN}

# ヘルパー関数
def sanitize_filename(name):
    """ファイル名に使えない文字を置換"""
    return re.sub(r'[/\\:*?"<>|]', '_', name)

def css_safe_identifier(text: str) -> str:
    """CSSクラス/セレクタで安全な識別子へ変換"""
    if not text:
        return ""
    safe = re.sub(r'[^a-zA-Z0-9_-]', '-', text)
    safe = re.sub(r'-{2,}', '-', safe).strip('-')
    return safe

# --- Alias helpers for .n- classes ---
NODE_ALIAS_CANDIDATE = {}
ALIAS_FREQ = {}
ALIAS_BASE_FREQ = {}
CURRENT_SECTION_KEY = ""

def _is_bad_alias(name: str) -> bool:
    if not name:
        return True
    n = name.strip().lower()
    if not n:
        return True
    # Avoid generic/structural or reserved prefixes
    if n in {"section", "container", "inner", "content-width-container", "bg-fullbleed", "image-placeholder", "content-item", "layout-item"}:
        return True
    if n.startswith("n-") or n.startswith("layout-") or n.startswith("device-"):
        return True
    return False


def maybe_register_alias(node_id: str, element_name: str, element_type: str = "", element=None):
    if N_CLASS_ALIAS_MODE != "add":
        return
    if not node_id:
        return
    try:
        cand = None

        # Try utility class generation if element is provided
        if element is not None:
            utility_classes = generate_utility_classes_for_element(element)
            if utility_classes:
                # Use the first utility class as the alias
                cand = utility_classes[0]

        # Fallback to semantic/safe-name generation
        if not cand:
            if N_CLASS_ALIAS_SOURCE == "semantic":
                cand = generate_semantic_class(element_name or "", element_type or "")
            else:
                # safe-name source
                raw = (element_name or "").strip()
                cand = css_safe_identifier(raw.lower())

        if not cand or _is_bad_alias(cand):
            return

        # If we have a utility class, use it directly without modification
        if element is not None and cand in UTILITY_CLASS_CACHE.values():
            chosen = cand
        else:
            # Namespace with section (optional)
            # Token filter (aggressive): drop numeric/noise tokens
            alias_base = cand
            try:
                if N_CLASS_ALIAS_TOKEN_FILTER == 'aggressive':
                    import re
                    tokens = re.split(r"[^a-zA-Z0-9]+", cand)
                    filtered = []
                    for t in tokens:
                        if not t:
                            continue
                        letters = sum(ch.isalpha() for ch in t)
                        digits = sum(ch.isdigit() for ch in t)
                        if letters == 0 and digits > 0:
                            continue  # pure number
                        if letters < digits:
                            continue  # mostly numeric
                        if len(t) <= 1:
                            continue
                        filtered.append(t.lower())
                    if filtered:
                        alias_base = "-".join(filtered)
                    else:
                        alias_base = 'item'
            except Exception:
                pass
            # Stopwords (generic tokens)
            try:
                stop = {"frame","group","rectangle","rect","line","vector","image","img","layer","box","container","inner","section"}
                if alias_base in stop:
                    alias_base = 'block' if (element_type or '').upper() in ('FRAME','GROUP') else 'item'
            except Exception:
                pass

            # Set chosen based on alias_base
            chosen = alias_base
            if N_CLASS_ALIAS_NAMESPACE == 'section' and CURRENT_SECTION_KEY:
                if N_CLASS_ALIAS_STYLE == 'bem':
                    alias_base = f"{CURRENT_SECTION_KEY}__{alias_base}"
                else:
                    alias_base = f"{CURRENT_SECTION_KEY}_{alias_base}"
                # Deduplicate within section by adding _2, _3 ...
                base_count = ALIAS_BASE_FREQ.get(alias_base, 0)
                if N_CLASS_ALIAS_DEDUP == 'section_index' and base_count > 0:
                    chosen = f"{alias_base}_{base_count+1}"
                else:
                    chosen = alias_base
                ALIAS_BASE_FREQ[alias_base] = base_count + 1

        # Assign to node
        safe_id = css_safe_identifier(node_id)
        prev = NODE_ALIAS_CANDIDATE.get(safe_id)
        if prev and prev != chosen:
            ALIAS_FREQ[prev] = max(0, ALIAS_FREQ.get(prev, 1) - 1)
        NODE_ALIAS_CANDIDATE[safe_id] = chosen
        ALIAS_FREQ[chosen] = ALIAS_FREQ.get(chosen, 0) + 1
    except Exception:
        return

def _should_drop_n_for_safe(safe_id: str) -> bool:
    try:
        if N_CLASS_ALIAS_MODE != 'add':
            return False
        if not N_CLASS_ALIAS_DROP_N_UNIQUE:
            return False
        alias = NODE_ALIAS_CANDIDATE.get(safe_id)
        if not alias:
            return False
        return ALIAS_FREQ.get(alias, 0) == 1
    except Exception:
        return False


def _normalize_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\r", "\n").strip()
    # collapse whitespace
    s = re.sub(r"\s+", " ", s)
    s = s.strip('"\'')
    return s

def is_decorative_absolute_rect(node):
    try:
        if not isinstance(node, dict):
            return False
        if node.get("type") != "RECTANGLE":
            return False
        if (node.get("layoutPositioning") or "").upper() != "ABSOLUTE":
            return False
        b = (node.get("absoluteBoundingBox") or {})
        h = float(b.get("height") or 0)
        # Treat very thin absolute rectangles as decorative (e.g., underline)
        return h <= 14.0
    except Exception:
        return False

def should_exclude_node(node):
    """除外対象か判定（レイヤー名キーワード/IDで判定）"""
    if not node:
        return False
    # Exclude invisible nodes
    try:
        if node.get("visible") is False:
            return True
    except Exception:
        pass
    # Exclude decorative absolute thin rectangles
    try:
        if is_decorative_absolute_rect(node):
            return True
    except Exception:
        pass
    nid = node.get("id")
    if nid and nid in EXCLUDE_LAYER_IDS:
        return True
    name = (node.get("name") or "").strip().lower()
    if not name:
        return False
    for kw in EXCLUDE_LAYER_NAMES:
        if kw and kw in name:
            return True
    # include-like 自動判定
    if EXCLUDE_INCLUDES:
        nid = node.get("id")
        if nid and nid not in INCLUDE_ALLOWLIST_IDS:
            scope_ok = (INCLUDE_SCOPE == "all") or (nid in ROOT_CHILD_IDS)
            if scope_ok:
                score, reasons = is_include_like(node)
                if score >= INCLUDE_SCORE_THRESHOLD:
                    if INCLUDE_DRY_RUN:
                        INCLUDE_CANDIDATES.append({
                            "frame": CURRENT_FRAME_NAME,
                            "id": nid,
                            "name": node.get("name"),
                            "score": round(score, 2),
                            "reasons": reasons
                        })
                    else:
                        if nid not in INCLUDE_DENYLIST_IDS:
                            return True
                else:
                    # ドライランでも閾値未満は候補として残さない
                    pass
    # Exact-text exclusion for TEXT nodes
    try:
        if EXCLUDE_TEXT_EXACT and (node.get("type") == "TEXT"):
            chars = node.get("characters") or ""
            normalized = _normalize_text(chars)
            tokens = {_normalize_text(t) for t in EXCLUDE_TEXT_EXACT}
            if normalized and normalized in tokens:
                return True
    except Exception:
        pass
    # 自動ヘッダー/フッター判定（ルート直下の子ノードに限定）
    if EXCLUDE_HEADER_FOOTER and node.get("id") in ROOT_CHILD_IDS and is_probable_header_footer(node):
        return True
    return False

# ルートフレームの境界（ヘッダー/フッター判定用）
ROOT_FRAME_BOUNDS = None
ROOT_CHILD_IDS = set()
HAS_H1_EMITTED = False
CURRENT_SECTION_INDEX = -1

def build_reuse_maps(root):
    def walk(n):
        if not isinstance(n, dict):
            return
        comp_id = n.get("componentId")
        if comp_id:
            REUSE_COMPONENT_COUNT[comp_id] = REUSE_COMPONENT_COUNT.get(comp_id, 0) + 1
        nm = (n.get("name") or "").strip().lower()
        if nm:
            REUSE_NAME_COUNT[nm] = REUSE_NAME_COUNT.get(nm, 0) + 1
        for c in n.get("children", []) or []:
            walk(c)
    walk(root)

def is_include_like(node):
    score = 0.0
    reasons = []
    t = (node.get("type") or "").upper()
    if t in ("INSTANCE", "COMPONENT", "COMPONENT_SET"):
        score += 3.0
        reasons.append(f"type={t}")
    nm = (node.get("name") or "").strip().lower()
    if nm and any(kw in nm for kw in INCLUDE_KEYWORDS):
        score += 2.0
        reasons.append("keyword")
    comp_id = node.get("componentId")
    if comp_id and REUSE_COMPONENT_COUNT.get(comp_id, 0) >= INCLUDE_MIN_REUSE_COUNT:
        score += 2.0
        reasons.append("reuse:componentId")
    elif nm and REUSE_NAME_COUNT.get(nm, 0) >= INCLUDE_MIN_REUSE_COUNT:
        score += 2.0
        reasons.append("reuse:name")
    # 位置
    try:
        b = node.get("absoluteBoundingBox", {}) or {}
        root = ROOT_FRAME_BOUNDS or {}
        rw = float(root.get("width", 0) or 0)
        rh = float(root.get("height", 0) or 0)
        rx = float(root.get("x", 0) or 0)
        ry = float(root.get("y", 0) or 0)
        x = float(b.get("x", 0) or 0)
        y = float(b.get("y", 0) or 0)
        w = float(b.get("width", 0) or 0)
        h = float(b.get("height", 0) or 0)
        near_top = (y - ry) < INCLUDE_TOP_MARGIN
        near_bottom = ((y + h) > (ry + rh - INCLUDE_BOTTOM_MARGIN))
        wide = (rw > 0) and ((w / rw) >= INCLUDE_MIN_WIDTH_RATIO)
        if (near_top or near_bottom) and wide:
            score += 1.5
            reasons.append("position")
    except Exception:
        pass
    # locked
    if node.get("locked") is True:
        score += 1.0
        reasons.append("locked")
    return score, reasons

def is_probable_header_footer(node):
    """ヘッダー/フッターらしさを自動判定（幅・位置・名前を併用）"""
    global ROOT_FRAME_BOUNDS
    if not ROOT_FRAME_BOUNDS or not isinstance(ROOT_FRAME_BOUNDS, dict):
        return False
    bounds = node.get("absoluteBoundingBox", {}) or {}
    if not bounds:
        return False
    root_x = ROOT_FRAME_BOUNDS.get("x", 0)
    root_y = ROOT_FRAME_BOUNDS.get("y", 0)
    root_w = ROOT_FRAME_BOUNDS.get("width", 0) or 0
    root_h = ROOT_FRAME_BOUNDS.get("height", 0) or 0
    x = bounds.get("x", 0)
    y = bounds.get("y", 0)
    w = bounds.get("width", 0) or 0
    h = bounds.get("height", 0) or 0
    if root_w <= 0 or root_h <= 0 or w <= 0 or h <= 0:
        return False
    name = (node.get("name") or "").strip().lower()

    # 名称のヒント
    name_is_header = any(k in name for k in ["header", "ヘッダー", "ナビ", "nav", "navigation"])
    name_is_footer = any(k in name for k in ["footer", "フッター"])

    # 位置のヒント
    near_top = (y - root_y) < 120  # ルート上端から120px以内
    near_bottom = ((y + h) > (root_y + root_h - 160))  # ルート下端から160px以内

    # 幅のヒント（ルート幅に近い）
    wide = (w / max(root_w, 1)) > 0.9

    # 高さは極端に大きくない
    not_too_tall = h < max(320, root_h * 0.4)

    is_header_like = wide and near_top and not_too_tall
    is_footer_like = wide and near_bottom and not_too_tall

    if name_is_header and (is_header_like or wide):
        return True
    if name_is_footer and (is_footer_like or wide):
        return True
    # 名前が無くても位置+幅で推測
    if is_header_like:
        return True
    if is_footer_like:
        return True
    return False

def is_wrapper_like(node, p_left: int, p_right: int) -> bool:
    """Heuristically decide if a FRAME acts as a content wrapper.
    Conditions:
    - Node is a FRAME
    - Width is close to root width (>= HPAD_WRAPPER_MIN_WIDTH_RATIO)
    - Node is a direct child of root, or has symmetric horizontal padding within tolerance
    """
    try:
        if (node.get('type') or '').upper() != 'FRAME':
            return False
        b = node.get('absoluteBoundingBox') or {}
        rw = float((ROOT_FRAME_BOUNDS or {}).get('width') or 0)
        w = float(b.get('width') or 0)
        if rw <= 0 or w <= 0:
            return False
        wide = (w / rw) >= HPAD_WRAPPER_MIN_WIDTH_RATIO
        symm = abs(int(p_left or 0) - int(p_right or 0)) <= HPAD_SYMM_TOL_PX
        is_direct = node.get('id') in ROOT_CHILD_IDS
        return wide and (is_direct or symm)
    except Exception:
        return False

def _pick_solid_fill_rgba(element):
    """要素のfillsから最前面のSOLID塗りを選び、rgba文字列を返す。
    - Figmaのfills配列は下→上の順序のため、後方から探索
    - fill.opacity と element.opacity を乗算
    - visible=false や opacity<=0 は無視
    """
    fills = element.get("fills", []) or []
    if not isinstance(fills, list):
        return None
    node_opacity = float(element.get("opacity", 1))
    for fill in reversed(fills):
        if not isinstance(fill, dict):
            continue
        if fill.get("type") != "SOLID":
            continue
        if fill.get("visible") is False:
            continue
        fill_opacity = float(fill.get("opacity", 1))
        alpha = max(0.0, min(1.0, fill_opacity * node_opacity))
        if alpha <= 0:
            continue
        color = fill.get("color", {}) or {}
        r = int(round(float(color.get("r", 0)) * 255))
        g = int(round(float(color.get("g", 0)) * 255))
        b = int(round(float(color.get("b", 0)) * 255))
        return f"rgba({r}, {g}, {b}, {alpha:.2f})"
    return None

# ---------------- ファイル情報取得 ----------------
def fetch_file_json(file_key):
    url = f"https://api.figma.com/v1/files/{file_key}"
    print(f"[LOG] Figma APIにアクセス: {url}")
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def clean_figma_json(data):
    """FigmaJSONから無駄な要素を削除する前処理"""
    removed_count = {"invisible": 0, "empty": 0, "layout_only": 0}

    def should_remove_element(element):
        if not isinstance(element, dict):
            return False

        # 1. 非表示要素
        if element.get('visible') == False:
            removed_count["invisible"] += 1
            return True

        # 2. 完全に空の要素（effects, fills, strokes全て空）
        effects = element.get('effects', [])
        fills = element.get('fills', [])
        strokes = element.get('strokes', [])
        element_type = element.get('type', '')

        if (len(effects) == 0 and len(fills) == 0 and len(strokes) == 0 and
            element_type in ['FRAME', 'GROUP']):
            # 子要素が1個以下なら削除対象
            children = element.get('children', [])
            if len(children) <= 1:
                removed_count["empty"] += 1
                return True

        # 3. レイアウト専用FRAME（視覚効果なし、複数子要素あり）
        if (element_type == 'FRAME' and
            len(effects) == 0 and len(fills) == 0 and len(strokes) == 0):
            # 名前がAuto Layoutやグループ化を示唆する場合
            name = element.get('name', '').lower()
            if any(keyword in name for keyword in ['frame', 'group', 'container', 'wrapper']):
                children = element.get('children', [])
                if len(children) == 1:  # 1個の子要素のみを包むFRAME
                    removed_count["layout_only"] += 1
                    return True

        return False

    def clean_recursive(obj):
        if isinstance(obj, dict):
            # 子要素の再帰的クリーニング
            if 'children' in obj and isinstance(obj['children'], list):
                original_children = obj['children']
                cleaned_children = []

                for child in original_children:
                    if not should_remove_element(child):
                        cleaned_children.append(clean_recursive(child))
                    else:
                        # 削除する要素の子要素を親に統合（フラット化）
                        if isinstance(child, dict) and 'children' in child:
                            for grandchild in child.get('children', []):
                                if not should_remove_element(grandchild):
                                    cleaned_children.append(clean_recursive(grandchild))

                obj['children'] = cleaned_children

            # 他のプロパティも再帰的にクリーニング
            for key, value in obj.items():
                if key != 'children' and isinstance(value, (dict, list)):
                    obj[key] = clean_recursive(value)

        elif isinstance(obj, list):
            return [clean_recursive(item) for item in obj]

        return obj

    cleaned_data = clean_recursive(data)
    return cleaned_data, removed_count

def load_local_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # JSON前処理を実行
        print(f"[LOG] JSON前処理を実行中: {path}")
        cleaned_data, removed_count = clean_figma_json(data)

        total_removed = sum(removed_count.values())
        print(f"[LOG] JSON前処理完了 - 削除要素数: {total_removed}")
        print(f"[LOG]   非表示要素: {removed_count['invisible']}")
        print(f"[LOG]   空要素: {removed_count['empty']}")
        print(f"[LOG]   レイアウト専用: {removed_count['layout_only']}")

        return cleaned_data
    except Exception as e:
        raise RuntimeError(f"ローカルJSONの読み込みに失敗しました: {path} ({e})")

# ファイル情報の取得（ローカルJSON優先）
if INPUT_JSON_FILE:
    print(f"[LOG] Using local JSON file (PC): {INPUT_JSON_FILE}")
    file_data = load_local_json(INPUT_JSON_FILE)
else:
    file_data = fetch_file_json(FILE_KEY)
print("[LOG] Building reuse maps for include-like detection...")
try:
    build_reuse_maps(file_data.get("document", {}))
    print(f"[LOG] Reuse map built: componentIds={len(REUSE_COMPONENT_COUNT)}, names={len(REUSE_NAME_COUNT)}")
except Exception as e:
    print(f"[WARN] Failed to build reuse maps: {e}")

# 生データの保存（設定に応じて）
if SAVE_RAW_DATA:
    raw_data_dir = os.path.join(OUTPUT_DIR, "raw_figma_data")
    os.makedirs(raw_data_dir, exist_ok=True)

    # ファイル名にタイムスタンプを付与
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name_safe = sanitize_filename(file_data.get("name", "Unknown_Project"))

    raw_data_file = os.path.join(raw_data_dir, f"{project_name_safe}_{FILE_KEY}_{timestamp}.json")

    with open(raw_data_file, "w", encoding="utf-8") as f:
        json.dump(file_data, f, ensure_ascii=False, indent=2)

    # 直近参照用の固定名も保存（上書き）
    try:
        latest_pc = os.path.join(raw_data_dir, "latest_pc.json")
        with open(latest_pc, "w", encoding="utf-8") as f:
            json.dump(file_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to write latest_pc.json: {e}")

    print(f"[LOG] Raw Figma data saved: {raw_data_file}")
    print(f"[LOG] Raw data size: {len(json.dumps(file_data))} characters")
else:
    print(f"[LOG] JSONバックアップはスキップ（SAVE_RAW_DATA=false）")
    print(f"[LOG] データサイズ: {len(json.dumps(file_data))} characters")

# ---------------- Figmaスタイル情報の抽出 ----------------
def extract_figma_styles(file_info):
    """Figmaファイルからスタイルのメタ情報を抽出

    注意: filesエンドポイントのstylesは名前/タイプ/IDのみ。詳細値は含まれない。
    テキスト・ペイント詳細は各ノードから収集する方針にする。
    """
    styles_meta = file_info.get("styles", {})

    extracted_styles = {
        "text_styles": {},   # name -> {id}
        "paint_styles": {},  # name -> {id}
        "effect_styles": {}  # name -> {id}
    }

    for style_id, style_data in styles_meta.items():
        style_type = style_data.get("styleType", "")
        style_name = style_data.get("name", f"Style_{style_id}")

        if style_type == "TEXT":
            extracted_styles["text_styles"][style_name] = {"id": style_id}
        elif style_type == "FILL":
            extracted_styles["paint_styles"][style_name] = {"id": style_id}
        elif style_type == "EFFECT":
            extracted_styles["effect_styles"][style_name] = {"id": style_id}

    return extracted_styles

# スタイル情報を抽出
figma_styles = extract_figma_styles(file_data)
print(f"[LOG] Extracted styles:")
print(f"[LOG]   Text styles: {len(figma_styles['text_styles'])}")
print(f"[LOG]   Paint styles: {len(figma_styles['paint_styles'])}")
print(f"[LOG]   Effect styles: {len(figma_styles['effect_styles'])}")

# スタイル情報の表示
for style_name, style_data in figma_styles["text_styles"].items():
    print(f"[LOG]   Text Style: '{style_name}' (id={style_data.get('id')})")

for style_name, style_data in figma_styles["paint_styles"].items():
    print(f"[LOG]   Paint Style: '{style_name}' (id={style_data.get('id')})")

# ID→スタイル名の逆引きマップ（テキスト用、PCファイル基準）
TEXT_STYLE_ID_TO_NAME = {}
try:
    TEXT_STYLE_ID_TO_NAME = {data.get('id'): name for name, data in figma_styles.get('text_styles', {}).items()}
except Exception:
    TEXT_STYLE_ID_TO_NAME = {}

# ---------------- セクション自動検出関数 ----------------
def detect_sections_by_frames(node, path="root"):
    """Figmaフレーム構造によるセクション検出（優先度1位）"""
    sections = []
    node_name = node.get("name", "Unnamed")
    node_type = node.get("type", "Unknown")
    # 除外対象はスキップ
    if should_exclude_node(node):
        print(f"[LOG] Excluded by name/id: {node_name} ({node.get('id')})")
        return sections
    
    # フレームタイプで、セクション名らしいものを検出
    if node_type == "FRAME" and is_section_name(node_name):
        section_info = {
            "id": node["id"],
            "name": node_name,
            "type": "frame_detected",
            "absoluteBoundingBox": node.get("absoluteBoundingBox", {}),
            "children": node.get("children", [])
        }
        sections.append(section_info)
        print(f"[LOG] Section detected by frame: {node_name} ({node['id']})")
    
    # 子ノードも再帰的に検索
    for i, child in enumerate(node.get("children", [])):
        child_path = f"{path}/{node_name}[{i}]"
        sections.extend(detect_sections_by_frames(child, child_path))
    
    return sections

def is_section_name(name):
    """セクション名の判定（命名規則ベース）"""
    section_keywords = [
        "section", "hero", "feature", "pricing", "contact", 
        "about", "service", "gallery", "content", "main",
        "セクション", "ヒーロー", "機能", "料金", "連絡"
    ]
    name_lower = name.lower()
    return any(keyword in name_lower for keyword in section_keywords)

def detect_sections_by_position(node, threshold=100):
    """Y座標による機械的セクション分割（フォールバック）"""
    all_children = [el for el in get_all_child_elements(node) if not should_exclude_node(el)]
    
    # Y座標でソート
    sorted_elements = sorted(all_children, key=lambda x: x.get("absoluteBoundingBox", {}).get("y", 0))
    
    sections = []
    current_section_elements = []
    last_y = 0
    
    for element in sorted_elements:
        y_pos = element.get("absoluteBoundingBox", {}).get("y", 0)
        
        # 大きな空白があればセクション境界とみなす
        if y_pos - last_y > threshold and current_section_elements:
            sections.append({
                "type": "position_detected",
                "elements": current_section_elements.copy(),
                "y_start": current_section_elements[0].get("absoluteBoundingBox", {}).get("y", 0),
                "y_end": last_y
            })
            current_section_elements = []
        
        current_section_elements.append(element)
        last_y = y_pos + element.get("absoluteBoundingBox", {}).get("height", 0)
    
    # 最後のセクション
    if current_section_elements:
        sections.append({
            "type": "position_detected", 
            "elements": current_section_elements,
            "y_start": current_section_elements[0].get("absoluteBoundingBox", {}).get("y", 0),
            "y_end": last_y
        })
    
    return sections

def get_all_child_elements(node):
    """全ての子要素を再帰的に取得"""
    elements = []
    for child in node.get("children", []):
        if should_exclude_node(child):
            print(f"[LOG] Excluded child: {child.get('name')} ({child.get('id')})")
            continue
        elements.append(child)
        elements.extend(get_all_child_elements(child))
    return elements

# ---------------- 画像収集・ダウンロードユーティリティ ----------------
def collect_image_node_ids(node, acc=None):
    if acc is None:
        acc = set()
    if should_exclude_node(node):
        return acc
    # 依存関数に頼らず、fillsにIMAGEがあるかで判定
    fills = node.get("fills", []) or []
    for f in fills:
        if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
            nid = node.get("id")
            if nid:
                acc.add(nid)
            break
    for child in node.get("children", []) or []:
        collect_image_node_ids(child, acc)
    return acc

def fetch_figma_image_urls(file_key, node_ids, image_format="png", scale=1.0):
    if not node_ids:
        return {}
    ids_param = ",".join(node_ids)
    url = f"https://api.figma.com/v1/images/{file_key}?ids={ids_param}&format={image_format}&scale={scale}"
    print(f"[LOG] Requesting image URLs: {url}")
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    return data.get("images", {})

def download_images(url_map, out_dir, file_ext="png", filename_suffix=""):
    os.makedirs(out_dir, exist_ok=True)
    id_to_relpath = {}
    for node_id, url in url_map.items():
        if not url:
            continue
        try:
            safe_id = css_safe_identifier(node_id)
            filename = f"{safe_id}{filename_suffix}.{file_ext}"
            abs_path = os.path.join(out_dir, filename)
            # Cache: skip download if file exists and not forced
            if os.path.exists(abs_path) and not FORCE_IMAGE_REDOWNLOAD:
                id_to_relpath[node_id] = os.path.join("../images", filename)
                print(f"[CACHE] Using existing image: {abs_path}")
                continue

            resp = requests.get(url)
            resp.raise_for_status()
            with open(abs_path, "wb") as f:
                f.write(resp.content)
            id_to_relpath[node_id] = os.path.join("../images", filename)
            print(f"[LOG] Downloaded image: {abs_path}")
        except Exception as e:
            print(f"[WARN] Failed to download image for {node_id}: {e}")
    return id_to_relpath

# ---------------- フレームノード探索 ----------------
def find_node_by_id(node, target_id, path="root"):
    if node["id"] == target_id:
        return node
    for i, child in enumerate(node.get("children", [])):
        found = find_node_by_id(child, target_id, path=f"{path}/{node.get('name', 'Unnamed')}[{i}]")
        if found:
            return found
    return None

print(f"[LOG] Searching for Frame Node: {FRAME_NODE_ID}")
target_frame = find_node_by_id(file_data["document"], FRAME_NODE_ID)

if not target_frame:
    raise ValueError(f"フレームID {FRAME_NODE_ID} が見つかりませんでした")

print(f"[LOG] Frame found: {target_frame.get('name', 'Unnamed')}")
ROOT_FRAME_BOUNDS = target_frame.get("absoluteBoundingBox", {}) or {}
ROOT_CHILD_IDS = {c.get('id') for c in (target_frame.get('children') or []) if isinstance(c, dict)}

# ---------------- Phase 1: 構造解析（軽量処理） ----------------
print("[LOG] === Phase 1: 構造解析開始 ===")

# セクション検出（優先度順に実行）
sections = detect_sections_by_frames(target_frame)

if not sections:
    print("[LOG] フレーム構造でのセクション検出に失敗。Y座標による分割を実行...")
    sections = detect_sections_by_position(target_frame)

print(f"[LOG] 検出されたセクション数: {len(sections)}")

# セクション幅パターン分析機能
def analyze_section_widths(section):
    """セクション内の幅パターンを分析"""
    widths = []
    
    def collect_widths(element, depth=0):
        # 第1-3階層のレイアウトコンテナレベルの幅を収集
        if depth >= 1 and depth <= 3:
            bounds = element.get("absoluteBoundingBox", {})
            width = bounds.get("width", 0)
            if width >= 300:  # 最小幅300px以上でフィルタ
                widths.append(width)
                print(f"[LOG] Width detected: {width}px at depth {depth} ({element.get('name', 'Unnamed')})")
        
        for child in element.get("children", []):
            collect_widths(child, depth + 1)
    
    collect_widths(section)
    return widths

def identify_width_patterns(widths):
    """幅パターンを特定（近似値をグループ化）"""
    width_counts = {}
    for width in widths:
        # 50px単位で丸める（近似値をグループ化）
        rounded_width = round(width / 50) * 50
        width_counts[rounded_width] = width_counts.get(rounded_width, 0) + 1
    
    # 出現頻度でソート
    patterns = sorted(width_counts.items(), key=lambda x: x[1], reverse=True)
    return patterns

def classify_width_patterns(patterns):
    """幅パターンを分類"""
    classified = {
        "full_width": [],      # 1800px以上
        "content_width": [],   # 1000-1799px  
        "medium_width": [],    # 600-999px
        "narrow_width": []     # 300-599px
    }
    
    for width, frequency in patterns:
        if width >= 1800:
            classified["full_width"].append((width, frequency))
        elif width >= 1000:
            classified["content_width"].append((width, frequency))
        elif width >= 600:
            classified["medium_width"].append((width, frequency))
        else:
            classified["narrow_width"].append((width, frequency))
    
    return classified

# 各セクションの幅パターンを分析
print("[LOG] セクション幅パターン分析開始...")
all_widths = []
for i, section in enumerate(sections):
    print(f"[LOG] --- Section {i+1}: {section.get('name', 'Unnamed')} ---")
    section_widths = analyze_section_widths(section)
    all_widths.extend(section_widths)
    print(f"[LOG] Section {i+1} widths: {section_widths}")

# 全体の幅パターンを特定
print(f"[LOG] 全収集幅: {len(all_widths)}個")
width_patterns = identify_width_patterns(all_widths)
print(f"[LOG] 検出された幅パターン: {width_patterns}")

# 幅パターンを分類
classified_patterns = classify_width_patterns(width_patterns)
print(f"[LOG] 分類された幅パターン:")
for category, patterns in classified_patterns.items():
    if patterns:
        print(f"[LOG]   {category}: {patterns}")

# 主要な幅を決定
primary_content_width = 1200  # デフォルト
primary_full_width = 1920     # デフォルト

if classified_patterns["content_width"]:
    primary_content_width = classified_patterns["content_width"][0][0]
if classified_patterns["full_width"]:
    primary_full_width = classified_patterns["full_width"][0][0]

print(f"[LOG] 主要コンテンツ幅: {primary_content_width}px")
print(f"[LOG] 主要フルワイズ幅: {primary_full_width}px")

# レガシー対応
wrapper_width = primary_content_width

# 構造情報の保存
layout_structure = {
    "project_name": file_data.get("name", "Unknown_Project"),
    "frame_name": target_frame.get("name", "Unknown_Frame"),
    "wrapper_width": wrapper_width,
    "primary_content_width": primary_content_width,
    "primary_full_width": primary_full_width,
    "width_patterns": classified_patterns,
    "figma_styles": figma_styles,  # Figmaスタイル情報を追加
    "total_sections": len(sections),
    "sections_summary": [
        {
            "id": section.get("id", f"pos_{i}"),
            "name": section.get("name", f"Section_{i+1}"),
            "type": section.get("type", "unknown"),
            "bounds": section.get("absoluteBoundingBox", {})
        }
        for i, section in enumerate(sections)
    ]
}

print(f"[LOG] Phase 1 完了: 構造解析結果を保存")

# ---------------- レイアウト分析機能 ----------------
def analyze_layout_structure(element):
    """要素のレイアウト構造を分析（カラム数、配置パターンなど）
    優先度: layoutGrids(COLUMNS) > AutoLayout(HORIZONTAL/WRAP) > 位置ベース
    """
    children = element.get("children", []) or []
    if not children:
        return {"type": "single", "columns": 1, "layout_mode": element.get("layoutMode", "NONE"), "reason": "no-children", "confidence": 0.0}

    layout_mode = element.get("layoutMode", "NONE")

    # 1) レイアウトグリッドの列数
    grid_info = None
    for grid in element.get("layoutGrids", []) or []:
        try:
            if grid.get("pattern") == "COLUMNS" and grid.get("visible", True):
                count = int(grid.get("count", 0) or 0)
                if count > 0:
                    grid_info = {
                        "columns": count,
                        "gutter": int(grid.get("gutterSize", 0) or 0),
                        "alignment": grid.get("alignment", "STRETCH"),
                        "sectionSize": grid.get("sectionSize"),
                        "reason": "grid",
                        "confidence": 0.95
                    }
                    break
        except Exception:
            continue

    if grid_info:
        info = {"columns": grid_info["columns"], "layout_mode": layout_mode, "reason": grid_info["reason"], "confidence": grid_info["confidence"]}
        if grid_info.get("columns") == 2:
            info["type"] = "two-column"
        elif grid_info.get("columns") == 3:
            info["type"] = "three-column"
        elif grid_info.get("columns") >= 4:
            info["type"] = "multi-column"
        else:
            info["type"] = "single"
        info["gap"] = grid_info.get("gutter")
        return info

    # 子要素の位置・サイズ収集
    child_positions = []
    for child in children:
        if should_exclude_node(child):
            continue
        b = child.get("absoluteBoundingBox", {}) or {}
        child_positions.append({
            "id": child.get("id"),
            "name": child.get("name", ""),
            "type": child.get("type", ""),
            "x": b.get("x", 0),
            "y": b.get("y", 0),
            "width": b.get("width", 0),
            "height": b.get("height", 0),
            "element": child
        })

    if not child_positions:
        return {"type": "single", "columns": 1, "layout_mode": layout_mode, "reason": "no-visible-children", "confidence": 0.0}

    # 2) Auto Layout 横並び優先
    wrap = element.get("layoutWrap")  # WRAP / NONE / None
    container_w = (element.get("absoluteBoundingBox", {}) or {}).get("width", 0) or 0
    if layout_mode == "HORIZONTAL":
        if wrap == "WRAP" and container_w > 0:
            avg_w = max(1, sum(c["width"] for c in child_positions) / max(1, len(child_positions)))
            gap = int(element.get("itemSpacing", 0) or 0)
            est = max(1, int((container_w + gap) // (avg_w + gap)))
            est = min(est, len(child_positions))
            cols = est
            reason = "auto_layout_wrap"
            confidence = 0.7
        else:
            cols = len(child_positions)
            reason = "auto_layout_horizontal"
            confidence = 0.8

        info = {"columns": cols, "layout_mode": layout_mode, "reason": reason, "confidence": confidence}
        if cols == 2:
            info["type"] = "two-column"
            # 2カラムの比率推定（下の位置ベースでも算出）
        elif cols == 3:
            info["type"] = "three-column"
        elif cols >= 4:
            info["type"] = "multi-column"
        else:
            info["type"] = "single"
    else:
        info = None

    # 3) 位置ベース：行グルーピング（Y重なり）
    def y_overlap(a, b):
        top = max(a["y"], b["y"])
        bottom = min(a["y"] + a["height"], b["y"] + b["height"]) 
        inter = max(0, bottom - top)
        min_h = max(1, min(a["height"], b["height"]))
        return inter / min_h

    rows = []
    used = [False] * len(child_positions)
    # ソートして貪欲に行を作る
    order = sorted(range(len(child_positions)), key=lambda i: child_positions[i]["y"])
    for idx in order:
        if used[idx]:
            continue
        row = [child_positions[idx]]
        used[idx] = True
        for j in order:
            if used[j]:
                continue
            if y_overlap(child_positions[idx], child_positions[j]) >= 0.6:
                row.append(child_positions[j])
                used[j] = True
        if len(row) > 1:
            rows.append(sorted(row, key=lambda x: x["x"]))

    if rows:
        max_columns = max(len(r) for r in rows)
        pos_info = {"columns": max_columns, "reason": "position", "confidence": 0.6, "layout_mode": layout_mode}
        if max_columns == 2:
            pos_info["type"] = "two-column"
            ratios = analyze_column_ratios(rows)
            pos_info["ratios"] = ratios
        elif max_columns == 3:
            pos_info["type"] = "three-column"
        elif max_columns >= 4:
            pos_info["type"] = "multi-column"
        else:
            pos_info["type"] = "single"
    else:
        pos_info = {"type": "single", "columns": 1, "reason": "position-none", "confidence": 0.0, "layout_mode": layout_mode}

    # 決定：grid > auto > position
    if info and info.get("columns", 1) > 1:
        return info
    return pos_info

def map_auto_layout_inline_styles(element):
    """Auto Layout関連のプロパティをCSSのinline styleへ変換"""
    style_parts = []
    layout_mode = element.get("layoutMode", "NONE")
    if layout_mode in ("HORIZONTAL", "VERTICAL"):
        style_parts.append("display:flex")
        if layout_mode == "HORIZONTAL":
            style_parts.append("flex-direction:row")
        else:
            style_parts.append("flex-direction:column")

        # gap (clamp negative spacing to 0 since we don't overlap)
        gap = element.get("itemSpacing")
        if isinstance(gap, (int, float)):
            try:
                g = int(gap)
            except Exception:
                g = 0
            if g < 0:
                g = 0
            if g > 0:
                style_parts.append(f"gap:{g}px")

        # padding with optional horizontal normalization
        p_top = int(element.get("paddingTop", 0) or 0)
        p_right = int(element.get("paddingRight", 0) or 0)
        p_bottom = int(element.get("paddingBottom", 0) or 0)
        p_left = int(element.get("paddingLeft", 0) or 0)
        if any([p_top, p_right, p_bottom, p_left]):
            # base padding shorthand
            style_parts.append(f"padding:{p_top}px {p_right}px {p_bottom}px {p_left}px")
            # horizontal padding normalization by policy
            apply_norm = False
            if HPAD_MODE in ("trim", "clamp") and (p_left > 0 or p_right > 0):
                if HPAD_SCOPE == 'all':
                    apply_norm = True
                elif HPAD_SCOPE == 'wrapper_only':
                    apply_norm = is_wrapper_like(element, p_left, p_right)
            if apply_norm and abs(p_left - p_right) <= HPAD_SYMM_TOL_PX:
                if HPAD_MODE == "trim" and max(p_left, p_right) >= HPAD_TRIM_MIN_PX:
                    # override left/right to 0
                    style_parts.append("padding-left:0")
                    style_parts.append("padding-right:0")
                elif HPAD_MODE == "clamp":
                    # clamp between min px and original, preferred HPAD_CLAMP_VW vw
                    pr = max(p_right, 0)
                    pl = max(p_left, 0)
                    if pr > 0:
                        style_parts.append(f"padding-right:clamp({HPAD_CLAMP_MIN_PX}px, {HPAD_CLAMP_VW}vw, {pr}px)")
                    if pl > 0:
                        style_parts.append(f"padding-left:clamp({HPAD_CLAMP_MIN_PX}px, {HPAD_CLAMP_VW}vw, {pl}px)")
            # expose padding as CSS custom properties for bleed utilities
            try:
                style_parts.append(f"--pad-l:{p_left}px")
                style_parts.append(f"--pad-r:{p_right}px")
            except Exception:
                pass

        # alignment
        primary = element.get("primaryAxisAlignItems", "MIN")
        counter = element.get("counterAxisAlignItems", "MIN")

        def map_align(v):
            return {
                "MIN": "flex-start",
                "CENTER": "center",
                "MAX": "flex-end",
                "SPACE_BETWEEN": "space-between",
            }.get(v, "flex-start")

        # In flexbox: justify-content follows main axis; align-items follows cross axis
        justify = map_align(primary)
        align = map_align(counter)
        style_parts.append(f"justify-content:{justify}")
        style_parts.append(f"align-items:{align}")
        
        # wrap設定（Figma Auto Layoutのwrap対応）
        layout_wrap = element.get("layoutWrap")
        if layout_wrap == "WRAP":
            style_parts.append("flex-wrap:wrap")
        else:
            style_parts.append("flex-wrap:nowrap")

    return "; ".join(style_parts)

def analyze_column_ratios(horizontal_groups):
    """カラムの幅比率を分析（より精密な比率検出）"""
    ratios = []
    
    for group in horizontal_groups:
        if len(group) >= 2:
            # X座標でソート
            sorted_group = sorted(group, key=lambda x: x["x"])
            total_width = sum(item["width"] for item in sorted_group)
            
            if total_width > 0:
                # 各要素の比率を計算
                element_ratios = []
                for item in sorted_group:
                    ratio = item["width"] / total_width
                    element_ratios.append(ratio)
                
                # 精密な比率判定
                ratio_class = classify_ratio_precise(element_ratios)
                print(f"[LOG] 比率分析: 要素数={len(sorted_group)}, 実際の比率={element_ratios}, 分類結果={ratio_class}")
                ratios.append(ratio_class)
    
    return ratios

def classify_ratio_precise(ratios):
    """比率を精密に分類"""
    if len(ratios) == 2:
        left_ratio, right_ratio = ratios
        
        # 1:1 (50%:50%) の判定 - 誤差±5%
        if abs(left_ratio - 0.5) < 0.05 and abs(right_ratio - 0.5) < 0.05:
            return "1:1"
        
        # 1:2 (33%:67%) の判定 - 誤差±5%
        if (abs(left_ratio - 0.33) < 0.05 and abs(right_ratio - 0.67) < 0.05) or \
           (abs(left_ratio - 0.67) < 0.05 and abs(right_ratio - 0.33) < 0.05):
            return "1:2"
        
        # 2:3 (40%:60%) の判定 - 誤差±5%
        if (abs(left_ratio - 0.4) < 0.05 and abs(right_ratio - 0.6) < 0.05) or \
           (abs(left_ratio - 0.6) < 0.05 and abs(right_ratio - 0.4) < 0.05):
            return "2:3"
        
        # 1:3 (25%:75%) の判定 - 誤差±5%
        if (abs(left_ratio - 0.25) < 0.05 and abs(right_ratio - 0.75) < 0.05) or \
           (abs(left_ratio - 0.75) < 0.05 and abs(right_ratio - 0.25) < 0.05):
            return "1:3"
        
        # 3:4 (43%:57%) の判定 - 誤差±3%
        if (abs(left_ratio - 0.43) < 0.03 and abs(right_ratio - 0.57) < 0.03) or \
           (abs(left_ratio - 0.57) < 0.03 and abs(right_ratio - 0.43) < 0.03):
            return "3:4"
        
        # その他の場合は実際の比率を返す
        return f"{left_ratio:.2f}:{right_ratio:.2f}"
    
    elif len(ratios) == 3:
        # 3カラムの場合
        if all(abs(ratio - 0.33) < 0.05 for ratio in ratios):
            return "1:1:1"
        else:
            return ":".join([f"{ratio:.2f}" for ratio in ratios])
    
    # その他の場合
    return ":".join([f"{ratio:.2f}" for ratio in ratios])

def analyze_content_patterns(horizontal_groups):
    """コンテンツパターンを分析（画像-テキスト、テキスト-画像など）"""
    patterns = []
    
    for group in horizontal_groups:
        group_pattern = []
        for item in sorted(group, key=lambda x: x["x"]):  # X座標でソート
            if is_image_element(item["element"]):
                group_pattern.append("image")
            elif item["type"] == "TEXT":
                group_pattern.append("text")
            else:
                group_pattern.append("content")
        
        pattern_str = "-".join(group_pattern)
        if pattern_str not in patterns:
            patterns.append(pattern_str)
    
    return patterns

def generate_layout_class(layout_info):
    """レイアウト情報からCSSクラス名を生成 (ユーティリティクラス優先のため無効化)"""
    # ユーティリティクラス生成システムに移行したため、従来のlayout-*クラスは生成しない
    return ""

# ---------------- Phase 2: セクション詳細解析とHTML生成 ----------------
print("[LOG] === Phase 2: セクション詳細解析開始 ===")

# 出力ディレクトリの準備（sanitize_filenameは冒頭の定義を使用）

safe_project_name = sanitize_filename(layout_structure["project_name"])
safe_frame_name = sanitize_filename(layout_structure["frame_name"])
project_dir = os.path.join(OUTPUT_DIR, safe_project_name, safe_frame_name)
os.makedirs(project_dir, exist_ok=True)
print(f"[LOG] Output directory created: {project_dir}")

# 画像URL取得とダウンロード
IMAGE_URL_MAP = {}
if USE_IMAGES:
    try:
        image_ids = collect_image_node_ids(target_frame)
        print(f"[LOG] Image nodes detected: {len(image_ids)}")
        # 共通のimagesディレクトリを使用（OUTPUT_DIRの直下）
        base_output_dir = os.path.join(OUTPUT_DIR, os.path.basename(os.path.dirname(project_dir)))
        images_dir = os.path.join(base_output_dir, "images")

        if USE_LOCAL_IMAGES_ONLY:
            # オフライン/ローカル参照のみ: 既存ファイルがあればそれをマッピング
            tmp_map = {}
            for nid in image_ids:
                if not nid:
                    continue
                safe_id = css_safe_identifier(nid)
                filename = f"{safe_id}.{IMAGE_FORMAT}"
                abs_path = os.path.join(images_dir, filename)
                if os.path.exists(abs_path):
                    tmp_map[nid] = os.path.join("../images", filename)
            IMAGE_URL_MAP = tmp_map
            if not IMAGE_URL_MAP:
                print("[LOG] No local images found; will use placeholders where needed.")
        else:
            # オンライン: URL取得 → ダウンロード or CDN参照
            url_map = fetch_figma_image_urls(FILE_KEY, list(image_ids), IMAGE_FORMAT, IMAGE_SCALE)
            if DOWNLOAD_IMAGES:
                IMAGE_URL_MAP = download_images(url_map, images_dir, IMAGE_FORMAT)
            else:
                # ローカルがあれば優先、無ければCDN
                tmp_map = {}
                for nid, url in url_map.items():
                    if not nid or not url:
                        continue
                    safe_id = css_safe_identifier(nid)
                    filename = f"{safe_id}.{IMAGE_FORMAT}"
                    abs_path = os.path.join(images_dir, filename)
                    if os.path.exists(abs_path):
                        tmp_map[nid] = os.path.join("../images", filename)
                    else:
                        tmp_map[nid] = url
                IMAGE_URL_MAP = tmp_map
    except Exception as e:
        print(f"[WARN] Image export failed: {e}")
else:
    print("[LOG] Image integration disabled (USE_IMAGES=false)")

# フォント情報抽出関数
def extract_text_styles(text_element, figma_styles=None):
    """テキスト要素からフォント情報を抽出（実際の計算済み値を優先、Figmaスタイル名も記録）"""
    style_info = {
        "font_family": "Arial, sans-serif",  # デフォルト
        "font_size": 16,
        "font_weight": 400,
        "line_height": 1.6,
        "letter_spacing": 0,
        "text_align": "left",
        "color": "#000000",
        "figma_style_name": None  # Figmaスタイル名を記録
    }
    
    # 1. Figma定義スタイルの確認（最優先）
    # filesエンドポイントではスタイル詳細は得られないため、
    # スタイル名のみ逆引きし、詳細値はノードのstyleから取得する。
    style_id = (text_element.get("styles") or {}).get("text")
    if style_id:
        style_name = None
        if figma_styles:
            try:
                local_map = {data.get('id'): name for name, data in figma_styles.get('text_styles', {}).items()}
                style_name = local_map.get(style_id)
            except Exception:
                style_name = None
        if not style_name:
            style_name = TEXT_STYLE_ID_TO_NAME.get(style_id)
        if style_name:
            style_info["figma_style_name"] = style_name
    
    # 2. style プロパティから情報取得（実際の計算済み値を優先使用）
    style = text_element.get("style", {})

    # Figmaスタイル名に関係なく、常に実際の計算済み値（Auto Layout調整後）を使用
    if "fontFamily" in style:
        font_family = style["fontFamily"]
        # FigmaフォントをWeb安全フォントにマッピング
        font_mapping = {
            "Noto Sans JP": "\"Noto Sans JP\", \"Hiragino Kaku Gothic ProN\", \"Hiragino Sans\", Meiryo, sans-serif",
            "Yu Gothic": "\"Yu Gothic\", \"Hiragino Kaku Gothic ProN\", Meiryo, sans-serif",
            "Hiragino Sans": "\"Hiragino Sans\", \"Hiragino Kaku Gothic ProN\", Meiryo, sans-serif",
            "Inter": "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
            "Roboto": "Roboto, -apple-system, BlinkMacSystemFont, sans-serif"
        }
        style_info["font_family"] = font_mapping.get(font_family, f"\"{font_family}\", sans-serif")

    if "fontSize" in style:
        style_info["font_size"] = style["fontSize"]

    if "fontWeight" in style:
        style_info["font_weight"] = style["fontWeight"]

    if "lineHeightPx" in style:
        # 行間をfont-sizeとの比率で計算
        line_height_px = style["lineHeightPx"]
        font_size = style_info["font_size"]
        style_info["line_height"] = round(line_height_px / font_size, 2)
    elif "lineHeightPercent" in style:
        style_info["line_height"] = style["lineHeightPercent"] / 100

    if "letterSpacing" in style:
        style_info["letter_spacing"] = style["letterSpacing"]

    if "textAlignHorizontal" in style:
        align_mapping = {
            "LEFT": "left",
            "CENTER": "center",
            "RIGHT": "right",
            "JUSTIFIED": "justify"
        }
        style_info["text_align"] = align_mapping.get(style["textAlignHorizontal"], "left")
    
    # paragraph spacing (px)
    if "paragraphSpacing" in style:
        try:
            ps = float(style.get("paragraphSpacing", 0) or 0)
            if ps > 0:
                style_info["paragraph_spacing"] = int(round(ps))
        except Exception:
            pass
    
    # text decoration
    td = (style.get("textDecoration") or "").upper()
    if td in ("UNDERLINE", "STRIKETHROUGH", "NONE"):
        style_info["text_decoration"] = {
            "UNDERLINE": "underline",
            "STRIKETHROUGH": "line-through",
            "NONE": "none"
        }.get(td, None)
    
    # text case → text-transform
    tc = (style.get("textCase") or "").upper()
    if tc in ("UPPER", "LOWER", "TITLE"):
        style_info["text_transform"] = {
            "UPPER": "uppercase",
            "LOWER": "lowercase",
            "TITLE": "capitalize"
        }.get(tc)
    
    # italic
    if style.get("italic") is True or (str(style.get("fontStyle", "")).lower() == "italic"):
        style_info["font_style"] = "italic"
    
    # テキストの色情報（fillsから抽出、グラデーション対応）
    rgba = _pick_solid_fill_rgba(text_element)  # 単色フォールバック用
    if rgba:
        style_info["color"] = rgba
    
    return style_info

def extract_effects_styles(element):
    """要素からEffects（シャドウ、ブラー）情報を抽出してCSS文字列を生成"""
    effects = element.get("effects", []) or []
    if not effects:
        return ""

    css_parts = []
    box_shadows = []  # drop-shadow と inner-shadow を収集
    filters = []      # blur effects用

    for effect in effects:
        if not effect.get("visible", True):
            continue

        effect_type = effect.get("type", "")

        if effect_type == "DROP_SHADOW":
            color = effect.get("color", {})
            r = int(round(float(color.get("r", 0)) * 255))
            g = int(round(float(color.get("g", 0)) * 255))
            b = int(round(float(color.get("b", 0)) * 255))
            a = float(color.get("a", 1))

            offset = effect.get("offset", {})
            x = float(offset.get("x", 0))
            y = float(offset.get("y", 0))

            radius = float(effect.get("radius", 0))
            spread = float(effect.get("spread", 0))

            shadow_str = f"{x}px {y}px {radius}px {spread}px rgba({r}, {g}, {b}, {a:.2f})"
            box_shadows.append(shadow_str)

        elif effect_type == "INNER_SHADOW":
            color = effect.get("color", {})
            r = int(round(float(color.get("r", 0)) * 255))
            g = int(round(float(color.get("g", 0)) * 255))
            b = int(round(float(color.get("b", 0)) * 255))
            a = float(color.get("a", 1))

            offset = effect.get("offset", {})
            x = float(offset.get("x", 0))
            y = float(offset.get("y", 0))

            radius = float(effect.get("radius", 0))
            spread = float(effect.get("spread", 0))

            shadow_str = f"inset {x}px {y}px {radius}px {spread}px rgba({r}, {g}, {b}, {a:.2f})"
            box_shadows.append(shadow_str)

        elif effect_type == "LAYER_BLUR":
            radius = float(effect.get("radius", 0))
            if radius > 0:
                filters.append(f"blur({radius}px)")

        elif effect_type == "BACKGROUND_BLUR":
            radius = float(effect.get("radius", 0))
            if radius > 0:
                # Background blur should use backdrop-filter
                # Note: requires semi-transparent background to visualize properly
                css_parts.append(f"backdrop-filter: blur({radius}px)")
                css_parts.append(f"-webkit-backdrop-filter: blur({radius}px)")

    # CSSプロパティとして出力
    if box_shadows:
        css_parts.append(f"box-shadow: {', '.join(box_shadows)}")

    if filters:
        css_parts.append(f"filter: {' '.join(filters)}")

    return "; ".join(css_parts)

def extract_fills_styles(element):
    """要素からFills（背景色・グラデーション）情報を抽出してCSS文字列を生成"""
    fills = element.get("fills", []) or []
    if not fills:
        return ""

    node_opacity = float(element.get("opacity", 1))
    css_parts = []

    # fillsは配列の後方が最前面（Figmaの仕様）
    for idx, fill in enumerate(reversed(fills)):
        if not isinstance(fill, dict):
            continue
        if fill.get("visible") is False:
            continue

        fill_type = fill.get("type", "")
        fill_opacity = float(fill.get("opacity", 1))
        alpha = max(0.0, min(1.0, fill_opacity * node_opacity))

        if alpha <= 0:
            continue

        if fill_type == "SOLID":
            color = fill.get("color", {})
            r = int(round(float(color.get("r", 0)) * 255))
            g = int(round(float(color.get("g", 0)) * 255))
            b = int(round(float(color.get("b", 0)) * 255))
            css_parts.append(f"background-color: rgba({r}, {g}, {b}, {alpha:.2f})")
            break  # 最前面の塗りのみ使用

        elif fill_type.startswith("GRADIENT_"):
            gradient_stops = fill.get("gradientStops", [])
            if not gradient_stops:
                continue

            gradient_colors = []
            for stop in gradient_stops:
                position = float(stop.get("position", 0)) * 100
                stop_color = stop.get("color", {})
                r = int(round(float(stop_color.get("r", 0)) * 255))
                g = int(round(float(stop_color.get("g", 0)) * 255))
                b = int(round(float(stop_color.get("b", 0)) * 255))
                stop_alpha = float(stop_color.get("a", 1)) * alpha
                gradient_colors.append(f"rgba({r}, {g}, {b}, {stop_alpha:.2f}) {position:.1f}%")

            if gradient_colors:
                # グラデーションの方向を計算（gradientHandlePositions使用）
                handle_positions = fill.get("gradientHandlePositions", [])
                if len(handle_positions) >= 2:
                    start = handle_positions[0]
                    end = handle_positions[1]

                    # 角度計算（0度=右、90度=下）
                    dx = end.get("x", 1) - start.get("x", 0)
                    dy = end.get("y", 1) - start.get("y", 0)

                    import math
                    angle = math.atan2(dy, dx) * 180 / math.pi
                    angle = (angle + 90) % 360  # CSS角度に調整
                else:
                    angle = 90  # デフォルト：上から下

                if fill_type == "GRADIENT_LINEAR":
                    gradient_css = f"linear-gradient({angle:.0f}deg, {', '.join(gradient_colors)})"
                elif fill_type == "GRADIENT_RADIAL":
                    gradient_css = f"radial-gradient(circle, {', '.join(gradient_colors)})"
                elif fill_type == "GRADIENT_ANGULAR":
                    gradient_css = f"conic-gradient(from {angle:.0f}deg, {', '.join(gradient_colors)})"
                else:
                    # GRADIENT_DIAMOND等はlinear-gradientにフォールバック
                    gradient_css = f"linear-gradient({angle:.0f}deg, {', '.join(gradient_colors)})"

                # 可能ならベースとなるSOLID塗りも反映（Figmaの下層フィル）
                base_color_css = None
                try:
                    # fills は下→上の順序。最下層から最初のSOLIDをベース色に。
                    for base in fills:
                        if isinstance(base, dict) and base.get("visible", True) and base.get("type") == "SOLID":
                            bc = base.get("color", {}) or {}
                            br = int(round(float(bc.get("r", 0)) * 255))
                            bg = int(round(float(bc.get("g", 0)) * 255))
                            bb = int(round(float(bc.get("b", 0)) * 255))
                            ba = float(bc.get("a", 1)) * node_opacity
                            base_color_css = f"background-color: rgba({br}, {bg}, {bb}, {ba:.2f})"
                            break
                except Exception:
                    base_color_css = None

                if base_color_css:
                    css_parts.append(base_color_css)
                css_parts.append(f"background: {gradient_css}")
                break  # 最前面の塗りのみ使用

        # IMAGE fillsは既存処理に委譲（background-image）

    return "; ".join(css_parts)

def _pick_solid_stroke_rgba(element):
    """Pick the top-most visible SOLID stroke color as rgba string."""
    strokes = element.get("strokes", []) or []
    if not isinstance(strokes, list):
        return None
    node_opacity = float(element.get("opacity", 1))
    for p in reversed(strokes):
        if not isinstance(p, dict):
            continue
        if p.get("visible") is False:
            continue
        if p.get("type") != "SOLID":
            continue
        paint_opacity = float(p.get("opacity", 1))
        color = p.get("color", {}) or {}
        r = int(round(float(color.get("r", 0)) * 255))
        g = int(round(float(color.get("g", 0)) * 255))
        b = int(round(float(color.get("b", 0)) * 255))
        a = float(color.get("a", 1))
        alpha = max(0.0, min(1.0, a * paint_opacity * node_opacity))
        if alpha <= 0:
            continue
        return f"rgba({r}, {g}, {b}, {alpha:.2f})"
    return None

def extract_stroke_and_radius_styles(element):
    """Extract CSS for border (stroke) and border-radius from a Figma element."""
    css_parts = []
    # Stroke → border
    try:
        stroke_color = _pick_solid_stroke_rgba(element)
        dash = element.get("dashPattern") or element.get("strokeDashes")
        has_dash = isinstance(dash, list) and len(dash) > 0
        # Individual side weights if available
        t = element.get("strokeTopWeight")
        r = element.get("strokeRightWeight")
        b = element.get("strokeBottomWeight")
        l = element.get("strokeLeftWeight")
        side_present = any(isinstance(x, (int, float)) and x > 0 for x in [t, r, b, l])
        if stroke_color and side_present:
            if isinstance(t, (int, float)) and t > 0:
                css_parts.append(f"border-top:{int(round(t))}px {'dashed' if has_dash else 'solid'} {stroke_color}")
            if isinstance(r, (int, float)) and r > 0:
                css_parts.append(f"border-right:{int(round(r))}px {'dashed' if has_dash else 'solid'} {stroke_color}")
            if isinstance(b, (int, float)) and b > 0:
                css_parts.append(f"border-bottom:{int(round(b))}px {'dashed' if has_dash else 'solid'} {stroke_color}")
            if isinstance(l, (int, float)) and l > 0:
                css_parts.append(f"border-left:{int(round(l))}px {'dashed' if has_dash else 'solid'} {stroke_color}")
        else:
            # uniform stroke
            weight = element.get("strokeWeight")
            if weight is None:
                if element.get("strokes"):
                    weight = 1
            if stroke_color and isinstance(weight, (int, float)) and weight > 0:
                css_parts.append(f"border:{int(round(weight))}px {'dashed' if has_dash else 'solid'} {stroke_color}")
    except Exception:
        pass
    # Corner radius → border-radius
    try:
        if element.get("cornerRadius") is not None and isinstance(element.get("cornerRadius"), (int, float)):
            cr = float(element.get("cornerRadius", 0) or 0)
            if cr > 0:
                css_parts.append(f"border-radius:{int(round(cr))}px")
        else:
            radii = element.get("rectangleCornerRadii") or element.get("cornerRadii")
            # Some schemas may provide named radii; accept list of 4
            if isinstance(radii, (list, tuple)) and len(radii) == 4:
                tl, tr, br, bl = [max(0, float(x or 0)) for x in radii]
                if any([tl, tr, br, bl]):
                    css_parts.append(f"border-radius:{int(round(tl))}px {int(round(tr))}px {int(round(br))}px {int(round(bl))}px")
            else:
                # Named per-corner
                tl = element.get("topLeftRadius")
                tr = element.get("topRightRadius")
                br = element.get("bottomRightRadius")
                bl = element.get("bottomLeftRadius")
                corners = [tl, tr, br, bl]
                if any(isinstance(x, (int, float)) and x > 0 for x in corners):
                    tl = int(round(max(0, float(tl or 0))))
                    tr = int(round(max(0, float(tr or 0))))
                    br = int(round(max(0, float(br or 0))))
                    bl = int(round(max(0, float(bl or 0))))
                    css_parts.append(f"border-radius:{tl}px {tr}px {br}px {bl}px")
    except Exception:
        pass
    return "; ".join(css_parts)

def extract_blend_mode_style(element):
    """Map Figma blendMode to CSS mix-blend-mode if applicable."""
    mode = (element.get("blendMode") or "").upper()
    mapping = {
        "MULTIPLY": "multiply",
        "SCREEN": "screen",
        "OVERLAY": "overlay",
        "DARKEN": "darken",
        "LIGHTEN": "lighten",
        "COLOR_DODGE": "color-dodge",
        "COLOR_BURN": "color-burn",
        "HARD_LIGHT": "hard-light",
        "SOFT_LIGHT": "soft-light",
        "DIFFERENCE": "difference",
        "EXCLUSION": "exclusion",
        "HUE": "hue",
        "SATURATION": "saturation",
        "COLOR": "color",
        "LUMINOSITY": "luminosity",
    }
    css = mapping.get(mode)
    if css:
        return f"mix-blend-mode:{css}"
    return ""

def generate_semantic_class(element_name, element_type="", style_info=None, element_context=None):
    """レイヤー名から意味のあるクラス名を生成"""
    if not element_name:
        return None

    # レイヤー名をクリーンアップ
    clean_name = element_name.strip()

    # BEM風の命名規則を適用
    # セクション、コンポーネント、モディファイアを自動判定
    semantic_keywords = {
        # セクション
        "section": "section",
        "hero": "hero",
        "about": "about",
        "service": "service",
        "contact": "contact",
        "footer": "footer",
        "header": "header",
        "nav": "nav",

        # コンポーネント
        "button": "btn",
        "card": "card",
        "title": "title",
        "heading": "heading",
        "text": "text",
        "image": "img",
        "icon": "icon",
        "logo": "logo",
        "menu": "menu",
        "list": "list",

        # 日本語対応
        "ボタン": "btn",
        "カード": "card",
        "タイトル": "title",
        "見出し": "heading",
        "テキスト": "text",
        "画像": "img",
        "アイコン": "icon",
        "メニュー": "menu",
        "リスト": "list",
    }

    # レイヤー名から意味のある単語を抽出
    name_lower = clean_name.lower()

    # 最適なマッチを探す
    for keyword, semantic_class in semantic_keywords.items():
        if keyword in name_lower:
            # 追加情報があれば付加
            modifier = ""
            if "primary" in name_lower or "main" in name_lower or "メイン" in name_lower:
                modifier = "--primary"
            elif "secondary" in name_lower or "sub" in name_lower or "サブ" in name_lower:
                modifier = "--secondary"
            elif "small" in name_lower or "sm" in name_lower or "小" in name_lower:
                modifier = "--sm"
            elif "large" in name_lower or "lg" in name_lower or "大" in name_lower:
                modifier = "--lg"

            return f"{semantic_class}{modifier}"

    # キーワードにマッチしない場合の処理
    # 数字のみのレイヤー名（FigmaのIDなど）はそのまま使用
    if re.match(r'^\d+$', clean_name):
        # 数字のみの場合は、プレフィックスを付けてCSS的に有効にする
        return f"layer-{clean_name}"

    # レイヤー名をそのまま使用（英数字以外をハイフンに）
    safe_name = re.sub(r'[^a-zA-Z0-9\-_]', '-', clean_name)
    safe_name = re.sub(r'-+', '-', safe_name).strip('-').lower()

    # 空の場合や短すぎる場合のフォールバック
    if not safe_name or len(safe_name) < 2:
        return "content-item"

    return safe_name

def _visible_children(node):
    try:
        kids = node.get('children') or []
        return [c for c in kids if isinstance(c, dict) and not should_exclude_node(c)]
    except Exception:
        return []

def _has_padding(node):
    try:
        for k in ('paddingLeft','paddingRight','paddingTop','paddingBottom'):
            if float(node.get(k) or 0) > 0:
                return True
    except Exception:
        pass
    return False

def _has_layout_role(node):
    try:
        mode = (node.get('layoutMode') or 'NONE').upper()
        if mode in ('HORIZONTAL','VERTICAL'):
            gap = float(node.get('itemSpacing') or 0)
            if gap > 0:
                return True
            return False
        return False
    except Exception:
        return False

def is_shallow_wrapper_candidate(node):
    if not FLATTEN_SHALLOW_WRAPPERS:
        return False
    try:
        t = (node.get('type') or '').upper()
        if t not in ('FRAME','GROUP'):
            return False
        kids = _visible_children(node)
        if len(kids) != 1:
            return False
        # visual signals
        if _has_visible_fill(node):
            return False
        if node.get('strokes'):
            return False
        if node.get('effects'):
            return False
        if node.get('cornerRadius') or node.get('rectangleCornerRadii'):
            return False
        if node.get('clipsContent'):
            return False
        if _has_padding(node):
            return False
        # layout role
        if _has_layout_role(node):
            return False
        return True
    except Exception:
        return False

def generate_text_class(style_info, element_name="", element_id=""):
    """スタイル情報からCSSクラス名を生成（レイヤー名優先、色情報も考慮）"""
    # 1. レイヤー名から意味のあるクラス名を生成（最優先）
    if SEMANTIC_CLASS_MODE == "all":
        semantic_class = generate_semantic_class(element_name)
        if semantic_class and semantic_class not in ["content-item", "layout-item"]:
            return semantic_class
    
    # 2. Figmaスタイル名がある場合はそれを使用
    if style_info.get("figma_style_name"):
        figma_class = style_info["figma_style_name"].lower().replace(" ", "-").replace("/", "-")
        return f"figma-style-{figma_class}"
    
    # 3. 色情報を含むユニークなクラス名を生成
    font_size = int(style_info["font_size"])
    font_weight = style_info["font_weight"]
    color = style_info.get("color", "#000000")
    
    # 色からハッシュを生成
    import hashlib
    color_hash = hashlib.md5(color.encode()).hexdigest()[:6]
    
    class_parts = ["text"]
    class_parts.append(f"size-{font_size}")
    
    if font_weight >= 700:
        class_parts.append("bold")
    elif font_weight >= 500:
        class_parts.append("medium")
    
    # 色情報を追加してユニーク性を確保
    class_parts.append(f"c{color_hash}")
    
    return "-".join(class_parts)

# HTML生成関数
def generate_html_for_section(section_data, wrapper_width):
    """セクションデータからHTMLを生成"""
    section_name = section_data.get("name", "unnamed_section")
    
    # セクション名から意味のあるクラス名を生成（モード適用）
    if SEMANTIC_CLASS_MODE == "none":
        section_class = "section"
    else:
        semantic_class = generate_semantic_class(section_name, "section")
        section_class = semantic_class if semantic_class else sanitize_filename(section_name).lower().replace(" ", "-")
    # セクション名前空間キー（別名用）
    global CURRENT_SECTION_KEY
    prev_section_key = CURRENT_SECTION_KEY
    try:
        # prefer semantic class as section key; fallback to sanitized name; ensure css safe
        sec_key_raw = semantic_class if SEMANTIC_CLASS_MODE != 'none' else section_name
        sec_key_raw = sec_key_raw or section_name or 'section'
        CURRENT_SECTION_KEY = css_safe_identifier((sec_key_raw or 'section').lower())
    except Exception:
        CURRENT_SECTION_KEY = 'section'
    # ラッパーモードに応じて出力を切り替え
    if SECTION_WRAPPER_MODE == "minimal":
        # セクション自体に幅制限クラスを付けて最小の入れ子に
        html = f'''<section class="{section_class} content-width-container">\n'''
        indent_children = "  "
        closing = "</section>\n"
    elif SECTION_WRAPPER_MODE == "compact":
        # .containerをやめ、共通の .content-width-container のみ使用（.inner 無し）
        html = f'''<section class="{section_class}">\n  <div class="content-width-container">\n'''
        indent_children = "    "
        closing = "  </div>\n</section>\n"
    else:
        # 従来の構造（後方互換）
        html = f'''<section class="{section_class}">\n  <div class="container" style="max-width: {wrapper_width}px; margin: 0 auto;">\n    <div class="inner">\n'''
        indent_children = "      "
        closing = "    </div>\n  </div>\n</section>\n"
    
    # 子要素の処理（基本的なレイアウトのみ）
    children = section_data.get("children", [])
    # detect_sections_by_position のフォールバック（elements配列）に対応
    if not children and section_data.get("elements"):
        children = section_data.get("elements", [])
    for child in children:
        if should_exclude_node(child):
            print(f"[LOG] Excluded in section: {child.get('name')} ({child.get('id')})")
            continue
        html += generate_element_html(child, indent_children, suppress_leaf_images=False, suppress_parent_bounds=None)

    html += closing
    # reset section key
    CURRENT_SECTION_KEY = prev_section_key
    return html

def detect_heading_level(element):
    """テキスト要素の見出しレベルを判定"""
    element_name = element.get("name", "").lower()
    style = element.get("style", {})
    font_size = style.get("fontSize", 16)
    font_weight = style.get("fontWeight", 400)
    
    # 1. レイヤー名による判定（最優先）
    if "h1" in element_name or "見出し1" in element_name or "title" in element_name:
        return "h1"
    elif "h2" in element_name or "見出し2" in element_name or "subtitle" in element_name:
        return "h2"
    elif "h3" in element_name or "見出し3" in element_name:
        return "h3"
    elif "h4" in element_name or "見出し4" in element_name:
        return "h4"
    
    # 2. フォントサイズ + ウエイトによる判定
    if font_weight >= 600:  # Medium以上の場合
        if font_size >= 32:
            return "h1"
        elif font_size >= 24:
            return "h2"
        elif font_size >= 18:
            return "h3"
        elif font_size >= 16:
            return "h4"
    
    # 3. フォントサイズのみによる判定
    if font_size >= 28:
        return "h1"
    elif font_size >= 20:
        return "h2"
    
    # デフォルトは段落
    raw = "p"

    # 既存ロジックの結果を raw に反映
    if "h1" in element_name or "見出し1" in element_name or "title" in element_name:
        raw = "h1"
    elif "h2" in element_name or "見出し2" in element_name or "subtitle" in element_name:
        raw = "h2"
    elif "h3" in element_name or "見出し3" in element_name:
        raw = "h3"
    elif "h4" in element_name or "見出し4" in element_name:
        raw = "h4"
    else:
        if font_weight >= 600:
            if font_size >= 32:
                raw = "h1"
            elif font_size >= 24:
                raw = "h2"
            elif font_size >= 18:
                raw = "h3"
            elif font_size >= 16:
                raw = "h4"
            else:
                raw = "p"
        else:
            if font_size >= 28:
                raw = "h1"
            elif font_size >= 20:
                raw = "h2"
            else:
                raw = "p"

    # ポリシー適用
    global HAS_H1_EMITTED, CURRENT_SECTION_INDEX
    if HEADING_STRATEGY == "figma":
        # そのまま
        if raw == "h1":
            HAS_H1_EMITTED = True
        return raw

    if HEADING_STRATEGY == "single_h1":
        # ページ全体で最初のh1のみ許可。それ以外はh2へ降格
        if raw == "h1":
            if HAS_H1_EMITTED or (CURRENT_SECTION_INDEX not in (-1, 0)):
                return "h2"
            else:
                HAS_H1_EMITTED = True
                return "h1"
        return raw

    if HEADING_STRATEGY == "per_section":
        # セクション内は基本h2ベース。必要に応じてh3/h4へ。
        # 先頭セクションのみh1を許可（設定次第）
        if raw == "h1":
            if CURRENT_SECTION_INDEX in (-1, 0) and ALLOW_H1_IN_FIRST_SECTION and not HAS_H1_EMITTED:
                HAS_H1_EMITTED = True
                return "h1"
            return "h2"
        # h2/h3/h4はそのまま（最低でもSECTION_HEADING_BASE以上を保証）
        if raw == "p":
            return "p"
        # 正規化
        order = ["h2", "h3", "h4", "p"]
        if SECTION_HEADING_BASE <= 2:
            return raw if raw in order else "h2"
        if SECTION_HEADING_BASE == 3:
            return "h3" if raw in ("h2", "h3") else ("h4" if raw == "h4" else "p")
        return raw

    # フォールバック
    return raw

def is_image_element(element):
    """要素が画像かどうかを判定する包括的な関数"""
    element_name = element.get("name", "").lower()

    # 1. いずれの要素タイプでもIMAGE fillsを持つ
    fills = element.get("fills", [])
    for fill in fills:
        if fill.get("type") == "IMAGE":
            return True

    # 2. 要素名に画像らしいキーワードがある
    image_keywords = ["image", "img", "photo", "picture", "icon", "logo", "banner"]
    if any(keyword in element_name for keyword in image_keywords):
        return True

    # 3. 特定の拡張子を含む名前
    image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"]
    if any(ext in element_name for ext in image_extensions):
        return True

    return False

def _bounds(element):
    return element.get("absoluteBoundingBox", {}) or {}

def _area(b):
    return max(0, float(b.get("width", 0))) * max(0, float(b.get("height", 0)))

def _intersection_area(a, b):
    ax1, ay1 = float(a.get("x", 0)), float(a.get("y", 0))
    ax2, ay2 = ax1 + float(a.get("width", 0)), ay1 + float(a.get("height", 0))
    bx1, by1 = float(b.get("x", 0)), float(b.get("y", 0))
    bx2, by2 = bx1 + float(b.get("width", 0)), by1 + float(b.get("height", 0))
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    return iw * ih

def has_fixed_size_children(element):
    """要素が固定サイズの子要素を持つかチェック"""
    children = element.get("children", []) or []
    for child in children:
        if should_exclude_node(child):
            continue

        # 子要素のサイズ設定をチェック
        sizing_h = (child.get("layoutSizingHorizontal") or "").upper()
        bounds = child.get("absoluteBoundingBox", {})
        width = bounds.get("width", 0)

        # 固定幅を持つ子要素がある
        if sizing_h == "FIXED" and width > 0:
            return True

        # 画像要素（通常固定サイズ）
        child_type = child.get("type", "")
        child_name = (child.get("name", "") or "").lower()
        if (child_type in ["RECTANGLE", "FRAME"] and
            any(keyword in child_name for keyword in ["image", "img", "picture", "photo", "rectangle"])):
            return True

    return False

def _child_auto_layout_rules(parent_layout_mode, child, parent_layout_info=None):
    """Return (styles, skip_width, skip_height)
    - styles: list of CSS props like 'flex:1 1 auto', 'align-self:center'
    - skip_width/skip_height: whether to suppress fixed width/height on this child
    
    新ルール: Auto Layoutコンテナの子要素は基本的に柔軟なサイズにする
    parent_layout_info: 親要素のレイアウト分析結果（比率情報含む）
    """
    styles = []
    skip_w = False
    skip_h = False
    if not parent_layout_mode:
        # 親がAuto Layoutでない場合でも、画像要素は固定幅を避ける傾向
        has_image = is_image_element(child)
        if has_image:
            skip_w = True
            styles.append("flex:1 0 auto")
        return styles, skip_w, skip_h
    
    layout_grow = child.get("layoutGrow", 0)
    layout_align = (child.get("layoutAlign") or "").upper()
    sizing_h = (child.get("layoutSizingHorizontal") or "").upper()
    sizing_v = (child.get("layoutSizingVertical") or "").upper()
    cb = child.get("absoluteBoundingBox") or {}
    cw = float(cb.get("width") or 0)
    
    # 画像を含む要素はAuto Layout内で固定幅を避ける
    has_image = is_image_element(child)
    
    # Auto Layout内の要素は基本的に柔軟サイズ
    if parent_layout_mode == "HORIZONTAL":
        # 押し広げ抑止（ただし、固定サイズ要素は除外）
        if not (sizing_h == "FIXED" and cw > 0):
            styles.append("min-width:0")
        if sizing_h == "FIXED" and cw > 0:
            # 固定幅: ベース・収縮不可
            styles.append(f"flex:0 0 {int(cw)}px")
            styles.append(f"width:{int(cw)}px")
            skip_w = False
        elif sizing_h == "FILL" or (layout_grow and float(layout_grow) > 0):
            # 残り幅: basis=0で安定配分
            try:
                grow = int(layout_grow) if layout_grow else 1
            except Exception:
                grow = 1
            styles.append(f"flex:{grow} 1 0px")
            styles.append("width:auto")
            skip_w = True
        else:
            # HUG/未指定: 内容幅
            styles.append("flex:0 0 auto")
            styles.append("width:auto")
            skip_w = True
    elif parent_layout_mode == "VERTICAL":
        # 垂直レイアウト: 高さは柔軟、横は押し広げ抑止
        skip_h = True
        # 固定幅要素以外にmin-width:0を適用
        if not (sizing_h == "FIXED" and cw > 0):
            styles.append("min-width:0")
        if layout_grow and float(layout_grow) > 0:
            styles.append(f"flex:{int(layout_grow)} 1 auto")
        else:
            styles.append("flex:0 0 auto")
    
    # align-self on counter axis
    align_map = {
        "MIN": "flex-start",
        "MAX": "flex-end",
        "CENTER": "center",
        "STRETCH": "stretch",
    }
    if layout_align in align_map:
        styles.append(f"align-self:{align_map[layout_align]}")
        if layout_align == "STRETCH":
            # stretch on counter axis implies no fixed size on that axis
            if parent_layout_mode == "HORIZONTAL":
                skip_h = True
            elif parent_layout_mode == "VERTICAL":
                skip_w = True
    
    return styles, skip_w, skip_h


def generate_element_html(element, indent="", suppress_leaf_images=False, suppress_parent_bounds=None, parent_layout_mode=None, parent_padding=None, child_index=None):
    """個別要素のHTML生成"""
    element_type = element.get("type", "")
    element_name = element.get("name", "")
    # 除外対象は何も出力しない
    if should_exclude_node(element):
        return ""
    
    # テキスト要素
    if element_type == "TEXT":
        text_content = escape(element.get("characters", "テキスト"))
        
        # フォント情報の取得（Figmaスタイル優先）
        style_info = extract_text_styles(element, layout_structure.get("figma_styles"))
        element_id = element.get("id", "")
        base_class = generate_text_class(style_info, element_name, element_id)
        classes = [base_class]
        # Figmaのテキストスタイル名がある場合、figma-style クラスも付与
        if style_info.get("figma_style_name"):
            figma_class = style_info["figma_style_name"].lower().replace(" ", "-").replace("/", "-")
            classes.append(f"figma-style-{figma_class}")
        style_class = " ".join(dict.fromkeys(classes))

        # テキスト要素のinline style生成（エフェクトのみ、背景色は適用しない）
        text_style_parts = []

        # Note: テキストのfillsは文字色として使用（extract_text_stylesで処理済み）
        # 背景色はテキスト要素には適用しない（Figmaの仕様に合わせる）

        # Effects（シャドウ、ブラー）の適用
        effects_style = extract_effects_styles(element)
        if effects_style:
            text_style_parts.append(effects_style)

        # inline styleの生成
        inline_style = "; ".join(text_style_parts) if text_style_parts else ""
        style_attr = f' style="{inline_style}"' if inline_style else ""

        # 見出しレベルの判定
        tag_name = detect_heading_level(element)

        # ノード固有の色をCSSに出力し、テキスト要素にもノードクラスを付与（Figmaスタイル色の誤適用回避）
        node_id = element.get("id")
        node_safe = css_safe_identifier(node_id) if node_id else None
        node_class = f"n-{node_safe}" if node_safe else None
        if node_safe:
            set_node_kind(node_id, 'text')
            # set color per node
            color = style_info.get("color")
            if color:
                add_node_styles(node_safe, [f"color: {color}"])
        if node_class:
            # optionally drop .n- if unique alias present
            if not _should_drop_n_for_safe(node_safe):
                style_class = f"{style_class} {node_class}"
        # optional alias class
        try:
            if N_CLASS_ALIAS_MODE == 'add' and node_safe:
                alias = NODE_ALIAS_CANDIDATE.get(node_safe)
                if alias and (f" {alias}" not in style_class):
                    style_class = f"{style_class} {alias}"
        except Exception:
            pass

        # Register alias for n-class mapping (optional)
        try:
            maybe_register_alias(node_id, element_name, "TEXT", element)
            # Fallback: if no alias registered (empty or generic layer name), create from heading level
            node_safe_chk = css_safe_identifier(node_id) if node_id else None
            if node_safe_chk and node_safe_chk not in NODE_ALIAS_CANDIDATE:
                tag_guess = detect_heading_level(element)
                fallback_name = 'heading' if tag_guess and tag_guess.startswith('h') else 'text'
                maybe_register_alias(node_id, fallback_name, "TEXT", element)
        except Exception:
            pass
        return f'{indent}<{tag_name} class="{style_class}"{style_attr}>{text_content}</{tag_name}>\n'
    
    # コンテナ（子を持つ要素）は常にコンテナとして扱う（画像fillがあっても背景として扱う）
    children = element.get("children", []) or element.get("elements", []) or []
    if element_type == "FRAME" or children:
        # Conservative flatten: single-child wrapper with no visual/layout role
        try:
            if is_shallow_wrapper_candidate(element):
                vc = _visible_children(element)
                if len(vc) == 1:
                    # Preserve parent wrapper's auto layout context for the child
                    layout_info = analyze_layout_structure(element)
                    # apply child auto-layout mapping as if inside this wrapper
                    try:
                        child_styles, skip_w, skip_h = _child_auto_layout_rules(layout_info.get("layout_mode"), vc[0], layout_info)
                        cid = vc[0].get("id")
                        if cid and child_styles:
                            # ensure min-width:0 to avoid overflow (ただし固定サイズ子要素を持つ場合は除外)
                            if not any(s.strip().lower().startswith('min-width:') for s in child_styles):
                                if not has_fixed_size_children(vc[0]):
                                    child_styles.append('min-width:0')
                            add_node_styles(css_safe_identifier(cid), child_styles)
                    except Exception:
                        pass
                    # propagate wrapper padding as parent padding
                    try:
                        p_left = float(element.get("paddingLeft", 0) or 0)
                        p_right = float(element.get("paddingRight", 0) or 0)
                        pp = (p_left, p_right)
                    except Exception:
                        pp = parent_padding
                    return generate_element_html(
                        vc[0],
                        indent,
                        suppress_leaf_images=suppress_leaf_images,
                        suppress_parent_bounds=suppress_parent_bounds,
                        parent_layout_mode=layout_info.get("layout_mode"),
                        parent_padding=pp,
                        child_index=child_index,
                    )
        except Exception:
            pass
        # クラス名（セマンティック出力モード適用）
        if SEMANTIC_CLASS_MODE == "all":
            semantic_class = generate_semantic_class(element_name, element_type)
            frame_class = semantic_class if semantic_class else sanitize_filename(element_name).lower().replace(" ", "-")
        else:
            frame_class = ""  # ユーティリティクラス優先のため無効化
        # Register alias for n-class mapping (optional)
        try:
            maybe_register_alias(element.get("id"), element_name, element_type or "FRAME", element)
        except Exception:
            pass

        # レイアウト分析/クラス
        layout_info = analyze_layout_structure(element)
        layout_class = generate_layout_class(layout_info)

        # 要素自身のサイズ（FigmaのabsoluteBoundingBox）を反映
        bounds = element.get("absoluteBoundingBox", {}) or {}
        w = bounds.get("width")
        h = bounds.get("height")

        # 背景画像（fill: IMAGE）の反映
        bg_style = []
        fills = element.get("fills", []) or []
        has_image_fill = any(f.get("type") == "IMAGE" and f.get("visible", True) for f in fills)
        background_wrapper_style = []
        if has_image_fill:
            if USE_IMAGES:
                node_id = element.get("id", "")
                src = IMAGE_URL_MAP.get(node_id)
                if src:
                    # 背景レイヤー合成（画像 + グラデーション + ベース色）をwrapperに適用
                    try:
                        fills = element.get("fills", []) or []
                        node_opacity = float(element.get("opacity", 1))
                        layers = []
                        base_color_css = None
                        # top-most first for CSS background layering
                        for f in reversed(fills):
                            if not isinstance(f, dict) or f.get("visible") is False:
                                continue
                            ftype = f.get("type")
                            if ftype == "IMAGE":
                                # 画像はURL1つで近似
                                layers.append(f"url('{src}')")
                            elif ftype and ftype.startswith("GRADIENT_"):
                                stops = f.get("gradientStops", []) or []
                                if not stops:
                                    continue
                                cols = []
                                for stop in stops:
                                    pos = float(stop.get("position", 0)) * 100
                                    c = stop.get("color", {}) or {}
                                    rr = int(round(float(c.get("r", 0)) * 255))
                                    gg = int(round(float(c.get("g", 0)) * 255))
                                    bb = int(round(float(c.get("b", 0)) * 255))
                                    aa = float(c.get("a", 1)) * node_opacity
                                    cols.append(f"rgba({rr}, {gg}, {bb}, {aa:.2f}) {pos:.1f}%")
                                angle = 90
                                try:
                                    hp = f.get("gradientHandlePositions", [])
                                    if len(hp) >= 2:
                                        dx = float(hp[1].get("x", 1)) - float(hp[0].get("x", 0))
                                        dy = float(hp[1].get("y", 1)) - float(hp[0].get("y", 0))
                                        import math
                                        angle = (math.degrees(math.atan2(dy, dx)) + 90) % 360
                                except Exception:
                                    pass
                                if ftype == "GRADIENT_LINEAR":
                                    layers.append(f"linear-gradient({angle:.0f}deg, {', '.join(cols)})")
                                elif ftype == "GRADIENT_RADIAL":
                                    layers.append(f"radial-gradient(circle, {', '.join(cols)})")
                                elif ftype == "GRADIENT_ANGULAR":
                                    layers.append(f"conic-gradient(from {angle:.0f}deg, {', '.join(cols)})")
                                else:
                                    layers.append(f"linear-gradient({angle:.0f}deg, {', '.join(cols)})")
                            elif ftype == "SOLID" and base_color_css is None:
                                c = f.get("color", {}) or {}
                                rr = int(round(float(c.get("r", 0)) * 255))
                                gg = int(round(float(c.get("g", 0)) * 255))
                                bb = int(round(float(c.get("b", 0)) * 255))
                                aa = float(c.get("a", 1)) * node_opacity
                                base_color_css = f"background-color: rgba({rr}, {gg}, {bb}, {aa:.2f})"
                        # 反映
                        if base_color_css:
                            background_wrapper_style.append(base_color_css)
                        if layers:
                            background_wrapper_style.append(f"background: {', '.join(layers)}")
                        # 元要素の高さも背景wrapper要素に移動
                        if h and isinstance(h, (int, float)) and h > 0:
                            if SUPPRESS_FIXED_HEIGHT and USE_ASPECT_RATIO and w and isinstance(w, (int, float)) and w > 0:
                                # prefer aspect ratio over fixed height
                                background_wrapper_style.append(f"aspect-ratio:{int(w)}/{int(h)}")
                            elif not SUPPRESS_FIXED_HEIGHT:
                                background_wrapper_style.append(f"height:{int(h)}px")
                    except Exception:
                        # フォールバック：従来通り画像のみ
                        background_wrapper_style.append(f"background-image:url('{src}')")
                        if h and isinstance(h, (int, float)) and h > 0:
                            if SUPPRESS_FIXED_HEIGHT and USE_ASPECT_RATIO and w and isinstance(w, (int, float)) and w > 0:
                                background_wrapper_style.append(f"aspect-ratio:{int(w)}/{int(h)}")
                            elif not SUPPRESS_FIXED_HEIGHT:
                                background_wrapper_style.append(f"height:{int(h)}px")

        # Auto Layoutをinline styleで反映
        inline_style = map_auto_layout_inline_styles(element)
        style_parts = [inline_style] if inline_style else []
        
        # Auto Layout環境での自動サイズ調整検出を強化
        sizing_primary = (element.get("primaryAxisSizingMode") or "").upper()
        sizing_counter = (element.get("counterAxisSizingMode") or "").upper()
        layout_grow = element.get("layoutGrow", 0)
        layout_align = (element.get("layoutAlign") or "").upper()
        
        add_w = True
        add_h = True
        
        # 自身がAuto Layoutコンテナの場合のサイズモード
        own_layout_mode = layout_info.get("layout_mode")
        
        # デバッグ：Auto Layout情報をログ出力（重要なもののみ）
        element_name = element.get("name", "unnamed")
        if (own_layout_mode and own_layout_mode != "NONE") or (parent_layout_mode and parent_layout_mode != "NONE") or layout_grow > 0:
            print(f"[AUTO-LAYOUT] {element_name}: own={own_layout_mode}, parent={parent_layout_mode}, primary={sizing_primary}, counter={sizing_counter}, grow={layout_grow}, align={layout_align}")
        if own_layout_mode == "HORIZONTAL":
            if sizing_primary == "AUTO":
                add_w = False
                # 内容に合わせて自動幅 (flex-shrink対応)
                style_parts.append("width:auto")
            elif sizing_primary == "FILL":
                add_w = False
                style_parts.append("width:100%")
            if sizing_counter == "AUTO":
                add_h = False
                style_parts.append("height:auto")
            elif sizing_counter == "FILL":
                add_h = False
                style_parts.append("height:100%")
        elif own_layout_mode == "VERTICAL":
            if sizing_primary == "AUTO":
                add_h = False
                style_parts.append("height:auto")
            elif sizing_primary == "FILL":
                add_h = False
                style_parts.append("height:100%")
            if sizing_counter == "AUTO":
                add_w = False
                style_parts.append("width:auto")
            elif sizing_counter == "FILL":
                add_w = False
                style_parts.append("width:100%")
        
        # 親からのAuto Layout制約を考慮
        if parent_layout_mode:
            child_rules, skip_w_child, skip_h_child = _child_auto_layout_rules(parent_layout_mode, element, layout_info)
            if skip_w_child:
                add_w = False
                # 垂直スタック内では全幅、水平スタック内ではflex-grow
                if parent_layout_mode == "VERTICAL":
                    if layout_align == "STRETCH":
                        style_parts.append("width:100%")
                    else:
                        style_parts.append("width:auto")
                elif parent_layout_mode == "HORIZONTAL" and layout_grow > 0:
                    # flex-growが設定されている場合は明示的な幅は不要
                    pass
            if skip_h_child:
                add_h = False
                if parent_layout_mode == "HORIZONTAL":
                    if layout_align == "STRETCH":
                        style_parts.append("height:100%")
                    else:
                        style_parts.append("height:auto")
                elif parent_layout_mode == "VERTICAL" and layout_grow > 0:
                    pass
            # attach flex/align styles from parent's auto-layout intent
            if child_rules:
                style_parts.extend(child_rules)
        
        # 固定サイズの出力（Auto Layoutの意図を尊重）
        # 背景コンテナは固定px幅を出さない（フルブリード化する）
        if isinstance(w, (int, float)) and w > 0 and add_w and not has_image_fill:
            if not SUPPRESS_CONTAINER_WIDTH:
                # Auto Layout環境では固定幅を避ける傾向
                if parent_layout_mode or own_layout_mode:
                    # min-widthとして出力してレスポンシブ性を保持
                    style_parts.append(f"min-width:{int(w)}px")
                else:
                    style_parts.append(f"width:{int(w)}px")
        if isinstance(h, (int, float)) and h > 0 and add_h and not (has_image_fill and USE_IMAGES and background_wrapper_style):
            # 高さは常にmin-heightを優先（コンテンツで伸びることを許可）
            style_parts.append(f"min-height:{int(h)}px")
        if bg_style:
            style_parts.extend(bg_style)

        # 背景色・グラデーション（IMAGE以外）の適用
        if not has_image_fill:
            fills_style = extract_fills_styles(element)
            if fills_style:
                style_parts.append(fills_style)
        # Stroke / corner radius
        sr = extract_stroke_and_radius_styles(element)
        if sr:
            style_parts.append(sr)
        # Blend mode
        bm = extract_blend_mode_style(element)
        if bm:
            style_parts.append(bm)

        # Effects（シャドウ、ブラー）の適用
        effects_style = extract_effects_styles(element)
        if effects_style:
            style_parts.append(effects_style)

        # クリップ有効時は隠す
        if element.get("clipsContent"):
            style_parts.append("overflow:hidden")
        # ノード固有クラスへスタイルを移譲
        node_id = element.get("id", "")
        node_safe = css_safe_identifier(node_id) if node_id else None
        node_class = f"n-{node_safe}" if node_safe else None
        if node_class and style_parts:
            set_node_kind(node_id, 'container')
            add_node_styles(node_safe, [p for p in style_parts if p])

        # クラス結合（semantic + layout + node-specific）
        all_classes = [frame_class]
        if layout_class:
            all_classes.append(layout_class)
        if node_class:
            all_classes.append(node_class)
        # 固定幅クラス検出とfixed-widthクラス追加
        all_classes = add_fixed_width_class_if_needed(all_classes)
        # 背景画像がある場合は、bg-fullbleedクラスを元要素には追加しない
        final_class = " ".join(all_classes)

        # 背景画像がある場合は親要素（wrapper）を追加（ポリシー: content|none）
        if has_image_fill and USE_IMAGES and background_wrapper_style:
            # Ensure single image covers full width without tiling
            try:
                background_wrapper_style.append('background-repeat:no-repeat')
                background_wrapper_style.append('background-size:cover')
                background_wrapper_style.append('background-position:center')
            except Exception:
                pass
            # Apply border-radius to wrapper if element has it
            try:
                sr = extract_stroke_and_radius_styles(element) or ''
                if 'border-radius' in sr:
                    # extract just border-radius value
                    for part in sr.split(';'):
                        part = part.strip()
                        if part.startswith('border-radius'):
                            background_wrapper_style.append(part)
                            background_wrapper_style.append('overflow:hidden')
            except Exception:
                pass
            wrapper_style = "; ".join(background_wrapper_style)
            html = f'{indent}<div class="bg-fullbleed" style="{wrapper_style}">\n'
            if BG_FULLBLEED_INNER == "content":
                html += f'{indent}  <div class="content-width-container">\n'
                # optional alias class for containers inside wrapper
                try:
                    if N_CLASS_ALIAS_MODE == 'add' and node_class:
                        safe = node_class[2:] if node_class.startswith('n-') else None
                        if safe:
                            # drop n-class if configured and unique alias exists
                            if _should_drop_n_for_safe(safe):
                                final_class = " ".join([c for c in final_class.split() if not c.startswith('n-')])
                            alias = NODE_ALIAS_CANDIDATE.get(safe)
                            if alias:
                                final_class = f"{final_class} {alias}"
                except Exception:
                    pass
                html += f'{indent}    <div class="{final_class}">\n'
                content_indent = indent + "      "
                closing_html = f'{indent}    </div>\n{indent}  </div>\n{indent}</div>\n'
            else:
                # optional alias class for containers inside wrapper
                try:
                    if N_CLASS_ALIAS_MODE == 'add' and node_class:
                        safe = node_class[2:] if node_class.startswith('n-') else None
                        if safe:
                            if _should_drop_n_for_safe(safe):
                                final_class = " ".join([c for c in final_class.split() if not c.startswith('n-')])
                            alias = NODE_ALIAS_CANDIDATE.get(safe)
                            if alias:
                                final_class = f"{final_class} {alias}"
                except Exception:
                    pass
                html += f'{indent}  <div class="{final_class}">\n'
                content_indent = indent + "    "
                closing_html = f'{indent}  </div>\n{indent}</div>\n'
        else:
            # optional alias class for containers: append if registered
            try:
                alias_extra = ''
                if N_CLASS_ALIAS_MODE == 'add' and node_class:
                    # node_class is like 'n-<id>' – extract safe id
                    safe = node_class[2:] if node_class.startswith('n-') else None
                    if safe:
                        if _should_drop_n_for_safe(safe):
                            final_class = " ".join([c for c in final_class.split() if not c.startswith('n-')])
                        alias = NODE_ALIAS_CANDIDATE.get(safe)
                        if alias:
                            final_class = f"{final_class} {alias}"
            except Exception:
                pass
            html = f'{indent}<div class="{final_class}">\n'
            content_indent = indent + "  "
            closing_html = f'{indent}</div>\n'

        # 2カラム: Auto Layout配分で子幅を割り当て（優先）
        # 画像+テキストパターンの場合は統一的なflex配分を適用
        content_pattern = detect_image_text_pattern(element)
        is_image_text_layout = content_pattern in ["image-text", "text-image"]

        if USE_AL_RATIO_2COL and layout_info.get("type") == "two-column" and (element.get("layoutMode") or "").upper() == "HORIZONTAL":
            try:
                direct_children = element.get("children", []) or []
                dc = [c for c in direct_children if isinstance(c, dict)]
                if len(dc) == 2:
                    # 画像+テキストパターンの場合は統一的な比率を適用
                    if is_image_text_layout:
                        # 画像部分に固定幅、テキスト部分にflex-grow
                        for i, ch in enumerate(dc):
                            ch_name = (ch.get("name") or "").lower()
                            ch_type = ch.get("type") or ""

                            # 画像要素の判定
                            is_image = (ch_type in ["RECTANGLE", "FRAME"] and
                                      any(keyword in ch_name for keyword in ["image", "img", "picture", "photo", "rectangle"]))

                            if is_image:
                                # 画像部分: 固定幅320px
                                ch["_unified_flex"] = "flex: 0 0 320px; max-width: 320px;"
                            else:
                                # テキスト部分: 残り幅を占有
                                ch["_unified_flex"] = "flex: 1 1 auto; min-width: 0;"

                        # 画像+テキストパターンの場合は通常のAL比率計算をスキップ
                        pass
                    else:
                        # 通常のAuto Layout比率計算
                        # Parent inner width = parent width - paddingL/R - gap
                        b = element.get("absoluteBoundingBox") or {}
                        pw = float(b.get("width") or 0)
                        p_left = float(element.get("paddingLeft", 0) or 0)
                        p_right = float(element.get("paddingRight", 0) or 0)
                        gap = float(element.get("itemSpacing", 0) or 0)
                        inner = max(0.0, pw - p_left - p_right - gap)

                        # Child sizing
                        fixed = []
                        weights = []
                        for ch in dc:
                            cb = ch.get("absoluteBoundingBox") or {}
                            cw = float(cb.get("width") or 0)
                            sizing = (ch.get("layoutSizingHorizontal") or "").upper()
                            grow = float(ch.get("layoutGrow") or 0)
                            if sizing == "FIXED":
                                fixed.append(cw)
                                weights.append(0.0)
                            elif sizing == "FILL":
                                fixed.append(0.0)
                                weights.append(grow if grow > 0 else 1.0)
                            else:  # HUG or undefined → treat as fixed content width
                                fixed.append(cw)
                                weights.append(0.0)
                        total_fixed = sum(fixed)
                        rem = max(0.0, inner - total_fixed)
                        total_w = sum(weights)
                        widths = []
                        for i in range(2):
                            extra = (rem * (weights[i] / total_w)) if total_w > 0 else 0.0
                            widths.append(fixed[i] + extra)
                        if inner > 0 and (widths[0] > 0 or widths[1] > 0):
                            p0 = max(0.0, min(100.0, (widths[0] / inner) * 100.0))
                            p1 = max(0.0, min(100.0, 100.0 - p0))
                            for child, percent in zip(dc, (p0, p1)):
                                cid = child.get("id")
                                if cid:
                                    safe = css_safe_identifier(cid)
                                    # 画像+テキストパターンの統一flex設定があればそれを優先
                                    if child.get("_unified_flex"):
                                        flex_style = child["_unified_flex"]
                                        add_node_styles(safe, [flex_style])
                                    else:
                                        add_node_styles(safe, [f"flex: 0 0 {percent:.2f}%", "min-width:0"]) 
            except Exception as e:
                print(f"[WARN] 2col AL ratio mapping failed: {e}")

        # 2カラムのABB比率を使用して子幅を割り当て（フォールバック）
        if USE_ABB_RATIO_2COL and layout_info.get("type") == "two-column":
            try:
                direct_children = element.get("children", []) or []
                dc = [c for c in direct_children if isinstance(c, dict)]
                if len(dc) == 2:
                    w0 = float(((dc[0].get("absoluteBoundingBox") or {}).get("width") or 0))
                    w1 = float(((dc[1].get("absoluteBoundingBox") or {}).get("width") or 0))
                    total = w0 + w1
                    if total > 0:
                        p0 = max(0.0, min(100.0, (w0 / total) * 100.0))
                        p1 = max(0.0, min(100.0, (w1 / total) * 100.0))
                        for child, percent in zip(dc, (p0, p1)):
                            cid = child.get("id")
                            if cid:
                                safe = css_safe_identifier(cid)
                                add_node_styles(safe, [f"flex: 0 0 {percent:.2f}%", "min-width:0"]) 
            except Exception as e:
                print(f"[WARN] 2col ABB ratio mapping failed: {e}")
        # パディング情報を取得（parent_paddingで使用）
        p_left = float(element.get("paddingLeft", 0) or 0)
        p_right = float(element.get("paddingRight", 0) or 0)

        # 子の画像抑制ポリシー
        child_suppress = suppress_leaf_images
        parent_bounds = suppress_parent_bounds
        if IMAGE_CONTAINER_SUPPRESS_LEAFS and has_image_fill and USE_IMAGES:
            child_suppress = True
            parent_bounds = _bounds(element)

        # Infer margins between siblings for non Auto Layout parents
        if INFER_SIBLING_MARGINS and (own_layout_mode or 'NONE').upper() == 'NONE':
            try:
                sibs = [c for c in (element.get('children') or []) if isinstance(c, dict)]
                sibs_sorted = sorted(sibs, key=lambda c: ((c.get('absoluteBoundingBox') or {}).get('y') or 0))
                prev = None
                for ch in sibs_sorted:
                    if not prev:
                        prev = ch
                        continue
                    ab_prev = prev.get('absoluteBoundingBox') or {}
                    ab_cur = ch.get('absoluteBoundingBox') or {}
                    py = float(ab_prev.get('y') or 0.0)
                    ph = float(ab_prev.get('height') or 0.0)
                    cy = float(ab_cur.get('y') or 0.0)
                    mt = int(round(cy - (py + ph)))
                    if mt >= MARGIN_INFER_MIN_PX and mt <= MARGIN_INFER_MAX_PX:
                        cid = ch.get('id')
                        if cid:
                            add_node_styles(css_safe_identifier(cid), [f'margin-top:{mt}px'])
                    prev = ch
            except Exception as e:
                print(f"[WARN] Margin inference failed: {e}")

        for idx, child in enumerate(children):
            if should_exclude_node(child):
                continue
            # apply child auto-layout rules if this container is auto-layout
            child_styles, skip_w, skip_h = _child_auto_layout_rules(layout_info.get("layout_mode"), child, layout_info)
            # enrich child node styles
            child_id = child.get("id")
            if child_id and child_styles:
                add_node_styles(css_safe_identifier(child_id), child_styles)
            html += generate_element_html(
                child,
                content_indent,
                suppress_leaf_images=child_suppress,
                suppress_parent_bounds=parent_bounds,
                parent_layout_mode=layout_info.get("layout_mode"),
                parent_padding=(p_left, p_right),
                child_index=idx,
            )
        html += closing_html
        return html

    # 画像または矩形（子なしの葉要素）
    elif element_type == "RECTANGLE" or is_image_element(element):
        bounds = _bounds(element)
        width = bounds.get("width", 100)
        height = bounds.get("height", 100)
        # Optional alias registration for n-class mapping
        try:
            maybe_register_alias(element.get("id"), element_name, element_type or ("IMAGE" if is_image_element(element) else "RECTANGLE"), element)
        except Exception:
            pass

        # 画像要素かどうかをチェック
        if is_image_element(element):
            # 祖先コンテナが背景画像を持っている場合の抑制（重複回避）
            if suppress_leaf_images and suppress_parent_bounds:
                inter = _intersection_area(bounds, suppress_parent_bounds)
                child_area = _area(bounds)
                parent_area = _area(suppress_parent_bounds)
                # 子が親の大半を覆う、または子自身の大半が親と重なる場合は抑制
                overlap_child = (inter / child_area) if child_area > 0 else 0.0
                overlap_parent = (inter / parent_area) if parent_area > 0 else 0.0
                if max(overlap_child, overlap_parent) >= SUPPRESS_IMAGE_OVERLAP_THRESHOLD:
                    return ""

            semantic_class = generate_semantic_class(element_name, "image")
            img_class = semantic_class if semantic_class else "image"
            node_id = element.get("id", "")
            node_safe = css_safe_identifier(node_id) if node_id else None
            node_class = f"n-{node_safe}" if node_safe else None
            # 固有サイズをCSSに委譲（Auto Layoutの意図を尊重）
            child_styles, skip_w, skip_h = _child_auto_layout_rules(parent_layout_mode, element, None)
            node_props = []
            # Auto Layout HORIZONTAL: Sizingに応じて幅/フレックスを明示
            sizing_h = (element.get("layoutSizingHorizontal") or "").upper()
            # 固定幅要素以外に押し広げ抑止を適用
            if not (sizing_h == "FIXED" and width):
                node_props.append("min-width: 0")
            if parent_layout_mode == "HORIZONTAL":
                if sizing_h == "FIXED" and width:
                    node_props.append(f"flex: 0 0 {int(width)}px")
                    node_props.append(f"width: {int(width)}px")
                else:
                    node_props.append("width: auto")
            else:
                if not skip_w and not SUPPRESS_CONTAINER_WIDTH:
                    node_props.append(f"width: {int(width)}px")
            if not skip_h:
                if SUPPRESS_FIXED_HEIGHT and USE_ASPECT_RATIO and width and height:
                    node_props.append(f"aspect-ratio: {int(width)}/{int(height)}")
                elif not SUPPRESS_FIXED_HEIGHT:
                    node_props.append(f"height: {int(height)}px")
            # Border radius / stroke for image wrapper
            sr = extract_stroke_and_radius_styles(element)
            if sr:
                node_props.append(sr)
                # Clip inner image to rounded corners
                if 'border-radius' in sr:
                    node_props.append("overflow:hidden")
            # Effects（シャドウ、ブラー）の適用
            effects_style = extract_effects_styles(element)
            if effects_style:
                node_props.append(effects_style)
            # Blend mode
            bm = extract_blend_mode_style(element)
            if bm:
                node_props.append(bm)
            # include flex/align if any, avoiding duplicates
            merged_props = merge_css_props(node_props, [s for s in child_styles if s])
            if node_safe:
                set_node_kind(node_id, 'image')
                add_node_styles(node_safe, merged_props)
            if USE_IMAGES:
                # 画像出力（ダウンロード済み or CDN URL）
                src = IMAGE_URL_MAP.get(node_id)
                # フォールバックとしてプレースホルダー
                if not src:
                    safe_name = element_name.replace(" ", "_").replace("(", "").replace(")", "")
                    src = f"https://via.placeholder.com/{int(width)}x{int(height)}/cccccc/666666?text={safe_name}"
                all_classes = [img_class]
                # Auto Layout親に左右paddingがあり、先頭の画像の場合は横いっぱい（ブリード）を許可
                try:
                    if parent_padding and sum(parent_padding) >= 8 and (child_index == 0):
                        if 'no-bleed' not in (element.get('name') or '').lower():
                            all_classes.append('card-img-bleed-x')
                except Exception:
                    pass
                if node_class:
                    all_classes.append(node_class)
                # optional alias class + drop n- if unique
                try:
                    if N_CLASS_ALIAS_MODE == 'add' and node_safe:
                        alias = NODE_ALIAS_CANDIDATE.get(node_safe)
                        if alias and alias not in all_classes:
                            all_classes.append(alias)
                        if _should_drop_n_for_safe(node_safe):
                            all_classes = [c for c in all_classes if not c.startswith('n-')]
                except Exception:
                    pass
                # 固定幅クラス検出とfixed-widthクラス追加
                all_classes = add_fixed_width_class_if_needed(all_classes)
                return f'{indent}<div class="{" ".join(all_classes)}">\n{indent}  <img src="{src}" alt="{escape(element_name)}" style="height: auto; display: block;">\n{indent}</div>\n'
            else:
                # 画像は使わず、サイズだけ確保
                all_classes = [img_class]
                if node_class:
                    all_classes.append(node_class)
                # optional alias class + drop n- if unique
                try:
                    if N_CLASS_ALIAS_MODE == 'add' and node_safe:
                        alias = NODE_ALIAS_CANDIDATE.get(node_safe)
                        if alias and alias not in all_classes:
                            all_classes.append(alias)
                        if _should_drop_n_for_safe(node_safe):
                            all_classes = [c for c in all_classes if not c.startswith('n-')]
                except Exception:
                    pass
                # 固定幅クラス検出とfixed-widthクラス追加
                all_classes = add_fixed_width_class_if_needed(all_classes)
                return f'{indent}<div class="{" ".join(all_classes)}"></div>\n'
        else:
            # 通常の矩形要素
            node_id = element.get("id", "")
            node_safe = css_safe_identifier(node_id) if node_id else None
            node_class = f"n-{node_safe}" if node_safe else None
            child_styles, skip_w, skip_h = _child_auto_layout_rules(parent_layout_mode, element, None)

            # 背景色・グラデーション処理
            fills_style = extract_fills_styles(element)
            node_props = []
            if fills_style:
                node_props.append(fills_style)
            else:
                # フォールバック背景色
                node_props.append("background-color: #f0f0f0")
            if not skip_w and not SUPPRESS_CONTAINER_WIDTH:
                node_props.append(f"width: {int(width)}px")
            if not skip_h:
                if SUPPRESS_FIXED_HEIGHT and USE_ASPECT_RATIO and width and height:
                    node_props.append(f"aspect-ratio: {int(width)}/{int(height)}")
                elif not SUPPRESS_FIXED_HEIGHT:
                    node_props.append(f"height: {int(height)}px")
            # Stroke / corner radius
            sr = extract_stroke_and_radius_styles(element)
            if sr:
                node_props.append(sr)
            # Effects（シャドウ、ブラー）の適用
            effects_style = extract_effects_styles(element)
            if effects_style:
                node_props.append(effects_style)
            # Blend mode
            bm = extract_blend_mode_style(element)
            if bm:
                node_props.append(bm)
            merged_props = merge_css_props(node_props, [s for s in child_styles if s])
            if node_safe:
                set_node_kind(node_id, 'rect')
                add_node_styles(node_safe, merged_props)
            classes = ["rect-element"]
            if node_class:
                classes.append(node_class)
            # optional alias class + drop n- if unique
            try:
                if N_CLASS_ALIAS_MODE == 'add' and node_safe:
                    alias = NODE_ALIAS_CANDIDATE.get(node_safe)
                    if alias and alias not in classes:
                        classes.append(alias)
                    if _should_drop_n_for_safe(node_safe):
                        classes = [c for c in classes if not c.startswith('n-')]
            except Exception:
                pass
            return f'{indent}<div class="{" ".join(classes)}"></div>\n'
    
    # ここまでで該当しない要素タイプ
    
    else:
        # 線要素
        if element_type == "LINE":
            b = _bounds(element)
            w = float(b.get("width", 0) or 0)
            h = float(b.get("height", 0) or 0)
            weight = float(element.get("strokeWeight") or 1)
            color = _pick_solid_stroke_rgba(element) or "rgba(0,0,0,1)"
            node_id = element.get("id", "")
            node_safe = css_safe_identifier(node_id) if node_id else None
            node_class = f"n-{node_safe}" if node_safe else None
            dash = element.get("dashPattern") or element.get("strokeDashes")
            has_dash = isinstance(dash, list) and len(dash) > 0
            cap = (element.get("strokeCap") or "").upper()
            # rotation
            try:
                rot = float(element.get("rotation", 0) or 0)
            except Exception:
                rot = 0.0
            props = []
            horiz_guess = (w >= h)
            # If rotation is near axis-aligned, use border for crisp lines
            if (abs(rot) < 0.01 or abs(abs(rot) - 180.0) < 0.01) and horiz_guess:
                # horizontal line → use full width (responsive)
                if cap == "ROUND":
                    props.append("width:100%")
                    hh = int(round(max(h, weight)))
                    props.append(f"height:{hh}px")
                    props.append(f"background-color:{color}")
                    props.append(f"border-radius:{max(1, hh//2)}px")
                else:
                    props.append("width:100%")
                    props.append("height:0")
                    props.append(f"border-top:{int(round(max(h, weight)))}px {'dashed' if has_dash else 'solid'} {color}")
            elif (abs(abs(rot) - 90.0) < 0.01 or abs(abs(rot) - 270.0) < 0.01) and not horiz_guess:
                # vertical line
                if cap == "ROUND":
                    props.append(f"height:{int(round(h))}px")
                    ww = int(round(max(w, weight)))
                    props.append(f"width:{ww}px")
                    props.append(f"background-color:{color}")
                    props.append(f"border-radius:{max(1, ww//2)}px")
                else:
                    props.append("width:0")
                    props.append(f"height:{int(round(h))}px")
                    props.append(f"border-left:{int(round(max(w, weight)))}px {'dashed' if has_dash else 'solid'} {color}")
            else:
                # angled line fallback as rotated rectangle
                props.append(f"width:{int(round(max(1.0, w)))}px")
                props.append(f"height:{int(round(max(1.0, h, weight)))}px")
                props.append(f"background-color:{color}")
                if cap == "ROUND":
                    rr = int(round(max(1.0, min(w, h, weight) / 2)))
                    props.append(f"border-radius:{rr}px")
                if abs(rot) > 0.01:
                    props.append(f"transform:rotate({rot:.2f}deg)")
                    props.append("transform-origin: left top")
            if node_safe:
                set_node_kind(node_id, 'line')
                add_node_styles(node_safe, props)
            classes = ["line"]
            if node_class:
                classes.append(node_class)
            # optional alias + drop n- if unique
            try:
                if N_CLASS_ALIAS_MODE == 'add' and node_safe:
                    alias = NODE_ALIAS_CANDIDATE.get(node_safe)
                    if alias and alias not in classes:
                        classes.append(alias)
                    if _should_drop_n_for_safe(node_safe):
                        classes = [c for c in classes if not c.startswith('n-')]
            except Exception:
                pass
            return f'{indent}<div class="{" ".join(classes)}"></div>\n'
        # その他の要素タイプでも画像チェック
        if is_image_element(element):
            bounds = element.get("absoluteBoundingBox", {})
            width = bounds.get("width", 100)
            height = bounds.get("height", 100)
            if SEMANTIC_CLASS_MODE == "all":
                semantic_class = generate_semantic_class(element_name, "image")
                img_class = semantic_class if semantic_class else "image-placeholder"
            else:
                img_class = "image-placeholder"
            safe_name = element_name.replace(" ", "_").replace("(", "").replace(")", "")
            return f'{indent}<div class="{img_class}" style="width: {width}px; height: {height}px;">\n{indent}  <img src="https://via.placeholder.com/{int(width)}x{int(height)}/cccccc/666666?text={safe_name}" alt="{element_name}" style="width: 100%; height: 100%; object-fit: cover;">\n{indent}</div>\n'
        else:
            # その他の要素
            if SEMANTIC_CLASS_MODE == "all":
                semantic_class = generate_semantic_class(element_name, element_type)
                element_class = semantic_class if semantic_class else "content-item"
            else:
                element_class = "content-item"
            return f'{indent}<div class="{element_class}" data-type="{element_type}"><!-- {element_name} --></div>\n'

def generate_css(layout_structure, collected_text_styles, node_styles=None):
    """基本的なCSSを生成（複数幅パターン対応＋Figmaスタイル）"""
    primary_content_width = layout_structure.get("primary_content_width", 1200)
    primary_full_width = layout_structure.get("primary_full_width", 1920)
    width_patterns = layout_structure.get("width_patterns", {})
    figma_styles = layout_structure.get("figma_styles", {})
    
    css = f'''/* Generated CSS for {layout_structure["project_name"]} */

/* Google Fonts import */
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;700&family=Inter:wght@300;400;500;600;700&display=swap');

/* Width Pattern Containers */
.full-width-container {{
    width: 100%;
    /* Background images, full-width sections */
}}

.content-width-container {{
    max-width: {primary_content_width}px;
    margin: 0 auto;
    padding: 0 20px;
    /* Main content width */
}}

.medium-width-container {{
    max-width: 800px;
    margin: 0 auto;
    padding: 0 20px;
    /* Medium content width */
}}

/* Legacy container (backward compatibility) */
.container {{
    max-width: {primary_content_width}px;
    margin: 0 auto;
    padding: 0 20px;
}}

.inner {{
    width: 100%;
}}

/* Background fullbleed styles */
.bg-fullbleed {{
    position: relative;
    left: 50%;
    transform: translateX(-50%);
    width: 100vw;
    max-width: 100vw;
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
}}

/* Base image rule */
img {{
    max-width: 100%;
    height: auto;
    display: block;
}}

/* Section styles */
section {{
    padding: 40px 0;
}}

/* Default text styles */
.text-element {{
    margin: 10px 0;
    line-height: 1.6;
}}

/* Card image bleed utility: expand image wrapper to cancel parent's horizontal padding */
.card-img-bleed-x {{
    margin-left: calc(var(--pad-l, 0px) * -1);
    margin-right: calc(var(--pad-r, 0px) * -1);
    width: calc(100% + var(--pad-l, 0px) + var(--pad-r, 0px));
    max-width: none;
}}
.card-img-bleed-x img {{ width: 100%; height: auto; display: block; }}

/* Global image rule (prevent overflow) */
img {{
    max-width: 100%;
    height: auto;
    display: block;
}}

/* Detected Width Patterns */
'''
    
    # 検出された幅パターンごとにCSSクラスを生成
    for category, patterns in width_patterns.items():
        if patterns:
            css += f"/* {category.replace('_', ' ').title()} Patterns */\n"
            for i, (width, frequency) in enumerate(patterns):
                class_name = f"{category.replace('_', '-')}-{i+1}"
                if category == "full_width":
                    css += f'''.{class_name} {{
    width: 100%;
    /* Used {frequency} times, width: {width}px */
}}

'''
                else:
                    css += f'''.{class_name} {{
    max-width: {width}px;
    margin: 0 auto;
    /* Used {frequency} times */
}}

'''
    
    css += '''/* Figma Text Styles */
'''
    # 収集済みテキストスタイルから、Figmaスタイル名由来のクラスを優先生成
    for class_name, style_info in collected_text_styles.items():
        if not class_name.startswith("figma-style-"):
            continue
        css += f'''.{class_name} {{
    font-family: {style_info["font_family"]};
    font-size: {style_info["font_size"]}px;
    font-weight: {style_info["font_weight"]};
    line-height: {style_info["line_height"]};
    letter-spacing: {style_info["letter_spacing"]}px;
    text-align: {style_info["text_align"]};
'''
        if style_info.get("text_decoration"):
            css += f"    text-decoration: {style_info['text_decoration']};\n"
        if style_info.get("text_transform"):
            css += f"    text-transform: {style_info['text_transform']};\n"
        if style_info.get("font_style"):
            css += f"    font-style: {style_info['font_style']};\n"
        if style_info.get("paragraph_spacing") is not None:
            css += f"    margin: 0 0 {int(style_info['paragraph_spacing'])}px 0;\n"
        else:
            css += "    margin: 10px 0;\n"
        css += "}\n\n\n"
    
    css += '''/* Semantic Component Styles */
.hero {
    padding: 80px 0;
    text-align: center;
}

.btn, .btn--primary, .btn--secondary {
    display: inline-block;
    padding: 12px 24px;
    border-radius: 4px;
    text-decoration: none;
    font-weight: 500;
    cursor: pointer;
    border: none;
}

.btn--primary {
    background-color: #007bff;
    /* color inherited from Figma data */
}

.btn--secondary {
    background-color: #6c757d;
    /* color inherited from Figma data */
}

.card {
    background: white;
    border-radius: 8px;
    padding: 20px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    margin: 10px 0;
}

.title, .heading {
    margin: 20px 0 10px 0;
    line-height: 1.2;
}

.img, .logo, .icon {
    display: block;
    max-width: 100%;
    height: auto;
}

.nav {
    display: flex;
    align-items: center;
    padding: 10px 0;
}

.menu {
    display: flex;
    list-style: none;
    margin: 0;
    padding: 0;
    gap: 20px;
}

.footer {
    background-color: #f8f9fa;
    padding: 40px 0;
    margin-top: 40px;
}

/* Layer-based classes (preserving Figma layer names) */
[class^="layer-"] {
    display: block;
}

/* Layout Structure Classes */
.layout-2col {
    display: flex;
    gap: 20px;
}

.layout-flex-row.layout-2col-equal > * {
    flex: 1;
}

.layout-flex-row.layout-2col-1-2 > *:first-child {
    flex: 1;
}

.layout-flex-row.layout-2col-1-2 > *:last-child {
    flex: 2;
}

.layout-flex-row.layout-2col-1-3 > *:first-child {
    flex: 1;
}

.layout-flex-row.layout-2col-1-3 > *:last-child {
    flex: 3;
}

.layout-flex-row.layout-2col-2-3 > *:first-child {
    flex: 2;
}

.layout-flex-row.layout-2col-2-3 > *:last-child {
    flex: 3;
}

.layout-flex-row.layout-2col-3-4 > *:first-child {
    flex: 3;
}

.layout-flex-row.layout-2col-3-4 > *:last-child {
    flex: 4;
}

.layout-3col {
    display: flex;
    gap: 20px;
}

.layout-3col-equal > * {
    flex: 1;
}

.layout-3col > * {
    flex: 1;
}

.layout-4col {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 20px;
}

.layout-image-text {
    display: flex;
    align-items: flex-start;
    gap: 40px;
}

.layout-text-image {
    display: flex;
    flex-direction: row-reverse;
    align-items: flex-start;
    gap: 40px;
}

/* Image-text layout child constraints */
.layout-image-text > .img,
.layout-image-text > [class*="img"],
.layout-text-image > .img,
.layout-text-image > [class*="img"] {
    flex: 0 0 320px;
    max-width: 320px;
}

.layout-image-text > *:not(.img):not([class*="img"]),
.layout-text-image > *:not(.img):not([class*="img"]) {
    flex: 1 1 auto;
    min-width: 0;
}

.layout-image-gallery {
    display: flex;
    gap: 15px;
}

.layout-flex-row {
    display: flex;
    flex-direction: row;
    gap: 15px;
}

.layout-flex-col {
    display: flex;
    flex-direction: column;
    gap: 15px;
}

/* Responsive Layout */
@media (max-width: 768px) {
    .layout-2col,
    .layout-3col,
    .layout-4col,
    .layout-image-text,
    .layout-text-image {
        flex-direction: column;
    }
    .layout-flex-row.layout-2col-1-2 > *,
    .layout-flex-row.layout-2col-1-3 > *,
    .layout-flex-row.layout-2col-2-3 > *,
    .layout-flex-row.layout-2col-3-4 > *,
    .layout-2col-1-2 > *,
    .layout-2col-1-3 > *,
    .layout-2col-2-3 > *,
    .layout-2col-3-4 > * {
        flex: 1 1 auto;
        min-width: 0;
        width: auto;
    }
    .layout-3col > * { width: 100%; max-width: 100%; flex: 1 1 auto; }
    .layout-4col { grid-template-columns: 1fr; }
}

/* Collected text styles (fallback) */
'''
    
    # 収集されたテキストスタイルごとにCSSクラスを生成（Figmaスタイル以外）
    for class_name, style_info in collected_text_styles.items():
        # Figmaスタイルクラスは既に上で生成済みなのでスキップ
        if class_name.startswith("figma-style-"):
            continue
        css += f'''.{class_name} {{
    font-family: {style_info["font_family"]};
    font-size: {style_info["font_size"]}px;
    font-weight: {style_info["font_weight"]};
    line-height: {style_info["line_height"]};
    letter-spacing: {style_info["letter_spacing"]}px;
    text-align: {style_info["text_align"]};
'''
        # Figmaスタイルが併用される要素は、こちらでは色を出さずfigma-style側に委譲
        if not style_info.get("figma_style_name"):
            css += f'''    color: {style_info["color"]};
'''
        if style_info.get("text_decoration"):
            css += f"    text-decoration: {style_info['text_decoration']};\n"
        if style_info.get("text_transform"):
            css += f"    text-transform: {style_info['text_transform']};\n"
        if style_info.get("font_style"):
            css += f"    font-style: {style_info['font_style']};\n"
        if style_info.get("paragraph_spacing") is not None:
            css += f"    margin: 0 0 {int(style_info['paragraph_spacing'])}px 0;\n"
        else:
            css += "    margin: 10px 0;\n"
        css += "}\n\n\n"
    
    # Auto Layout内の見出し/段落は余白をgapで管理するため、既定marginをリセット
    css += (
        ".layout-flex-col h1, .layout-flex-col h2, .layout-flex-col h3, .layout-flex-col h4, .layout-flex-col h5, .layout-flex-col h6, .layout-flex-col p,\n"
        ".layout-flex-row h1, .layout-flex-row h2, .layout-flex-row h3, .layout-flex-row h4, .layout-flex-row h5, .layout-flex-row h6, .layout-flex-row p {\n"
        "  margin: 0;\n"
        "}\n\n"
    )

    css += '''/* Rectangle styles */
.rect-element {
    margin: 10px 0;
    border-radius: 4px;
}

/* Image placeholder styles */
.image-placeholder {
    margin: 10px 0;
    border-radius: 4px;
    overflow: hidden;
    background-color: #f5f5f5;
    border: 1px solid #ddd;
}

.image-placeholder img {
    display: block;
    transition: opacity 0.3s ease;
}

.image-placeholder:hover img {
    opacity: 0.8;
}

/* Responsive */
@media (max-width: 768px) {
    .container {
        padding: 0 15px;
    }
    
    section {
        padding: 20px 0;
    }
    
    /* Responsive font sizes */
'''
    
    # レスポンシブフォントサイズ
    for class_name, style_info in collected_text_styles.items():
        font_size = style_info["font_size"]
        responsive_size = max(12, int(font_size * 0.9))  # 最小12px
        css += f'''    .{class_name} {{
        font-size: {responsive_size}px;
    }}
    
'''
    
    css += '''}
'''

    # Two-column stability helpers
    css += ".layout-2col > * { min-width: 0; }\n"
    css += ".layout-2col { align-items: stretch; }\n.layout-2col > :first-child { flex-shrink: 0; }\n"
    css += ".layout-2col > :first-child img { max-width: 100%; width: auto; }\n\n"

    # Optional: equalize 2-col when no ratio is specified
    if EQUALIZE_2COL_FALLBACK:
        css += '.layout-2col > * { flex: 1 1 0; min-width: 0; }\n\n'

    # ノード固有スタイルを出力（インライン削減）
    css += '/* Node-specific styles (generated) */\n'
    node_styles = node_styles or {}
    for node_id, props in node_styles.items():
        safe_id = css_safe_identifier(node_id)
        props_str = ";\n    ".join(props)
        selectors = [f'.n-{safe_id}']
        try:
            if N_CLASS_ALIAS_MODE == 'add':
                alias = NODE_ALIAS_CANDIDATE.get(safe_id)
                if alias:
                    unique = (ALIAS_FREQ.get(alias, 0) == 1)
                    if N_CLASS_ALIAS_DROP_N_UNIQUE and unique:
                        selectors = [f'.{alias}']
                    else:
                        if (not N_CLASS_ALIAS_UNIQUE_ONLY) or unique:
                            selectors.append(f'.{alias}')
        except Exception:
            pass
        sel = ", ".join(selectors)
        css += f'''{sel} {{
    {props_str};
}}

'''

    # Generate utility classes CSS
    css += "\n/* Utility Classes (Generated) */\n"

    # Flexbox utilities
    css += """
/* Display */
.d-flex { display: flex; }
.d-block { display: block; }
.d-inline { display: inline; }
.d-inline-block { display: inline-block; }
.d-grid { display: grid; }
.d-none { display: none; }

/* Flex Direction */
.flex-row { flex-direction: row; }
.flex-col { flex-direction: column; }

/* Justify Content */
.justify-start { justify-content: flex-start; }
.justify-end { justify-content: flex-end; }
.justify-center { justify-content: center; }
.justify-between { justify-content: space-between; }
.justify-around { justify-content: space-around; }

/* Align Items */
.align-start { align-items: flex-start; }
.align-end { align-items: flex-end; }
.align-center { align-items: center; }
.align-stretch { align-items: stretch; }

/* Border Radius */
.rounded__4 { border-radius: 4px; }
.rounded__8 { border-radius: 8px; }
.rounded__12 { border-radius: 12px; }
.rounded__16 { border-radius: 16px; }

/* Box Shadow */
.shadow { box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06); }

/* Image-Text Layout Patterns */
.image-text-layout {
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    gap: 20px;
}

.text-image-layout {
    display: flex;
    flex-direction: row-reverse;
    align-items: flex-start;
    gap: 20px;
}

.image-text-layout > .img,
.image-text-layout > [class*="img"],
.image-text-layout > .rectangle {
    flex-shrink: 0;
    max-width: 40%;
}

.text-image-layout > .img,
.text-image-layout > [class*="img"],
.text-image-layout > .rectangle {
    flex-shrink: 0;
    max-width: 40%;
}

"""

    # Dynamic width/height utilities from UTILITY_CLASS_CACHE
    if UTILITY_CLASS_CACHE:
        for cache_key, class_name in UTILITY_CLASS_CACHE.items():
            property_type, value, direction = cache_key.split(":", 2)

            if property_type == "width" and value.endswith("px"):
                px_value = value.replace("px", "")
                css += f".w__{px_value} {{ width: {value}; }}\n"
            elif property_type == "height" and value.endswith("px"):
                px_value = value.replace("px", "")
                css += f".h__{px_value} {{ height: {value}; }}\n"
            elif property_type == "padding" and value.endswith("px"):
                px_value = value.replace("px", "")
                css += f".p__{px_value} {{ padding: {value}; }}\n"

    # Final responsive overrides (placed after node-specific styles; no !important needed)
    css += (
        "@media (max-width: 768px) {\n"
        "  .layout-2col, .layout-3col, .layout-4col, .layout-image-text, .layout-text-image { flex-direction: column; }\n"
        "  .layout-flex-row.layout-2col-1-2 > *, .layout-flex-row.layout-2col-1-3 > *, .layout-flex-row.layout-2col-2-3 > *, .layout-flex-row.layout-2col-3-4 > *,\n"
        "  .layout-2col-1-2 > *, .layout-2col-1-3 > *, .layout-2col-2-3 > *, .layout-2col-3-4 > * { flex: 1 1 auto; min-width: 0; width: auto; }\n"
        "  .layout-3col > * { width: 100%; max-width: 100%; flex: 1 1 auto; }\n"
        "  [class^=\"n-\"], [class*=\" n-\"] { max-width:100%; height:auto; min-height:0; box-sizing:border-box; }\n"
        "}\n"
    )

    # Post-process: 画像+テキストレイアウトコンテナのmin-width:0を除去
    css = fix_image_text_layout_sizing(css)

    return css

def add_fixed_width_class_if_needed(classes):
    """固定幅クラス(w__XXX)がある場合にfixed-widthクラスを追加"""
    if any(cls.startswith('w__') for cls in classes):
        if 'fixed-width' not in classes:
            classes.append('fixed-width')
    return classes

def fix_image_text_layout_sizing(css):
    """Auto Layoutの想定外挙動を起こすmin-width:0を除去し、固定幅要素のflex制御を追加"""
    import re

    lines = css.split('\n')
    fixed_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # CSSクラス定義の開始を検出（.で始まり{を含む行）
        if line.strip().startswith('.') and '{' in line:
            class_content = []
            j = i
            brace_count = 0

            # クラス定義全体を取得
            while j < len(lines):
                class_content.append(lines[j])
                brace_count += lines[j].count('{')
                brace_count -= lines[j].count('}')
                j += 1
                if brace_count == 0:
                    break

            class_css = '\n'.join(class_content)

            # 以下の場合にmin-width:0を除去:
            # 1. flex-direction:row + gap を持つコンテナ
            # 2. 固定幅(width: XXpx)を持つ要素
            # 3. flex-direction:row コンテナ内の子要素（テキスト側含む）

            has_row = 'flex-direction:row' in class_css
            has_gap = ('gap:40px' in class_css or 'gap:20px' in class_css or 'gap:24px' in class_css)
            has_fixed_width = re.search(r'width:\s*\d+(\.\d+)?px', class_css)
            has_flex_column = 'flex-direction:column' in class_css

            should_remove_min_width = (
                (has_row and has_gap) or  # 横並びコンテナ
                has_fixed_width or        # 固定幅要素
                (has_flex_column and 'width:auto' in class_css)  # テキスト側縦並びコンテナ
            )

            if should_remove_min_width:
                # min-width:0を除去
                fixed_class_content = []
                for content_line in class_content:
                    if 'min-width:0;' in content_line:
                        # min-width:0を除去
                        fixed_line = content_line.replace('min-width:0;', '')
                        # 空行にならないよう調整
                        if fixed_line.strip() and fixed_line.strip() != ';':
                            fixed_class_content.append(fixed_line)
                        elif content_line.strip() != 'min-width:0;':
                            # min-width:0以外の内容があれば追加
                            fixed_class_content.append(fixed_line)
                    else:
                        fixed_class_content.append(content_line)

                fixed_lines.extend(fixed_class_content)
            else:
                fixed_lines.extend(class_content)

            i = j
        else:
            fixed_lines.append(line)
            i += 1

    # 固定幅要素のflex制御を追加
    css_result = '\n'.join(fixed_lines)
    css_result += '\n\n/* 固定幅要素のflex制御 (Auto Layout幅保持) */\n'
    css_result += '.fixed-width {\n'
    css_result += '    flex-shrink: 0;\n'
    css_result += '}\n\n'
    css_result += '/* SP: レスポンシブ性を優先 */\n'
    css_result += '@media (max-width: 768px) {\n'
    css_result += '    .fixed-width {\n'
    css_result += '        flex-shrink: 1;\n'
    css_result += '        max-width: 100%;\n'
    css_result += '    }\n'
    css_result += '}\n'

    return css_result

def build_node_style_report(out_dir):
    try:
        os.makedirs(out_dir, exist_ok=True)
        report = {
            "scope": NODE_STYLE_SCOPE,
            "totals": {
                "nodes": len(collected_node_styles or {}),
                "by_kind": {},
                "issues": {
                    "non_text_color": 0
                }
            },
            "issues": {
                "non_text_color": []
            }
        }
        # Aggregate by kind
        kind_counts = {}
        for node_id in (collected_node_styles or {}).keys():
            safe_id = css_safe_identifier(node_id)
            k = NODE_KIND_MAP.get(safe_id, 'unknown')
            kind_counts[k] = kind_counts.get(k, 0) + 1
        report["totals"]["by_kind"] = kind_counts
        # Detect color on non-text nodes (could cascade)
        for node_id, props in (collected_node_styles or {}).items():
            safe_id = css_safe_identifier(node_id)
            kind = NODE_KIND_MAP.get(safe_id, 'unknown')
            if kind != 'text':
                for p in props:
                    if isinstance(p, str) and p.strip().lower().startswith('color:'):
                        report["totals"]["issues"]["non_text_color"] += 1
                        report["issues"]["non_text_color"].append({
                            "node_id": node_id,
                            "safe_id": safe_id,
                            "kind": kind,
                            "prop": p
                        })
                        break
        path = os.path.join(out_dir, 'node_style_report.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Node style report saved: {path}")
    except Exception as e:
        print(f"[WARN] Failed to write node style report: {e}")

def build_alias_report(out_dir):
    try:
        os.makedirs(out_dir, exist_ok=True)
        report = {
            "mode": N_CLASS_ALIAS_MODE,
            "source": N_CLASS_ALIAS_SOURCE,
            "unique_only": N_CLASS_ALIAS_UNIQUE_ONLY,
            "drop_n_unique": N_CLASS_ALIAS_DROP_N_UNIQUE,
            "unique_count": sum(1 for a, c in ALIAS_FREQ.items() if c == 1),
            "duplicates": {a: c for a, c in ALIAS_FREQ.items() if c > 1},
            "map": NODE_ALIAS_CANDIDATE,
        }
        path = os.path.join(out_dir, 'alias_map.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Alias map saved: {path}")
    except Exception as e:
        print(f"[WARN] Failed to write alias map: {e}")

def _css_defined_classes_from_file(path):
    try:
        if not os.path.exists(path):
            return set()
        txt = open(path, 'r', encoding='utf-8', errors='ignore').read()
        import re
        classes = set()
        for m in re.finditer(r"\.[a-zA-Z0-9_-]+\s*\{", txt):
            sel = m.group(0)
            name = sel.split('{', 1)[0].strip()
            name = name.lstrip('.')
            classes.add(name)
        return classes
    except Exception:
        return set()

def _html_used_classes_from_file(path):
    try:
        if not os.path.exists(path):
            return set()
        txt = open(path, 'r', encoding='utf-8', errors='ignore').read()
        import re
        used = set()
        for m in re.finditer(r'class="([^"]+)"', txt):
            for c in m.group(1).split():
                used.add(c.strip())
        return used
    except Exception:
        return set()

def _has_visible_fill(node):
    try:
        fills = (node.get('fills') or [])
        for f in fills:
            if not isinstance(f, dict):
                continue
            if f.get('visible') is False:
                continue
            t = f.get('type')
            if t in ('SOLID', 'GRADIENT_LINEAR', 'GRADIENT_RADIAL', 'GRADIENT_ANGULAR', 'GRADIENT_DIAMOND', 'IMAGE'):
                # opacity checks (best-effort)
                if float(f.get('opacity', 1) or 1) <= 0:
                    continue
                color = f.get('color') or {}
                if isinstance(color, dict) and float(color.get('a', 1) or 1) <= 0:
                    continue
                return True
    except Exception:
        pass
    return False

def _child_count(node):
    try:
        kids = node.get('children') or []
        cnt = 0
        for ch in kids:
            if isinstance(ch, dict) and not should_exclude_node(ch):
                cnt += 1
        return cnt
    except Exception:
        return 0

def build_waste_report(out_dir, sections, node_styles, combined_html=None, css_paths=None):
    try:
        os.makedirs(out_dir, exist_ok=True)
        node_styles = node_styles or {}
        shallow = []
        zero_prop_n = []
        used = set()
        defined = set()
        if combined_html:
            used = _html_used_classes_from_file(combined_html)
        css_paths = css_paths or []
        for p in css_paths:
            defined |= _css_defined_classes_from_file(p)

        # zero-prop .n- classes (by generation data)
        for node_id, props in node_styles.items():
            if not props:
                zero_prop_n.append(f"n-{css_safe_identifier(node_id)}")

        # shallow wrappers (FRAME with one child and no signals)
        def scan(node):
            if not isinstance(node, dict):
                return
            if should_exclude_node(node):
                return
            t = (node.get('type') or '').upper()
            kids = node.get('children') or []
            if t in ('FRAME', 'GROUP') and kids:
                cnt = _child_count(node)
                if cnt == 1:
                    # signals from figma node
                    signals = []
                    if _has_visible_fill(node):
                        signals.append('fill')
                    if (node.get('strokes') or []):
                        signals.append('stroke')
                    if (node.get('effects') or []):
                        signals.append('effect')
                    if node.get('cornerRadius') or node.get('rectangleCornerRadii'):
                        signals.append('radius')
                    if node.get('clipsContent'):
                        signals.append('clip')
                    for k in ('paddingLeft','paddingRight','paddingTop','paddingBottom'):
                        try:
                            if float(node.get(k) or 0) > 0:
                                signals.append('padding')
                                break
                        except Exception:
                            pass
                    # signals from generated styles
                    nid = node.get('id')
                    safe = css_safe_identifier(nid) if nid else ''
                    props = node_styles.get(nid) or []
                    if props:
                        for p in props:
                            s = (p or '').strip().lower()
                            if s.startswith(('display:','flex-','gap:','align-','justify-','background','border','box-shadow','filter','backdrop-filter','mix-blend-mode','overflow','aspect-ratio','transform')):
                                signals.append('style')
                                break
                    if not signals:
                        shallow.append({
                            'id': nid,
                            'safe': safe,
                            'name': node.get('name'),
                            'type': t,
                            'reason': 'single-child-no-style',
                        })
            for ch in kids:
                scan(ch)

        for sec in (sections or []):
            scan(sec)

        # unused css/html classes
        # remove some known globals from consideration
        ignore = {'device-pc','device-sp','container','inner','content-width-container','full-width-container','bg-fullbleed','image-placeholder','rect-element','line','layout-item'}
        defined_eff = {c for c in defined if c not in ignore}
        used_eff = {c for c in used if c not in ignore}
        unused_css = sorted(list(defined_eff - used_eff))
        unused_html = sorted(list(used_eff - defined_eff))

        report = {
            'shallow_wrappers': shallow,
            'zero_prop_n_classes': zero_prop_n,
            'unused_css_classes': unused_css,
            'unused_html_classes': unused_html,
            'totals': {
                'shallow_wrappers': len(shallow),
                'zero_prop_n': len(zero_prop_n),
                'unused_css': len(unused_css),
                'unused_html': len(unused_html),
            }
        }
        out = os.path.join(out_dir, 'waste_report.json')
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Waste report saved: {out}")
    except Exception as e:
        print(f"[WARN] Failed to write waste report: {e}")

def prune_unused_css(html_path: str, css_path: str, out_path: str):
    try:
        used = _html_used_classes_from_file(html_path)
        if not os.path.exists(css_path):
            return False
        css = open(css_path, 'r', encoding='utf-8', errors='ignore').read()
        import re
        out_lines = []
        i = 0
        n = len(css)
        # Very naive parser: drop simple top-level class rules whose all selectors are unused.
        # Keep @-blocks and complex rules intact.
        rule_re = re.compile(r"(^|\n)(\.[a-zA-Z0-9_-][^{]+)\{([^}]*)\}")
        last = 0
        removed = 0
        for m in rule_re.finditer(css):
            start, end = m.start(0), m.end(0)
            # write chunk before
            out_lines.append(css[last:start])
            selectors = m.group(2).strip()
            body = m.group(3)
            # Check each selector separated by ,
            sels = [s.strip() for s in selectors.split(',')]
            # Only consider pure class selectors
            def sel_used(s):
                if not s.startswith('.'):
                    return True  # keep non-class complex selectors
                cname = s[1:].strip()
                return cname in used
            keep = any(sel_used(s) for s in sels)
            if keep:
                out_lines.append(m.group(0))
            else:
                removed += 1
            last = end
        out_lines.append(css[last:])
        pruned = ''.join(out_lines)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(pruned)
        print(f"[LOG] CSS pruned: removed {removed} simple class rules -> {out_path}")
        return True
    except Exception as e:
        print(f"[WARN] CSS prune failed: {e}")
        return False

# テキストスタイル収集用辞書
collected_text_styles = {}
# ノードごとのスタイルをCSSに出力するための収集
collected_node_styles = {}
COLLECT_NODE_STYLES = True

def merge_css_props(existing_props, new_props):
    """CSS プロパティリストをマージし、重複を防ぐ
    後の値が優先される（CSSの仕様に従う）
    """
    if not existing_props:
        return new_props[:]
    if not new_props:
        return existing_props[:]
    
    # プロパティ名で重複をチェック
    prop_dict = {}
    
    # 既存のプロパティを辞書に格納
    for prop in existing_props:
        if ':' in prop:
            prop_name = prop.split(':', 1)[0].strip().lower()
            prop_dict[prop_name] = prop
    
    # 新しいプロパティで上書き
    for prop in new_props:
        if ':' in prop:
            prop_name = prop.split(':', 1)[0].strip().lower()
            prop_dict[prop_name] = prop
    
    return list(prop_dict.values())

def add_node_styles(node_id, style_props):
    """ノード固有スタイルを収集（後でCSSへ出力）
    style_props: ['width:100px', 'min-height:200px', ...]
    """
    global collected_node_styles
    if not COLLECT_NODE_STYLES:
        return
    if not node_id:
        return
    # Filtering based on node kind and scope
    safe_id = css_safe_identifier(node_id)
    kind = NODE_KIND_MAP.get(safe_id, None)

    def allowed(prop: str) -> bool:
        if not prop:
            return False
        p = prop.strip().lower()
        scope = NODE_STYLE_SCOPE
        # Always allow these basics
        always = (
            p.startswith('display:') or p.startswith('flex-') or p.startswith('justify-') or p.startswith('align-') or
            p.startswith('gap:') or p.startswith('padding') or p.startswith('overflow:') or
            (p.startswith('width:') and not SUPPRESS_CONTAINER_WIDTH) or
            (p.startswith('min-width:') and not SUPPRESS_CONTAINER_WIDTH) or
            p.startswith('max-width:') or
            p.startswith('height:') or p.startswith('min-height:') or p.startswith('max-height:') or
            p.startswith('transform:') or p.startswith('transform-origin')
        )
        if always:
            return True
        if scope == 'aggressive':
            return True
        # Block 'color' cascading on non-text
        if p.startswith('color:') and kind != 'text':
            return False
        if scope == 'standard':
            return True
        # conservative
        if kind == 'text':
            # only text-specific cosmetics
            return (
                p.startswith('color:') or p.startswith('text-decoration') or p.startswith('text-transform') or
                p.startswith('font-style') or p.startswith('margin:')
            )
        # containers / rects / image / line: allow visuals but not text color
        return (
            p.startswith('background') or p.startswith('border') or p.startswith('box-shadow') or
            p.startswith('filter') or p.startswith('backdrop-filter') or p.startswith('mix-blend-mode') or
            p.startswith('aspect-ratio') or
            p.startswith('width') or p.startswith('height') or p.startswith('min-width') or p.startswith('min-height') or
            p.startswith('overflow') or p.startswith('transform') or p.startswith('transform-origin')
        )

    filtered = []
    for prop in style_props:
        if allowed(prop):
            if prop not in filtered:
                filtered.append(prop)

    if not filtered:
        return

    bucket = collected_node_styles.get(node_id, [])
    for prop in filtered:
        if prop and prop not in bucket:
            bucket.append(prop)
    collected_node_styles[node_id] = bucket

def collect_text_styles_from_element(element, figma_styles=None):
    """要素からテキストスタイルを収集"""
    if should_exclude_node(element):
        return
    if element.get("type") == "TEXT":
        style_info = extract_text_styles(element, figma_styles)
        element_name = element.get("name", "")
        element_id = element.get("id", "")
        class_name = generate_text_class(style_info, element_name, element_id)
        collected_text_styles[class_name] = style_info
        # Figmaスタイル名がある場合は、そのクラスも同時に収集
        if style_info.get("figma_style_name"):
            figma_class = style_info["figma_style_name"].lower().replace(" ", "-").replace("/", "-")
            collected_text_styles[f"figma-style-{figma_class}"] = style_info
    
    # 子要素も再帰的に処理
    for child in element.get("children", []):
        collect_text_styles_from_element(child, figma_styles)
    # フォールバック検出のelements配列にも対応
    for child in element.get("elements", []):
        collect_text_styles_from_element(child, figma_styles)

# 全セクションからテキストスタイルを事前収集
print("[LOG] テキストスタイルを収集中...")
for i, section_summary in enumerate(layout_structure["sections_summary"]):
    section_data = sections[i] if i < len(sections) else {}
    collect_text_styles_from_element(section_data, layout_structure.get("figma_styles"))

print(f"[LOG] 収集されたユニークなテキストスタイル数: {len(collected_text_styles)}")

# 各セクションのHTML生成
all_sections_html = ""
for i, section_summary in enumerate(layout_structure["sections_summary"]):
    # 実際のセクションデータを取得（簡略版）
    section_data = sections[i] if i < len(sections) else {}
    # 現在のセクションインデックス（見出しポリシー用）
    try:
        CURRENT_SECTION_INDEX = i
    except Exception:
        CURRENT_SECTION_INDEX = i
    section_html = generate_html_for_section(section_data, layout_structure["wrapper_width"])
    all_sections_html += section_html + "\n"
    
    print(f"[LOG] Section {i+1} HTML generated: {section_summary['name']}")

# ファイル名をFigmaフレーム名から生成
frame_name = layout_structure["frame_name"]
safe_frame_name = sanitize_filename(frame_name)

# 完全なHTMLドキュメントの生成
full_html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{layout_structure["project_name"]} - {layout_structure["frame_name"]}</title>
    <link rel="stylesheet" href="{safe_frame_name}{PC_SUFFIX}.css">
</head>
<body>
{all_sections_html}
</body>
</html>'''

# index.html用（style.cssを参照）
index_html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{layout_structure["project_name"]} - {layout_structure["frame_name"]}</title>
    <link rel="stylesheet" href="style{PC_SUFFIX}.css">
</head>
<body>
{all_sections_html}
</body>
</html>'''

# ファイル出力
html_file = os.path.join(project_dir, f"{safe_frame_name}{PC_SUFFIX}.html")
css_file = os.path.join(project_dir, f"{safe_frame_name}{PC_SUFFIX}.css")  
structure_file = os.path.join(project_dir, f"{safe_frame_name}{PC_SUFFIX}_structure.json")
index_file = os.path.join(project_dir, f"index{PC_SUFFIX}.html")
style_file = os.path.join(project_dir, f"style{PC_SUFFIX}.css")

PC_NODE_STYLES = dict(collected_node_styles)

if not SINGLE_HTML_ONLY:
    # フレーム名ベースのファイル生成（オプション）
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(full_html)
    with open(css_file, "w", encoding="utf-8") as f:
        f.write(generate_css(layout_structure, collected_text_styles, PC_NODE_STYLES))
    with open(structure_file, "w", encoding="utf-8") as f:
        json.dump(layout_structure, f, ensure_ascii=False, indent=2)
    with open(index_file, "w", encoding="utf-8") as f:
        f.write(index_html)
    with open(style_file, "w", encoding="utf-8") as f:
        f.write(generate_css(layout_structure, collected_text_styles, PC_NODE_STYLES))
    print(f"[LOG] Frame-based HTML file saved: {html_file}")
    print(f"[LOG] Frame-based CSS file saved: {css_file}")
    print(f"[LOG] Structure data saved: {structure_file}")
    print(f"[LOG] Index HTML file saved: {index_file}")
    print(f"[LOG] Index CSS file saved: {style_file}")
    print("[LOG] レイアウト解析とHTML生成が完了しました！")

# 保存したPC情報を後で結合用に保持
PC_SECTIONS = sections
PC_LAYOUT_STRUCTURE = layout_structure
PC_COLLECTED_TEXT_STYLES = collected_text_styles
PC_SAFE_FRAME_NAME = safe_frame_name
PC_PROJECT_DIR = project_dir

# SPが無い場合でも単一HTML/CSSを出力（PCのみ）
if SINGLE_HTML and not SP_FRAME_NODE_ID:
    combined_dir = os.path.join(OUTPUT_DIR, safe_project_name)
    os.makedirs(combined_dir, exist_ok=True)

    # 画像パスを結合用に再マッピング（PCは <pc_frame>/images）
    pc_image_map = {}
    for section in PC_SECTIONS:
        for el in get_all_child_elements(section):
            nid = el.get('id')
            if not nid:
                continue
            safe_id = css_safe_identifier(nid) if nid else ""
            pc_image_map[nid] = f"images/{safe_id}.{IMAGE_FORMAT}"

    # PCセクションHTML生成（結合用）
    IMAGE_URL_MAP = pc_image_map
    pc_sections_html = ""
    for i, section_summary in enumerate(PC_LAYOUT_STRUCTURE["sections_summary"]):
        section_data = PC_SECTIONS[i] if i < len(PC_SECTIONS) else {}
        pc_sections_html += generate_html_for_section(section_data, PC_LAYOUT_STRUCTURE["wrapper_width"]) + "\n"

    combined_html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{PC_LAYOUT_STRUCTURE["project_name"]}</title>
    <link rel="stylesheet" href="style-pc.css" media="(min-width: 769px)">
</head>
<body>
  <div class="device-pc">
{pc_sections_html}
  </div>
</body>
</html>'''

    combined_html_file = os.path.join(combined_dir, "index.html")
    combined_css_file = os.path.join(combined_dir, "style-pc.css")
    # Write HTML first (always)
    with open(combined_html_file, "w", encoding="utf-8") as f:
        f.write(combined_html)
    # Build CSS with failsafe
    try:
        pc_css = generate_css(PC_LAYOUT_STRUCTURE, PC_COLLECTED_TEXT_STYLES)
        # Core first, then clamp (so clamp wins over node-specific widths)
        combined_css = (
            "/* Device visibility */\n"
            ".device-pc { display: block; }\n"
            ".device-sp { display: none; }\n\n"
            "@media (max-width: 768px) {\n"
            "  .device-pc { display: block; }\n"
            "}\n\n"
            "/* Base image rule */\n"
            "img { max-width: 100%; height: auto; display: block; }\n\n"
            "/* PC styles (core) */\n"
            + pc_css +
            "\n\n/* PC clamp to prevent overflow (overrides core) */\n"
            ".device-pc, .device-pc * { box-sizing: border-box; }\n"
            ".device-pc [class^=\"n-\"], .device-pc [class*=\" n-\"] { max-width: 100%; }\n"
            ".device-pc img { max-width: 100%; height: auto; display: block; }\n\n"
            + (".device-pc [class^=\\\"n-\\\"], .device-pc [class*=\\\" n-\\\"] { width: 100%; }\n\n" if PC_STRICT_CLAMP else "")
        )
    except Exception as e:
        print(f"[WARN] CSS generation (PC-only) failed: {e}")
        combined_css = (
            "/* Fallback CSS */\n"
            "html, body { margin:0; padding:0; overflow-x:hidden; }\n"
            ".device-pc { display:block; } .device-sp { display:none; }\n"
            "img { max-width:100%; height:auto; display:block; }\n"
        )
    with open(combined_css_file, "w", encoding="utf-8") as f:
        f.write(combined_css)
    print(f"[LOG] Combined (PC only) HTML saved: {combined_html_file}")
    print(f"[LOG] Combined (PC only) CSS saved: {combined_css_file}")
    # Write validation report
    try:
        build_node_style_report(combined_dir)
        build_alias_report(combined_dir)
        try:
            build_waste_report(combined_dir, PC_SECTIONS, PC_NODE_STYLES, combined_html_file, [combined_css_file])
        except Exception as e:
            print(f"[WARN] Waste report (PC only) failed: {e}")
    except Exception as e:
        print(f"[WARN] Report generation failed: {e}")
 

# =============================
# Optional: SP Frame Processing
# =============================
if SP_FRAME_NODE_ID:
    print("[LOG] === SPフレーム解析を開始します ===")
    # SP用のファイルJSONを取得（PCと別ファイルでも対応）
    if SP_INPUT_JSON_FILE:
        print(f"[LOG] Using local JSON file (SP): {SP_INPUT_JSON_FILE}")
        sp_file_data = load_local_json(SP_INPUT_JSON_FILE)
    else:
        if OFFLINE_MODE:
            print("[WARN] OFFLINE_MODE=true ですが SP_INPUT_JSON_FILE が未指定のため、SP解析をスキップします。")
            sp_file_data = None
        else:
            sp_file_data = fetch_file_json(SP_FILE_KEY)
    if not sp_file_data:
        sp_frame = None
        print("[LOG] SP解析はスキップされました（ローカルJSONなし）")
    else:
        figma_styles_sp = extract_figma_styles(sp_file_data)
        sp_frame = find_node_by_id(sp_file_data["document"], SP_FRAME_NODE_ID)
        if not sp_frame:
            print(f"[WARN] SPフレームID {SP_FRAME_NODE_ID} が見つかりませんでした。スキップします。")
            # 何もせず抜ける
            sp_frame = None
    if sp_frame:
        target_frame = sp_frame
        print(f"[LOG] SP Frame found: {target_frame.get('name', 'Unnamed')}")
        ROOT_FRAME_BOUNDS = target_frame.get("absoluteBoundingBox", {}) or {}
        ROOT_CHILD_IDS = {c.get('id') for c in (target_frame.get('children') or []) if isinstance(c, dict)}

        # Phase 1 for SP: 構造解析
        print("[LOG] === SP Phase 1: 構造解析開始 ===")
        sections = detect_sections_by_frames(target_frame)
        if not sections:
            print("[LOG] SP: フレーム構造でのセクション検出に失敗。Y座標による分割を実行...")
            sections = detect_sections_by_position(target_frame)

        print(f"[LOG] SP: 検出されたセクション数: {len(sections)}")

        # 幅パターン分析
        all_widths = []
        for i, section in enumerate(sections):
            section_widths = analyze_section_widths(section)
            all_widths.extend(section_widths)

        width_patterns = identify_width_patterns(all_widths)
        classified_patterns = classify_width_patterns(width_patterns)

        primary_content_width = 1200
        primary_full_width = 1920
        if classified_patterns["content_width"]:
            primary_content_width = classified_patterns["content_width"][0][0]
        if classified_patterns["full_width"]:
            primary_full_width = classified_patterns["full_width"][0][0]

        wrapper_width = primary_content_width

        layout_structure = {
            "project_name": sp_file_data.get("name", "Unknown_Project"),
            "frame_name": target_frame.get("name", "Unknown_Frame"),
            "wrapper_width": wrapper_width,
            "primary_content_width": primary_content_width,
            "primary_full_width": primary_full_width,
            "width_patterns": classified_patterns,
            "figma_styles": figma_styles_sp,
            "total_sections": len(sections),
            "sections_summary": [
                {
                    "id": section.get("id", f"pos_{i}"),
                    "name": section.get("name", f"Section_{i+1}"),
                    "type": section.get("type", "unknown"),
                    "bounds": section.get("absoluteBoundingBox", {})
                }
                for i, section in enumerate(sections)
            ]
        }

        # Phase 2 for SP: 出力準備
        safe_project_name = sanitize_filename(layout_structure["project_name"])
        sp_safe_frame_name = sanitize_filename(layout_structure["frame_name"])
        project_dir = os.path.join(OUTPUT_DIR, safe_project_name, sp_safe_frame_name)
        os.makedirs(project_dir, exist_ok=True)
        print(f"[LOG] SP Output directory created: {project_dir}")

        # 画像エクスポート
        IMAGE_URL_MAP = {}
        if USE_IMAGES:
            try:
                image_ids = collect_image_node_ids(target_frame)
                print(f"[LOG] SP Image nodes detected: {len(image_ids)}")
                # 共通のimagesディレクトリを使用（OUTPUT_DIRの直下）
                base_output_dir = os.path.join(OUTPUT_DIR, os.path.basename(os.path.dirname(project_dir)))
                images_dir = os.path.join(base_output_dir, "images")
                if USE_LOCAL_IMAGES_ONLY:
                    # オフライン/ローカル参照のみ: 既存ファイルがあればそれをマッピング（_spサフィックス）
                    tmp_map = {}
                    for nid in image_ids:
                        if not nid:
                            continue
                        safe_id = css_safe_identifier(nid)
                        filename = f"{safe_id}_sp.{IMAGE_FORMAT}"
                        abs_path = os.path.join(images_dir, filename)
                        if os.path.exists(abs_path):
                            tmp_map[nid] = os.path.join("../images", filename)
                    IMAGE_URL_MAP = tmp_map
                    if not IMAGE_URL_MAP:
                        print("[LOG] No local SP images found; will use placeholders where needed.")
                else:
                    url_map = fetch_figma_image_urls(SP_FILE_KEY, list(image_ids), IMAGE_FORMAT, IMAGE_SCALE)
                    if DOWNLOAD_IMAGES:
                        IMAGE_URL_MAP = download_images(url_map, images_dir, IMAGE_FORMAT, "_sp")
                    else:
                        # ローカル優先、無ければCDN
                        tmp_map = {}
                        for nid, url in url_map.items():
                            if not nid or not url:
                                continue
                            safe_id = css_safe_identifier(nid)
                            filename = f"{safe_id}_sp.{IMAGE_FORMAT}"
                            abs_path = os.path.join(images_dir, filename)
                            if os.path.exists(abs_path):
                                tmp_map[nid] = os.path.join("../images", filename)
                            else:
                                tmp_map[nid] = url
                        IMAGE_URL_MAP = tmp_map
            except Exception as e:
                print(f"[WARN] SP Image export failed: {e}")
        else:
            print("[LOG] SP Image integration disabled (USE_IMAGES=false)")

        # SPテキストスタイル収集
        # 収集用のノードスタイルをリセット
        collected_node_styles = {}
        collected_text_styles_sp = {}

        def collect_sp(element):
            if element.get("type") == "TEXT":
                style_info = extract_text_styles(element, layout_structure.get("figma_styles"))
                element_name = element.get("name", "")
                element_id = element.get("id", "")
                class_name = generate_text_class(style_info, element_name, element_id)
                collected_text_styles_sp[class_name] = style_info
                if style_info.get("figma_style_name"):
                    figma_class = style_info["figma_style_name"].lower().replace(" ", "-").replace("/", "-")
                    collected_text_styles_sp[f"figma-style-{figma_class}"] = style_info
            for c in element.get("children", []) or []:
                collect_sp(c)
            for c in element.get("elements", []) or []:
                collect_sp(c)

        for i, section_summary in enumerate(layout_structure["sections_summary"]):
            section_data = sections[i] if i < len(sections) else {}
            collect_sp(section_data)

        # HTML生成
        all_sections_html = ""
        for i, section_summary in enumerate(layout_structure["sections_summary"]):
            section_data = sections[i] if i < len(sections) else {}
            section_html = generate_html_for_section(section_data, layout_structure["wrapper_width"])
            all_sections_html += section_html + "\n"
            print(f"[LOG] SP Section {i+1} HTML generated: {section_summary['name']}")

        SP_NODE_STYLES = dict(collected_node_styles)

        sp_full_html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{layout_structure["project_name"]} - {layout_structure["frame_name"]}</title>
    <link rel="stylesheet" href="{sp_safe_frame_name}{SP_SUFFIX}.css">
</head>
<body>
{all_sections_html}
</body>
</html>'''

        sp_index_html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{layout_structure["project_name"]} - {layout_structure["frame_name"]}</title>
    <link rel="stylesheet" href="style{SP_SUFFIX}.css">
</head>
<body>
{all_sections_html}
</body>
</html>'''

        # ファイル出力（SP）
        if not SINGLE_HTML_ONLY:
            sp_html_file = os.path.join(project_dir, f"{sp_safe_frame_name}{SP_SUFFIX}.html")
            sp_css_file = os.path.join(project_dir, f"{sp_safe_frame_name}{SP_SUFFIX}.css")
            sp_structure_file = os.path.join(project_dir, f"{sp_safe_frame_name}{SP_SUFFIX}_structure.json")
            sp_index_file = os.path.join(project_dir, f"index{SP_SUFFIX}.html")
            sp_style_file = os.path.join(project_dir, f"style{SP_SUFFIX}.css")

            with open(sp_html_file, "w", encoding="utf-8") as f:
                f.write(sp_full_html)
            # Build SP per-frame CSS: core first, then clamp overrides
            sp_core_css = generate_css(layout_structure, collected_text_styles_sp, SP_NODE_STYLES)
            sp_clamp_css = (
                "/* Base image rule */\n"
                "img { max-width: 100%; height: auto; display: block; }\n\n"
                "/* Clamp overrides (SP per-frame, no device wrapper) */\n"
                "[class^=\"n-\"], [class*=\" n-\"] { max-width: 100%; width: 100%; box-sizing: border-box; }\n"
            )
            with open(sp_css_file, "w", encoding="utf-8") as f:
                f.write(sp_core_css + "\n\n" + sp_clamp_css)
            with open(sp_structure_file, "w", encoding="utf-8") as f:
                json.dump(layout_structure, f, ensure_ascii=False, indent=2)
            with open(sp_index_file, "w", encoding="utf-8") as f:
                f.write(sp_index_html)
            with open(sp_style_file, "w", encoding="utf-8") as f:
                f.write(sp_core_css + "\n\n" + sp_clamp_css)

            print(f"[LOG] SP Frame-based HTML file saved: {sp_html_file}")
            print(f"[LOG] SP Frame-based CSS file saved: {sp_css_file}")
            print(f"[LOG] SP Structure data saved: {sp_structure_file}")
            print(f"[LOG] SP Index HTML file saved: {sp_index_file}")
            print(f"[LOG] SP Index CSS file saved: {sp_style_file}")
            print("[LOG] SPフレームのレイアウト解析とHTML生成が完了しました！")

        # 結合用にSP情報を保持
        SP_SECTIONS = sections
        SP_LAYOUT_STRUCTURE = layout_structure
        SP_COLLECTED_TEXT_STYLES = collected_text_styles_sp
        SP_SAFE_FRAME_NAME = sp_safe_frame_name
        SP_PROJECT_DIR = project_dir

        # =============================
        # Single HTML/CSS 結合出力
        # =============================
        if SINGLE_HTML:
            combined_dir = os.path.join(OUTPUT_DIR, safe_project_name)
            os.makedirs(combined_dir, exist_ok=True)

            # 画像パスを結合用に再マッピング（PCは <pc_frame>/images、SPは <sp_frame>/images）
            pc_image_map = {}
            for section in PC_SECTIONS:
                for el in get_all_child_elements(section):
                    nid = el.get('id')
                    if not nid:
                        continue
                    safe_id = css_safe_identifier(nid) if nid else ""
                    pc_image_map[nid] = f"images/{safe_id}.{IMAGE_FORMAT}"

            sp_image_map = {}
            for section in SP_SECTIONS:
                for el in get_all_child_elements(section):
                    nid = el.get('id')
                    if not nid:
                        continue
                    safe_id = css_safe_identifier(nid) if nid else ""
                    sp_image_map[nid] = f"images/{safe_id}_sp.{IMAGE_FORMAT}"

            # PCセクションHTML生成（結合用）
            COLLECT_NODE_STYLES = False
            IMAGE_URL_MAP = pc_image_map
            pc_sections_html = ""
            for i, section_summary in enumerate(PC_LAYOUT_STRUCTURE["sections_summary"]):
                section_data = PC_SECTIONS[i] if i < len(PC_SECTIONS) else {}
                try:
                    CURRENT_SECTION_INDEX = i
                except Exception:
                    CURRENT_SECTION_INDEX = i
                pc_sections_html += generate_html_for_section(section_data, PC_LAYOUT_STRUCTURE["wrapper_width"]) + "\n"

            # SPセクションHTML生成（結合用）
            IMAGE_URL_MAP = sp_image_map
            sp_sections_html = ""
            for i, section_summary in enumerate(SP_LAYOUT_STRUCTURE["sections_summary"]):
                section_data = SP_SECTIONS[i] if i < len(SP_SECTIONS) else {}
                try:
                    CURRENT_SECTION_INDEX = i
                except Exception:
                    CURRENT_SECTION_INDEX = i
                sp_sections_html += generate_html_for_section(section_data, SP_LAYOUT_STRUCTURE["wrapper_width"]) + "\n"

            # 単一HTML
            combined_html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{PC_LAYOUT_STRUCTURE["project_name"]}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="device-pc">
{pc_sections_html}
  </div>
  <div class="device-sp">
{sp_sections_html}
  </div>
</body>
</html>'''

            # Write combined HTML
            combined_html_file = os.path.join(combined_dir, "index.html")
            with open(combined_html_file, "w", encoding="utf-8") as f:
                f.write(combined_html)

            # Split CSS into PC/SP files
            pc_css_file = os.path.join(combined_dir, "style-pc.css")
            sp_css_file = os.path.join(combined_dir, "style-sp.css")
            try:
                pc_css_core = generate_css(PC_LAYOUT_STRUCTURE, PC_COLLECTED_TEXT_STYLES, PC_NODE_STYLES)
                # core first, then clamp so overrides win
                pc_css_full = (
                    "/* Device visibility (PC bundle) */\n"
                    ".device-pc { display: block; }\n"
                    ".device-sp { display: none; }\n\n"
                    "/* Global overflow guard */\n"
                    "html, body { overflow-x: hidden; }\n\n"
                    "/* Base image rule */\n"
                    "img { max-width: 100%; height: auto; display: block; }\n\n"
                    "/* PC styles (core) */\n"
                    + pc_css_core +
                    "\n\n/* Clamp (overrides core) */\n"
                    ".device-pc, .device-pc * { box-sizing: border-box; }\n"
                    ".device-pc [class^=\"n-\"], .device-pc [class*=\" n-\"] { max-width: 100%; }\n"
                    ".device-pc img { max-width: 100%; height: auto; display: block; }\n\n"
                )
            except Exception as e:
                print(f"[WARN] PC CSS generation failed: {e}")
                pc_css_full = (
                    "/* Fallback PC CSS */\n"
                    "html, body { margin:0; padding:0; overflow-x:hidden; }\n"
                    ".device-pc { display:block; } .device-sp { display:none; }\n"
                    "img { max-width:100%; height:auto; display:block; }\n"
                )
            with open(pc_css_file, "w", encoding="utf-8") as f:
                f.write(pc_css_full)

            try:
                sp_css_core = generate_css(SP_LAYOUT_STRUCTURE, SP_COLLECTED_TEXT_STYLES, SP_NODE_STYLES)
                sp_css_full = (
                    "/* Device visibility (SP bundle) */\n"
                    ".device-pc { display: none; }\n"
                    ".device-sp { display: block; }\n\n"
                    "/* Base image rule */\n"
                    "img { max-width: 100%; height: auto; display: block; }\n\n"
                    "/* SP styles (core) */\n"
                    + sp_css_core +
                    "\n\n/* Clamp (overrides core) */\n"
                    ".device-sp, .device-sp * { box-sizing: border-box; }\n"
                    ".device-sp [class^=\"n-\"], .device-sp [class*=\" n-\"] { max-width: 100%; width: 100%; }\n"
                    ".device-sp img { max-width: 100%; width: 100%; height: auto; display: block; }\n\n"
                )
            except Exception as e:
                print(f"[WARN] SP CSS generation failed: {e}")
                sp_css_full = (
                    "/* Fallback SP CSS */\n"
                    ".device-pc { display:none; } .device-sp { display:block; }\n"
                    "img { max-width:100%; height:auto; display:block; }\n"
                )
            with open(sp_css_file, "w", encoding="utf-8") as f:
                f.write(sp_css_full)

    print(f"[LOG] Combined HTML saved: {combined_html_file}")
    print(f"[LOG] Combined PC CSS saved: {pc_css_file}")
    print(f"[LOG] Combined SP CSS saved: {sp_css_file}")
    # Dump include-like dry-run report if any
    try:
        report_file = os.path.join(combined_dir, "include_candidates.json")
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(INCLUDE_CANDIDATES, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Include-like candidates report saved: {report_file}")
    except Exception as e:
        print(f"[WARN] Failed to save include candidates: {e}")

    # Reports
    try:
        build_node_style_report(combined_dir)
        build_alias_report(combined_dir)
        try:
            build_waste_report(combined_dir, PC_SECTIONS, PC_NODE_STYLES, combined_html_file, [pc_css_file, sp_css_file])
        except Exception as e:
            print(f"[WARN] Waste report (PC+SP) failed: {e}")
    except Exception as e:
        print(f"[WARN] Report generation failed: {e}")

# Final combined output guard: ensure index.html/style.css are produced even if SP missing
if SINGLE_HTML:
    combined_dir = os.path.join(OUTPUT_DIR, safe_project_name)
    os.makedirs(combined_dir, exist_ok=True)

    # Build PC images map with safe IDs
    pc_image_map = {}
    for section in PC_SECTIONS:
        for el in get_all_child_elements(section):
            nid = el.get('id')
            if not nid:
                continue
            safe_id = css_safe_identifier(nid)
            pc_image_map[nid] = f"images/{safe_id}.{IMAGE_FORMAT}"

    # PC sections HTML
    IMAGE_URL_MAP = pc_image_map
    pc_sections_html = ""
    for i, section_summary in enumerate(PC_LAYOUT_STRUCTURE["sections_summary"]):
        section_data = PC_SECTIONS[i] if i < len(PC_SECTIONS) else {}
        pc_sections_html += generate_html_for_section(section_data, PC_LAYOUT_STRUCTURE["wrapper_width"]) + "\n"

    # Optional SP sections
    sp_sections_html = ""
    have_sp = 'SP_SECTIONS' in locals() and SP_SECTIONS
    if have_sp:
        sp_image_map = {}
        for section in SP_SECTIONS:
            for el in get_all_child_elements(section):
                nid = el.get('id')
                if not nid:
                    continue
                safe_id = css_safe_identifier(nid)
                sp_image_map[nid] = os.path.join(SP_SAFE_FRAME_NAME, 'images', f"{safe_id}.{IMAGE_FORMAT}")
        IMAGE_URL_MAP = sp_image_map
        for i, section_summary in enumerate(SP_LAYOUT_STRUCTURE["sections_summary"]):
            section_data = SP_SECTIONS[i] if i < len(SP_SECTIONS) else {}
            sp_sections_html += generate_html_for_section(section_data, SP_LAYOUT_STRUCTURE["wrapper_width"]) + "\n"

    # Combined HTML
    combined_html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{PC_LAYOUT_STRUCTURE["project_name"]}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="device-pc">
{pc_sections_html}
  </div>
  <div class="device-sp">
{sp_sections_html}
  </div>
</body>
</html>'''

    combined_html_file = os.path.join(combined_dir, "index.html")
    combined_css_file = os.path.join(combined_dir, "style.css")
    # Write HTML first
    with open(combined_html_file, "w", encoding="utf-8") as f:
        f.write(combined_html)
    # Build CSS with failsafe
    try:
        pc_css = generate_css(PC_LAYOUT_STRUCTURE, PC_COLLECTED_TEXT_STYLES, PC_NODE_STYLES)
        sp_css = ""
        if have_sp:
            sp_css_raw = generate_css(SP_LAYOUT_STRUCTURE, SP_COLLECTED_TEXT_STYLES, SP_NODE_STYLES)
            sp_css = "\n".join(["    " + line if line.strip() else line for line in sp_css_raw.splitlines()])
        combined_css = (
            "/* Device visibility */\n"
            ".device-pc { display: block; }\n"
            ".device-sp { display: none; }\n\n"
            "@media (max-width: 768px) {\n"
            "  .device-pc { display: none; }\n"
            "  .device-sp { display: block; }\n"
            "}\n\n"
            "/* Global overflow guard */\n"
            "html, body { overflow-x: hidden; }\n\n"
            "/* PC clamp to prevent overflow */\n"
            ".device-pc, .device-pc * { box-sizing: border-box; }\n"
            ".device-pc [class^=\"n-\"], .device-pc [class*=\" n-\"] { max-width: 100%; }\n"
            ".device-pc img { max-width: 100%; height: auto; display: block; }\n\n"
            + (".device-pc [class^=\\\"n-\\\"], .device-pc [class*=\\\" n-\\\"] { width: 100% !important; }\n\n" if PC_STRICT_CLAMP else "") +
            "/* PC styles */\n"
            + pc_css +
            "\n\n/* SP styles (scoped via media query) */\n"
            "@media (max-width: 768px) {\n" +
            sp_css +
            "\n  /* Responsive overrides to prevent sideways scroll */\n"
            "  .device-sp, .device-sp * { box-sizing: border-box; }\n"
            "  .device-sp [class^=\"n-\"], .device-sp [class*=\" n-\"] { max-width: 100% !important; width: 100% !important; }\n"
            "  .device-sp img { max-width: 100% !important; width: 100% !important; height: auto !important; display: block; }\n"
            "  .device-sp [class^=\"n-\"], .device-sp [class*=\" n-\"] { height: auto !important; min-height: 0 !important; }\n"
            "}\n"
        )
    except Exception as e:
        print(f"[WARN] CSS generation (combined) failed: {e}")
        combined_css = (
            "/* Fallback CSS */\n"
            "html, body { margin:0; padding:0; overflow-x:hidden; }\n"
            ".device-pc { display:block; } .device-sp { display:none; }\n"
            "@media (max-width:768px){ .device-pc{display:none;} .device-sp{display:block;} }\n"
            "img { max-width:100%; height:auto; display:block; }\n"
        )
    with open(combined_css_file, "w", encoding="utf-8") as f:
        f.write(combined_css)
    # Optional prune
    if PRUNE_UNUSED_CSS:
        try:
            pruned_path = os.path.join(combined_dir, "style.css")
            if prune_unused_css(combined_html_file, combined_css_file, pruned_path):
                print(f"[LOG] Combined CSS pruned -> {pruned_path}")
            else:
                print("[LOG] CSS prune skipped or failed; keeping original")
        except Exception as e:
            print(f"[WARN] CSS prune error: {e}")
    print(f"[LOG] Combined HTML saved: {combined_html_file}")
    print(f"[LOG] Combined CSS saved: {combined_css_file}")
    # Write validation report
    try:
        build_node_style_report(combined_dir)
        build_alias_report(combined_dir)
        try:
            build_waste_report(combined_dir, PC_SECTIONS, PC_NODE_STYLES, combined_html_file, [combined_css_file])
        except Exception as e:
            print(f"[WARN] Waste report (final combined) failed: {e}")
    except Exception as e:
        print(f"[WARN] Report generation failed: {e}")

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

def should_exclude_node(node):
    """除外対象か判定（レイヤー名キーワード/IDで判定）"""
    if not node:
        return False
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
    # 自動ヘッダー/フッター判定（ルート直下の子ノードに限定）
    if EXCLUDE_HEADER_FOOTER and node.get("id") in ROOT_CHILD_IDS and is_probable_header_footer(node):
        return True
    return False

# ルートフレームの境界（ヘッダー/フッター判定用）
ROOT_FRAME_BOUNDS = None
ROOT_CHILD_IDS = set()

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

def download_images(url_map, out_dir, file_ext="png"):
    os.makedirs(out_dir, exist_ok=True)
    id_to_relpath = {}
    for node_id, url in url_map.items():
        if not url:
            continue
        try:
            safe_id = css_safe_identifier(node_id)
            filename = f"{safe_id}.{file_ext}"
            abs_path = os.path.join(out_dir, filename)
            # Cache: skip download if file exists and not forced
            if os.path.exists(abs_path) and not FORCE_IMAGE_REDOWNLOAD:
                id_to_relpath[node_id] = os.path.join("images", filename)
                print(f"[CACHE] Using existing image: {abs_path}")
                continue

            resp = requests.get(url)
            resp.raise_for_status()
            with open(abs_path, "wb") as f:
                f.write(resp.content)
            id_to_relpath[node_id] = os.path.join("images", filename)
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

        # gap
        gap = element.get("itemSpacing")
        if isinstance(gap, (int, float)):
            style_parts.append(f"gap:{int(gap)}px")

        # padding
        p_top = int(element.get("paddingTop", 0))
        p_right = int(element.get("paddingRight", 0))
        p_bottom = int(element.get("paddingBottom", 0))
        p_left = int(element.get("paddingLeft", 0))
        if any([p_top, p_right, p_bottom, p_left]):
            style_parts.append(f"padding:{p_top}px {p_right}px {p_bottom}px {p_left}px")

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
    """レイアウト情報からCSSクラス名を生成"""
    classes = []
    
    # 基本レイアウトクラス
    if layout_info["type"] == "two-column":
        classes.append("layout-2col")
        
        # 精密な比率情報があれば追加
        if layout_info.get("ratios"):
            ratio = layout_info["ratios"][0]
            if ratio == "1:1":
                classes.append("layout-2col-equal")
            elif ratio == "1:2":
                classes.append("layout-2col-1-2")
            elif ratio == "2:3":
                classes.append("layout-2col-2-3")
            elif ratio == "1:3":
                classes.append("layout-2col-1-3")
            elif ratio == "3:4":
                classes.append("layout-2col-3-4")
            else:
                # カスタム比率の場合
                ratio_safe = ratio.replace(":", "-").replace(".", "")
                classes.append(f"layout-2col-{ratio_safe}")
    
    elif layout_info["type"] == "three-column":
        classes.append("layout-3col")
        
        # 3カラムの比率
        if layout_info.get("ratios"):
            ratio = layout_info["ratios"][0]
            if ratio == "1:1:1":
                classes.append("layout-3col-equal")
            else:
                ratio_safe = ratio.replace(":", "-").replace(".", "")
                classes.append(f"layout-3col-{ratio_safe}")
    
    elif layout_info["type"] == "multi-column":
        classes.append(f"layout-{layout_info['columns']}col")
    
    # コンテンツパターンクラス
    if layout_info.get("content_patterns"):
        for pattern in layout_info["content_patterns"]:
            if pattern == "image-text":
                classes.append("layout-image-text")
            elif pattern == "text-image":
                classes.append("layout-text-image")
            elif pattern == "image-image":
                classes.append("layout-image-gallery")
    
    # Auto Layoutクラス
    if layout_info.get("layout_mode") == "HORIZONTAL":
        classes.append("layout-flex-row")
    elif layout_info.get("layout_mode") == "VERTICAL":
        classes.append("layout-flex-col")
    
    return " ".join(classes) if classes else ""

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
        url_map = fetch_figma_image_urls(FILE_KEY, list(image_ids), IMAGE_FORMAT, IMAGE_SCALE)
        images_dir = os.path.join(project_dir, "images")
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
                    tmp_map[nid] = os.path.join("images", filename)
                else:
                    tmp_map[nid] = url
            IMAGE_URL_MAP = tmp_map
    except Exception as e:
        print(f"[WARN] Image export failed: {e}")
else:
    print("[LOG] Image integration disabled (USE_IMAGES=false)")

# フォント情報抽出関数
def extract_text_styles(text_element, figma_styles=None):
    """テキスト要素からフォント情報を抽出（Figmaスタイル優先）"""
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
    
    # 2. style プロパティから情報取得（Figmaスタイルがない場合のフォールバック）
    style = text_element.get("style", {})
    
    # Figmaスタイルが適用されていない場合のみ、個別スタイルを適用
    if not style_info.get("figma_style_name"):
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
    
    # テキストの色情報（fillsの最前面SOLIDを使用、opacity考慮）
    rgba = _pick_solid_fill_rgba(text_element)
    if rgba:
        style_info["color"] = rgba
    
    return style_info

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

def generate_text_class(style_info, element_name="", element_id=""):
    """スタイル情報からCSSクラス名を生成（レイヤー名優先、色情報も考慮）"""
    # 1. レイヤー名から意味のあるクラス名を生成（最優先）
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
    
    # セクション名から意味のあるクラス名を生成
    semantic_class = generate_semantic_class(section_name, "section")
    section_class = semantic_class if semantic_class else sanitize_filename(section_name).lower().replace(" ", "-")
    
    html = f'''<section class="{section_class}">
  <div class="container" style="max-width: {wrapper_width}px; margin: 0 auto;">
    <div class="inner">
'''
    
    # 子要素の処理（基本的なレイアウトのみ）
    children = section_data.get("children", [])
    # detect_sections_by_position のフォールバック（elements配列）に対応
    if not children and section_data.get("elements"):
        children = section_data.get("elements", [])
    for child in children:
        if should_exclude_node(child):
            print(f"[LOG] Excluded in section: {child.get('name')} ({child.get('id')})")
            continue
        html += generate_element_html(child, "      ", suppress_leaf_images=False, suppress_parent_bounds=None)
    
    html += '''    </div>
  </div>
</section>
'''
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
    return "p"

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

def _child_auto_layout_rules(parent_layout_mode, child):
    """Return (styles, skip_width, skip_height)
    - styles: list of CSS props like 'flex:1 1 auto', 'align-self:center'
    - skip_width/skip_height: whether to suppress fixed width/height on this child
    """
    styles = []
    skip_w = False
    skip_h = False
    if not parent_layout_mode:
        return styles, skip_w, skip_h
    layout_grow = child.get("layoutGrow", 0)
    layout_align = (child.get("layoutAlign") or "").upper()
    # flex grow on primary axis
    if layout_grow == 1:
        styles.append("flex:1 1 auto")
        if parent_layout_mode == "HORIZONTAL":
            skip_w = True
        elif parent_layout_mode == "VERTICAL":
            skip_h = True
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


def generate_element_html(element, indent="", suppress_leaf_images=False, suppress_parent_bounds=None, parent_layout_mode=None):
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
        
        # 見出しレベルの判定
        tag_name = detect_heading_level(element)
        
        return f'{indent}<{tag_name} class="{style_class}">{text_content}</{tag_name}>\n'
    
    # コンテナ（子を持つ要素）は常にコンテナとして扱う（画像fillがあっても背景として扱う）
    children = element.get("children", []) or element.get("elements", []) or []
    if element_type == "FRAME" or children:
        # クラス名
        semantic_class = generate_semantic_class(element_name, element_type)
        frame_class = semantic_class if semantic_class else sanitize_filename(element_name).lower().replace(" ", "-")

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
                    # 背景画像は親要素（wrapper）に適用
                    background_wrapper_style.append(f"background-image:url('{src}')")
                    # 元要素の高さも背景wrapper要素に移動
                    if h and isinstance(h, (int, float)) and h > 0:
                        background_wrapper_style.append(f"height:{int(h)}px")
                    # bg_style には何も追加しない（元要素には背景画像を適用しない）

        # Auto Layoutをinline styleで反映
        inline_style = map_auto_layout_inline_styles(element)
        style_parts = [inline_style] if inline_style else []
        # respect container sizing modes when present
        sizing_primary = (element.get("primaryAxisSizingMode") or "").upper()
        sizing_counter = (element.get("counterAxisSizingMode") or "").upper()
        add_w = True
        add_h = True
        if layout_info.get("layout_mode") == "HORIZONTAL":
            if sizing_primary == "AUTO":
                add_w = False
            if sizing_counter == "AUTO":
                add_h = False
        elif layout_info.get("layout_mode") == "VERTICAL":
            if sizing_primary == "AUTO":
                add_h = False
            if sizing_counter == "AUTO":
                add_w = False
        # also consider parent layout intention for this element (stretch/grow)
        if parent_layout_mode:
            child_rules, skip_w_child, skip_h_child = _child_auto_layout_rules(parent_layout_mode, element)
            if skip_w_child:
                add_w = False
                # prefer full-width in vertical stacks
                if parent_layout_mode == "VERTICAL":
                    style_parts.append("width:100%")
            if skip_h_child:
                add_h = False
                if parent_layout_mode == "HORIZONTAL":
                    style_parts.append("height:100%")
            # attach flex/align styles from parent's auto-layout intent
            if child_rules:
                style_parts.extend(child_rules)
        # 背景コンテナは固定px幅を出さない（フルブリード化する）
        if isinstance(w, (int, float)) and w > 0 and add_w and not has_image_fill:
            style_parts.append(f"width:{int(w)}px")
        if isinstance(h, (int, float)) and h > 0 and add_h and not (has_image_fill and USE_IMAGES and background_wrapper_style):
            # 高さはコンテンツで伸びても良いようにmin-heightを優先
            # 背景画像がある場合は高さをwrapper要素に移動済みなので元要素では出力しない
            style_parts.append(f"min-height:{int(h)}px")
        if bg_style:
            style_parts.extend(bg_style)
        # クリップ有効時は隠す
        if element.get("clipsContent"):
            style_parts.append("overflow:hidden")
        # ノード固有クラスへスタイルを移譲
        node_id = element.get("id", "")
        node_safe = css_safe_identifier(node_id) if node_id else None
        node_class = f"n-{node_safe}" if node_safe else None
        if node_class and style_parts:
            add_node_styles(node_safe, [p for p in style_parts if p])

        # クラス結合
        all_classes = [frame_class]
        if layout_class:
            all_classes.append(layout_class)
        if node_class:
            all_classes.append(node_class)
        # クラス名を結合
        all_classes = [frame_class]
        if layout_class:
            all_classes.append(layout_class)
        # 背景画像がある場合は、bg-fullbleedクラスを元要素には追加しない
        final_class = " ".join(all_classes)

        # 背景画像がある場合は親要素（wrapper）を追加
        if has_image_fill and USE_IMAGES and background_wrapper_style:
            wrapper_style = "; ".join(background_wrapper_style)
            html = f'{indent}<div class="bg-fullbleed" style="{wrapper_style}">\n'
            html += f'{indent}  <div class="{final_class}">\n'
            content_indent = indent + "    "
            closing_html = f'{indent}  </div>\n{indent}</div>\n'
        else:
            html = f'{indent}<div class="{final_class}">\n'
            content_indent = indent + "  "
            closing_html = f'{indent}</div>\n'
        # 子の画像抑制ポリシー
        child_suppress = suppress_leaf_images
        parent_bounds = suppress_parent_bounds
        if IMAGE_CONTAINER_SUPPRESS_LEAFS and has_image_fill and USE_IMAGES:
            child_suppress = True
            parent_bounds = _bounds(element)

        for child in children:
            if should_exclude_node(child):
                continue
            # apply child auto-layout rules if this container is auto-layout
            child_styles, skip_w, skip_h = _child_auto_layout_rules(layout_info.get("layout_mode"), child)
            # enrich child node styles
            child_id = child.get("id")
            if child_id and child_styles:
                add_node_styles(css_safe_identifier(child_id), child_styles)
            html += generate_element_html(child, content_indent, suppress_leaf_images=child_suppress, suppress_parent_bounds=parent_bounds, parent_layout_mode=layout_info.get("layout_mode"))
        html += closing_html
        return html

    # 画像または矩形（子なしの葉要素）
    elif element_type == "RECTANGLE" or is_image_element(element):
        bounds = _bounds(element)
        width = bounds.get("width", 100)
        height = bounds.get("height", 100)
        
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
            # 固有サイズをCSSに委譲
            # parent auto-layout rules may suppress fixed width/height
            child_styles, skip_w, skip_h = _child_auto_layout_rules(parent_layout_mode, element)
            node_props = []
            if not skip_w:
                node_props.append(f"width: {int(width)}px")
            if not skip_h:
                node_props.append(f"height: {int(height)}px")
            # include flex/align if any
            node_props.extend([s for s in child_styles if s])
            if node_safe:
                add_node_styles(node_safe, node_props)
            if USE_IMAGES:
                # 画像出力（ダウンロード済み or CDN URL）
                src = IMAGE_URL_MAP.get(node_id)
                # フォールバックとしてプレースホルダー
                if not src:
                    safe_name = element_name.replace(" ", "_").replace("(", "").replace(")", "")
                    src = f"https://via.placeholder.com/{int(width)}x{int(height)}/cccccc/666666?text={safe_name}"
                all_classes = [img_class]
                if node_class:
                    all_classes.append(node_class)
                return f'{indent}<div class="{" ".join(all_classes)}">\n{indent}  <img src="{src}" alt="{escape(element_name)}" style="width: 100%; height: 100%; object-fit: cover;">\n{indent}</div>\n'
            else:
                # 画像は使わず、サイズだけ確保
                all_classes = [img_class]
                if node_class:
                    all_classes.append(node_class)
                return f'{indent}<div class="{" ".join(all_classes)}"></div>\n'
        else:
            # 通常の矩形要素
            rgba = _pick_solid_fill_rgba(element)
            bg_color = rgba if rgba else "#f0f0f0"
            node_id = element.get("id", "")
            node_safe = css_safe_identifier(node_id) if node_id else None
            node_class = f"n-{node_safe}" if node_safe else None
            child_styles, skip_w, skip_h = _child_auto_layout_rules(parent_layout_mode, element)
            node_props = [f"background-color: {bg_color}"]
            if not skip_w:
                node_props.append(f"width: {int(width)}px")
            if not skip_h:
                node_props.append(f"height: {int(height)}px")
            node_props.extend([s for s in child_styles if s])
            if node_safe:
                add_node_styles(node_safe, node_props)
            classes = ["rect-element"]
            if node_class:
                classes.append(node_class)
            return f'{indent}<div class="{" ".join(classes)}"></div>\n'
    
    # ここまでで該当しない要素タイプ
    
    else:
        # その他の要素タイプでも画像チェック
        if is_image_element(element):
            bounds = element.get("absoluteBoundingBox", {})
            width = bounds.get("width", 100)
            height = bounds.get("height", 100)
            semantic_class = generate_semantic_class(element_name, "image")
            img_class = semantic_class if semantic_class else "image-placeholder"
            safe_name = element_name.replace(" ", "_").replace("(", "").replace(")", "")
            return f'{indent}<div class="{img_class}" style="width: {width}px; height: {height}px;">\n{indent}  <img src="https://via.placeholder.com/{int(width)}x{int(height)}/cccccc/666666?text={safe_name}" alt="{element_name}" style="width: 100%; height: 100%; object-fit: cover;">\n{indent}</div>\n'
        else:
            # その他の要素でもレイヤー名を活用
            semantic_class = generate_semantic_class(element_name, element_type)
            element_class = semantic_class if semantic_class else "unknown-element"
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
    color: {style_info["color"]};
    margin: 10px 0;
}}

'''
    
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

.layout-2col-equal > * {
    flex: 1;
}

.layout-2col-1-2 > *:first-child {
    flex: 1;
}

.layout-2col-1-2 > *:last-child {
    flex: 2;
}

.layout-2col-1-3 > *:first-child {
    flex: 1;
}

.layout-2col-1-3 > *:last-child {
    flex: 3;
}

.layout-2col-2-3 > *:first-child {
    flex: 2;
}

.layout-2col-2-3 > *:last-child {
    flex: 3;
}

.layout-2col-3-4 > *:first-child {
    flex: 3;
}

.layout-2col-3-4 > *:last-child {
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
    gap: 20px;
}

.layout-text-image {
    display: flex;
    flex-direction: row-reverse;
    align-items: flex-start;
    gap: 20px;
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
    
    .layout-2col-1-2 > *,
    .layout-2col-1-3 > *,
    .layout-2col-2-3 > *,
    .layout-2col-3-4 > * {
        flex: 1;
    }
    
    .layout-4col {
        grid-template-columns: 1fr;
    }
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
        css += '''    margin: 10px 0;
}

'''
    
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

    # ノード固有スタイルを出力（インライン削減）
    css += '/* Node-specific styles (generated) */\n'
    node_styles = node_styles or {}
    for node_id, props in node_styles.items():
        safe_id = css_safe_identifier(node_id)
        props_str = ";\n    ".join(props)
        css += f'''.n-{safe_id} {{
    {props_str};
}}

'''

    return css

# テキストスタイル収集用辞書
collected_text_styles = {}
# ノードごとのスタイルをCSSに出力するための収集
collected_node_styles = {}
COLLECT_NODE_STYLES = True

def add_node_styles(node_id, style_props):
    """ノード固有スタイルを収集（後でCSSへ出力）
    style_props: ['width:100px', 'min-height:200px', ...]
    """
    global collected_node_styles
    if not COLLECT_NODE_STYLES:
        return
    if not node_id:
        return
    bucket = collected_node_styles.get(node_id, [])
    # 重複排除
    for prop in style_props:
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
            pc_image_map[nid] = os.path.join(PC_SAFE_FRAME_NAME, 'images', f"{safe_id}.{IMAGE_FORMAT}")

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

# =============================
# Optional: SP Frame Processing
# =============================
if SP_FRAME_NODE_ID:
    print("[LOG] === SPフレーム解析を開始します ===")
    # SP用のファイルJSONを取得（PCと別ファイルでも対応）
    sp_file_data = fetch_file_json(SP_FILE_KEY)
    figma_styles_sp = extract_figma_styles(sp_file_data)
    sp_frame = find_node_by_id(sp_file_data["document"], SP_FRAME_NODE_ID)
    if not sp_frame:
        print(f"[WARN] SPフレームID {SP_FRAME_NODE_ID} が見つかりませんでした。スキップします。")
    else:
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
                url_map = fetch_figma_image_urls(SP_FILE_KEY, list(image_ids), IMAGE_FORMAT, IMAGE_SCALE)
                images_dir = os.path.join(project_dir, "images")
                if DOWNLOAD_IMAGES:
                    IMAGE_URL_MAP = download_images(url_map, images_dir, IMAGE_FORMAT)
                else:
                    # ローカル優先、無ければCDN
                    tmp_map = {}
                    for nid, url in url_map.items():
                        if not nid or not url:
                            continue
                        safe_id = css_safe_identifier(nid)
                        filename = f"{safe_id}.{IMAGE_FORMAT}"
                        abs_path = os.path.join(images_dir, filename)
                        if os.path.exists(abs_path):
                            tmp_map[nid] = os.path.join("images", filename)
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
                    pc_image_map[nid] = os.path.join(PC_SAFE_FRAME_NAME, 'images', f"{safe_id}.{IMAGE_FORMAT}")

            sp_image_map = {}
            for section in SP_SECTIONS:
                for el in get_all_child_elements(section):
                    nid = el.get('id')
                    if not nid:
                        continue
                    safe_id = css_safe_identifier(nid) if nid else ""
                    sp_image_map[nid] = os.path.join(SP_SAFE_FRAME_NAME, 'images', f"{safe_id}.{IMAGE_FORMAT}")

            # PCセクションHTML生成（結合用）
            COLLECT_NODE_STYLES = False
            IMAGE_URL_MAP = pc_image_map
            pc_sections_html = ""
            for i, section_summary in enumerate(PC_LAYOUT_STRUCTURE["sections_summary"]):
                section_data = PC_SECTIONS[i] if i < len(PC_SECTIONS) else {}
                pc_sections_html += generate_html_for_section(section_data, PC_LAYOUT_STRUCTURE["wrapper_width"]) + "\n"

            # SPセクションHTML生成（結合用）
            IMAGE_URL_MAP = sp_image_map
            sp_sections_html = ""
            for i, section_summary in enumerate(SP_LAYOUT_STRUCTURE["sections_summary"]):
                section_data = SP_SECTIONS[i] if i < len(SP_SECTIONS) else {}
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
            pc_image_map[nid] = os.path.join(PC_SAFE_FRAME_NAME, 'images', f"{safe_id}.{IMAGE_FORMAT}")

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
    print(f"[LOG] Combined HTML saved: {combined_html_file}")
    print(f"[LOG] Combined CSS saved: {combined_css_file}")

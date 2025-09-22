import os
import requests
from dotenv import load_dotenv
import json
import re

# ---------------- 環境変数読み込み ----------------
load_dotenv()

FIGMA_API_TOKEN = os.getenv("FIGMA_API_TOKEN")
FILE_KEY = os.getenv("FILE_KEY")
FRAME_NODE_ID = os.getenv("FRAME_NODE_ID")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "figma_layout")
SP_FRAME_NODE_ID = os.getenv("SP_FRAME_NODE_ID", None)  # SP版フレームID（オプション）
SAVE_RAW_DATA = os.getenv("SAVE_RAW_DATA", "false").lower() == "true"  # JSONバックアップの有効/無効

if not all([FIGMA_API_TOKEN, FILE_KEY, FRAME_NODE_ID]):
    raise ValueError("APIトークン、ファイルキー、フレームIDを .env に設定してください。")

headers = {"X-Figma-Token": FIGMA_API_TOKEN}

# ヘルパー関数
def sanitize_filename(name):
    """ファイル名に使えない文字を置換"""
    return re.sub(r'[/\\:*?"<>|]', '_', name)

# ---------------- ファイル情報取得 ----------------
file_url = f"https://api.figma.com/v1/files/{FILE_KEY}"
print(f"[LOG] Figma APIにアクセス: {file_url}")
resp = requests.get(file_url, headers=headers)
resp.raise_for_status()
file_data = resp.json()

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
    """Figmaファイルからスタイル情報を抽出"""
    styles = file_info.get("styles", {})
    
    extracted_styles = {
        "text_styles": {},
        "paint_styles": {},
        "effect_styles": {}
    }
    
    # テキストスタイルの抽出
    for style_id, style_data in styles.items():
        style_type = style_data.get("styleType", "")
        style_name = style_data.get("name", f"Style_{style_id}")
        
        if style_type == "TEXT":
            text_style = style_data.get("style", {})
            extracted_styles["text_styles"][style_name] = {
                "id": style_id,
                "fontFamily": text_style.get("fontFamily", "Arial"),
                "fontSize": text_style.get("fontSize", 16),
                "fontWeight": text_style.get("fontWeight", 400),
                "lineHeight": text_style.get("lineHeightPx", 0),
                "letterSpacing": text_style.get("letterSpacing", 0),
                "textAlign": text_style.get("textAlignHorizontal", "LEFT")
            }
            
        elif style_type == "FILL":
            paint_style = style_data.get("style", {})
            fills = paint_style.get("fills", [])
            if fills and fills[0].get("type") == "SOLID":
                color = fills[0].get("color", {})
                extracted_styles["paint_styles"][style_name] = {
                    "id": style_id,
                    "type": "SOLID",
                    "color": {
                        "r": color.get("r", 0),
                        "g": color.get("g", 0), 
                        "b": color.get("b", 0),
                        "a": color.get("a", 1)
                    },
                    "css_color": f"rgba({int(color.get('r', 0) * 255)}, {int(color.get('g', 0) * 255)}, {int(color.get('b', 0) * 255)}, {color.get('a', 1)})"
                }
                
        elif style_type == "EFFECT":
            effect_style = style_data.get("style", {})
            extracted_styles["effect_styles"][style_name] = {
                "id": style_id,
                "effects": effect_style.get("effects", [])
            }
    
    return extracted_styles

# スタイル情報を抽出
figma_styles = extract_figma_styles(file_data)
print(f"[LOG] Extracted styles:")
print(f"[LOG]   Text styles: {len(figma_styles['text_styles'])}")
print(f"[LOG]   Paint styles: {len(figma_styles['paint_styles'])}")
print(f"[LOG]   Effect styles: {len(figma_styles['effect_styles'])}")

# スタイル情報の表示
for style_name, style_data in figma_styles["text_styles"].items():
    print(f"[LOG]   Text Style: '{style_name}' - {style_data['fontSize']}px, {style_data['fontWeight']}")

for style_name, style_data in figma_styles["paint_styles"].items():
    print(f"[LOG]   Paint Style: '{style_name}' - {style_data['css_color']}")

# ---------------- セクション自動検出関数 ----------------
def detect_sections_by_frames(node, path="root"):
    """Figmaフレーム構造によるセクション検出（優先度1位）"""
    sections = []
    node_name = node.get("name", "Unnamed")
    node_type = node.get("type", "Unknown")
    
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
    all_children = get_all_child_elements(node)
    
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
        elements.append(child)
        elements.extend(get_all_child_elements(child))
    return elements

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
    """要素のレイアウト構造を分析（カラム数、配置パターンなど）"""
    children = element.get("children", [])
    if not children:
        return {"type": "single", "columns": 1}
    
    # Auto Layout情報を取得
    layout_mode = element.get("layoutMode", "NONE")
    primary_axis_align = element.get("primaryAxisAlignItems", "MIN")
    
    # 子要素の位置を分析
    child_positions = []
    for child in children:
        bounds = child.get("absoluteBoundingBox", {})
        child_positions.append({
            "id": child.get("id"),
            "name": child.get("name", ""),
            "type": child.get("type", ""),
            "x": bounds.get("x", 0),
            "y": bounds.get("y", 0),
            "width": bounds.get("width", 0),
            "height": bounds.get("height", 0),
            "element": child
        })
    
    if not child_positions:
        return {"type": "single", "columns": 1}
    
    # Y座標でソートして横並び要素を検出
    sorted_by_y = sorted(child_positions, key=lambda x: x["y"])
    
    # 同じY座標レンジにある要素をグループ化（横並び検出）
    horizontal_groups = []
    current_group = [sorted_by_y[0]]
    y_threshold = 50  # Y座標の許容範囲
    
    for i in range(1, len(sorted_by_y)):
        current_y = sorted_by_y[i]["y"]
        last_y = current_group[-1]["y"]
        
        if abs(current_y - last_y) <= y_threshold:
            current_group.append(sorted_by_y[i])
        else:
            if len(current_group) > 1:  # 横並び要素がある場合のみ追加
                horizontal_groups.append(current_group)
            current_group = [sorted_by_y[i]]
    
    # 最後のグループを追加
    if len(current_group) > 1:
        horizontal_groups.append(current_group)
    
    # レイアウトパターンを判定
    layout_info = {"type": "single", "columns": 1, "layout_mode": layout_mode}
    
    if horizontal_groups:
        # 最大カラム数を取得
        max_columns = max(len(group) for group in horizontal_groups)
        layout_info["columns"] = max_columns
        
        if max_columns == 2:
            layout_info["type"] = "two-column"
            # 2カラムの比率を分析
            ratios = analyze_column_ratios(horizontal_groups)
            layout_info["ratios"] = ratios
        elif max_columns == 3:
            layout_info["type"] = "three-column"
        elif max_columns >= 4:
            layout_info["type"] = "multi-column"
        
        # 画像とテキストの配置パターンを分析
        content_patterns = analyze_content_patterns(horizontal_groups)
        layout_info["content_patterns"] = content_patterns
    
    return layout_info

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

# 出力ディレクトリの準備
def sanitize_filename(name):
    """ファイル名に使えない文字を置換"""
    return re.sub(r'[/\\:*?"<>|]', '_', name)

safe_project_name = sanitize_filename(layout_structure["project_name"])
safe_frame_name = sanitize_filename(layout_structure["frame_name"])
project_dir = os.path.join(OUTPUT_DIR, safe_project_name, safe_frame_name)
os.makedirs(project_dir, exist_ok=True)
print(f"[LOG] Output directory created: {project_dir}")

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
    if figma_styles:
        # テキスト要素がFigmaスタイルを参照している場合
        style_id = text_element.get("styleId")
        if style_id:
            # スタイルIDからスタイル名を逆引き
            for style_name, style_data in figma_styles.get("text_styles", {}).items():
                if style_data.get("id") == style_id:
                    print(f"[LOG] Using Figma style '{style_name}' for text element")
                    style_info.update({
                        "font_family": f'"{style_data.get("fontFamily", "Arial")}", sans-serif',
                        "font_size": style_data.get("fontSize", 16),
                        "font_weight": style_data.get("fontWeight", 400),
                        "line_height": style_data.get("lineHeight", 1.6) if style_data.get("lineHeight") > 0 else 1.6,
                        "letter_spacing": style_data.get("letterSpacing", 0),
                        "text_align": style_data.get("textAlign", "left"),
                        "figma_style_name": style_name
                    })
                    break
    
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
    
    # テキストの色情報
    fills = text_element.get("fills", [])
    if fills and fills[0].get("type") == "SOLID":
        color = fills[0].get("color", {})
        r = int(color.get("r", 0) * 255)
        g = int(color.get("g", 0) * 255)
        b = int(color.get("b", 0) * 255)
        style_info["color"] = f"rgb({r}, {g}, {b})"
    
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
    for child in children:
        html += generate_element_html(child, "      ")
    
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
    element_type = element.get("type", "")
    element_name = element.get("name", "").lower()
    
    # 1. RECTANGLE要素でIMAGE fillsを持つ
    if element_type == "RECTANGLE":
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

def generate_element_html(element, indent=""):
    """個別要素のHTML生成"""
    element_type = element.get("type", "")
    element_name = element.get("name", "")
    
    if element_type == "TEXT":
        text_content = element.get("characters", "テキスト")
        
        # フォント情報の取得（Figmaスタイル優先）
        style_info = extract_text_styles(element, layout_structure.get("figma_styles"))
        element_id = element.get("id", "")
        style_class = generate_text_class(style_info, element_name, element_id)
        
        # 見出しレベルの判定
        tag_name = detect_heading_level(element)
        
        return f'{indent}<{tag_name} class="{style_class}">{text_content}</{tag_name}>\n'
    
    elif element_type == "RECTANGLE" or is_image_element(element):
        bounds = element.get("absoluteBoundingBox", {})
        width = bounds.get("width", 100)
        height = bounds.get("height", 100)
        
        # 画像要素かどうかをチェック
        if is_image_element(element):
            # 画像プレースホルダーを生成
            semantic_class = generate_semantic_class(element_name, "image")
            img_class = semantic_class if semantic_class else "image-placeholder"
            safe_name = element_name.replace(" ", "_").replace("(", "").replace(")", "")
            return f'{indent}<div class="{img_class}" style="width: {width}px; height: {height}px;">\n{indent}  <img src="https://via.placeholder.com/{int(width)}x{int(height)}/cccccc/666666?text={safe_name}" alt="{element_name}" style="width: 100%; height: 100%; object-fit: cover;">\n{indent}</div>\n'
        else:
            # 通常の矩形要素
            fills = element.get("fills", [])
            bg_color = "#f0f0f0"  # デフォルト
            if fills and fills[0].get("type") == "SOLID":
                color = fills[0].get("color", {})
                r = int(color.get("r", 0) * 255)
                g = int(color.get("g", 0) * 255)
                b = int(color.get("b", 0) * 255)
                bg_color = f"rgb({r}, {g}, {b})"
            
            return f'{indent}<div class="rect-element" style="width: {width}px; height: {height}px; background-color: {bg_color};"></div>\n'
    
    elif element_type == "FRAME":
        # フレームは子要素を含むコンテナとして処理
        semantic_class = generate_semantic_class(element_name, element_type)
        frame_class = semantic_class if semantic_class else sanitize_filename(element_name).lower().replace(" ", "-")
        
        # レイアウト分析を実行
        layout_info = analyze_layout_structure(element)
        layout_class = generate_layout_class(layout_info)
        
        # クラス名を結合
        all_classes = [frame_class]
        if layout_class:
            all_classes.append(layout_class)
        
        final_class = " ".join(all_classes)
        html = f'{indent}<div class="{final_class}">\n'
        
        # レイアウト情報をログ出力
        if layout_info["columns"] > 1:
            print(f"[LOG] Layout detected: {layout_info['type']} ({layout_info['columns']} columns) - {element_name}")
            if layout_info.get("ratios"):
                print(f"[LOG]   Ratios: {layout_info['ratios']}")
            if layout_info.get("content_patterns"):
                print(f"[LOG]   Patterns: {layout_info['content_patterns']}")
        
        for child in element.get("children", []):
            html += generate_element_html(child, indent + "  ")
        
        html += f'{indent}</div>\n'
        return html
    
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

def generate_css(layout_structure, collected_text_styles):
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

/* Section styles */
section {{
    padding: 40px 0;
}}

/* Default text styles */
.text-element {{
    margin: 10px 0;
    line-height: 1.6;
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
    
    # Figma定義テキストスタイルを先に生成
    for style_name, style_data in figma_styles.get("text_styles", {}).items():
        figma_class = style_name.lower().replace(" ", "-").replace("/", "-")
        css += f'''.figma-style-{figma_class} {{
    font-family: "{style_data.get("fontFamily", "Arial")}", sans-serif;
    font-size: {style_data.get("fontSize", 16)}px;
    font-weight: {style_data.get("fontWeight", 400)};
    line-height: {style_data.get("lineHeight", 1.6) if style_data.get("lineHeight") > 0 else 1.6};
    letter-spacing: {style_data.get("letterSpacing", 0)}px;
    text-align: {style_data.get("textAlign", "left")};
    margin: 10px 0;
}}

'''
    
    css += '''/* Figma Paint Styles */
'''
    
    # Figma定義ペイントスタイルを生成
    for style_name, style_data in figma_styles.get("paint_styles", {}).items():
        paint_class = style_name.lower().replace(" ", "-").replace("/", "-")
        css += f'''.figma-paint-{paint_class} {{
    background-color: {style_data.get("css_color", "#ffffff")};
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
    color: {style_info["color"]};
    margin: 10px 0;
}}

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
    return css

# テキストスタイル収集用辞書
collected_text_styles = {}

def collect_text_styles_from_element(element, figma_styles=None):
    """要素からテキストスタイルを収集"""
    if element.get("type") == "TEXT":
        style_info = extract_text_styles(element, figma_styles)
        element_name = element.get("name", "")
        element_id = element.get("id", "")
        class_name = generate_text_class(style_info, element_name, element_id)
        collected_text_styles[class_name] = style_info
    
    # 子要素も再帰的に処理
    for child in element.get("children", []):
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
    <link rel="stylesheet" href="{safe_frame_name}.css">
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
    <link rel="stylesheet" href="style.css">
</head>
<body>
{all_sections_html}
</body>
</html>'''

# ファイル出力
html_file = os.path.join(project_dir, f"{safe_frame_name}.html")
css_file = os.path.join(project_dir, f"{safe_frame_name}.css")  
structure_file = os.path.join(project_dir, f"{safe_frame_name}_structure.json")
index_file = os.path.join(project_dir, "index.html")
style_file = os.path.join(project_dir, "style.css")

# フレーム名ベースのファイル生成
with open(html_file, "w", encoding="utf-8") as f:
    f.write(full_html)

with open(css_file, "w", encoding="utf-8") as f:
    f.write(generate_css(layout_structure, collected_text_styles))

with open(structure_file, "w", encoding="utf-8") as f:
    json.dump(layout_structure, f, ensure_ascii=False, indent=2)

# 互換性のためindex.htmlとstyle.cssも生成
with open(index_file, "w", encoding="utf-8") as f:
    f.write(index_html)

with open(style_file, "w", encoding="utf-8") as f:
    f.write(generate_css(layout_structure, collected_text_styles))

print(f"[LOG] Frame-based HTML file saved: {html_file}")
print(f"[LOG] Frame-based CSS file saved: {css_file}")
print(f"[LOG] Structure data saved: {structure_file}")
print(f"[LOG] Index HTML file saved: {index_file}")
print(f"[LOG] Index CSS file saved: {style_file}")
print("[LOG] レイアウト解析とHTML生成が完了しました！")

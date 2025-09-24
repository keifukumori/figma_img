#!/usr/bin/env python3
"""
PC/SP統合プロセッサ
Figmaから生成されたPC版とSP版のHTML/CSSを統合し、レスポンシブデザインを作成します。
"""

import os
import re
import json
import argparse
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple, Optional, Set
import difflib
from html import escape, unescape


class Element:
    """HTML要素を表現するクラス"""
    def __init__(self, tag: str, classes: List[str], content: str, attributes: Dict[str, str], position: int):
        self.tag = tag
        self.classes = classes
        self.content = content.strip()
        self.attributes = attributes
        self.position = position
        self.semantic_id = None
        self.matched_element = None
        
    def __repr__(self):
        return f"<{self.tag} class='{' '.join(self.classes)}' pos={self.position}>"


class PCSpMatcher:
    """PC版とSP版の要素をマッチングするクラス"""
    
    def __init__(self):
        self.text_similarity_threshold = 0.7
        self.structure_similarity_threshold = 0.6
        
    def extract_elements(self, html_content: str) -> List[Element]:
        """HTMLから要素を抽出"""
        soup = BeautifulSoup(html_content, 'html.parser')
        elements = []
        
        # bodyタグの中身のみを対象にする
        body = soup.find('body')
        if not body:
            return elements
            
        position = 0
        for tag in body.find_all(True):
            # テキストコンテンツを取得（子要素は除く）
            direct_text = ''.join(tag.find_all(string=True, recursive=False)).strip()
            
            # 子要素のテキストも含める（見出しや段落の場合）
            if tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'span', 'div'] and not direct_text:
                all_text = tag.get_text(strip=True)
                direct_text = all_text
            
            classes = tag.get('class', [])
            attributes = dict(tag.attrs)
            
            element = Element(
                tag=tag.name,
                classes=classes,
                content=direct_text,
                attributes=attributes,
                position=position
            )
            elements.append(element)
            position += 1
            
        return elements
    
    def calculate_text_similarity(self, text1: str, text2: str) -> float:
        """テキストの類似度を計算"""
        if not text1 and not text2:
            return 1.0
        if not text1 or not text2:
            return 0.0
            
        # HTMLエンティティをデコード
        text1 = unescape(text1)
        text2 = unescape(text2)
        
        # 正規化（改行、空白の削除）
        text1_norm = re.sub(r'\s+', ' ', text1).strip()
        text2_norm = re.sub(r'\s+', ' ', text2).strip()
        
        if text1_norm == text2_norm:
            return 1.0
            
        # 部分一致をチェック
        if text1_norm in text2_norm or text2_norm in text1_norm:
            return 0.8
            
        # Levenshtein distance による類似度
        similarity = difflib.SequenceMatcher(None, text1_norm, text2_norm).ratio()
        return similarity
    
    def calculate_structure_similarity(self, elem1: Element, elem2: Element) -> float:
        """構造の類似度を計算"""
        similarity_score = 0.0
        
        # タグ名の一致
        if elem1.tag == elem2.tag:
            similarity_score += 0.4
        elif (elem1.tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] and 
              elem2.tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            similarity_score += 0.3  # 見出しタグ同士
        
        # レイアウトクラスの一致
        layout_classes1 = [c for c in elem1.classes if c.startswith('layout-')]
        layout_classes2 = [c for c in elem2.classes if c.startswith('layout-')]
        
        if layout_classes1 and layout_classes2:
            common_layouts = set(layout_classes1) & set(layout_classes2)
            if common_layouts:
                similarity_score += 0.3 * (len(common_layouts) / max(len(layout_classes1), len(layout_classes2)))
        
        # figma-styleクラスの一致
        figma_classes1 = [c for c in elem1.classes if c.startswith('figma-style-')]
        figma_classes2 = [c for c in elem2.classes if c.startswith('figma-style-')]
        
        if figma_classes1 and figma_classes2:
            common_figma = set(figma_classes1) & set(figma_classes2)
            if common_figma:
                similarity_score += 0.3 * (len(common_figma) / max(len(figma_classes1), len(figma_classes2)))
        
        return min(similarity_score, 1.0)
    
    def match_elements(self, pc_elements: List[Element], sp_elements: List[Element]) -> Dict[int, int]:
        """PC要素とSP要素のマッチングを実行"""
        matches = {}  # pc_index -> sp_index
        used_sp_indices = set()
        
        # フェーズ1: 高精度テキストマッチング
        for i, pc_elem in enumerate(pc_elements):
            if not pc_elem.content:
                continue
                
            best_match_idx = None
            best_score = 0.0
            
            for j, sp_elem in enumerate(sp_elements):
                if j in used_sp_indices or not sp_elem.content:
                    continue
                    
                text_sim = self.calculate_text_similarity(pc_elem.content, sp_elem.content)
                
                if text_sim > self.text_similarity_threshold and text_sim > best_score:
                    best_score = text_sim
                    best_match_idx = j
            
            if best_match_idx is not None:
                matches[i] = best_match_idx
                used_sp_indices.add(best_match_idx)
                pc_elem.matched_element = sp_elements[best_match_idx]
                print(f"[TEXT MATCH] PC[{i}] <-> SP[{best_match_idx}]: {best_score:.2f}")
                print(f"  PC: {pc_elem.content[:50]}...")
                print(f"  SP: {sp_elements[best_match_idx].content[:50]}...")
        
        # フェーズ2: 構造ベースマッチング（残った要素）
        for i, pc_elem in enumerate(pc_elements):
            if i in matches:  # 既にマッチング済み
                continue
                
            best_match_idx = None
            best_score = 0.0
            
            for j, sp_elem in enumerate(sp_elements):
                if j in used_sp_indices:
                    continue
                    
                struct_sim = self.calculate_structure_similarity(pc_elem, sp_elem)
                
                if struct_sim > self.structure_similarity_threshold and struct_sim > best_score:
                    best_score = struct_sim
                    best_match_idx = j
            
            if best_match_idx is not None:
                matches[i] = best_match_idx
                used_sp_indices.add(best_match_idx)
                pc_elem.matched_element = sp_elements[best_match_idx]
                print(f"[STRUCT MATCH] PC[{i}] <-> SP[{best_match_idx}]: {best_score:.2f}")
        
        return matches


class CSSUnifier:
    """CSS統合クラス"""
    
    def __init__(self):
        self.semantic_counter = 0
        
    def generate_semantic_class(self, pc_elem: Element, sp_elem: Element = None) -> str:
        """意味のあるクラス名を生成"""
        self.semantic_counter += 1
        
        # テキスト内容から意味を推測
        if pc_elem.content:
            content = unescape(pc_elem.content)
            
            # キーワードマッピング
            if "MEN'S TBC" in content and "について" in content:
                return "hero-title"
            elif "美をサポート" in content and "メニュー" in content:
                return "service-menu-title"
            elif pc_elem.content == "EPI":
                return "service-epi-title"
            elif pc_elem.content == "FACIAL":
                return "service-facial-title"
            elif pc_elem.content == "BODY":
                return "service-body-title"
            elif "TBC" in content and len(content) > 50:
                return f"content-section-{self.semantic_counter}"
        
        # タグとレイアウトクラスから推測
        layout_classes = [c for c in pc_elem.classes if c.startswith('layout-')]
        
        if pc_elem.tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            if 'layout-3col' in layout_classes:
                return f"heading-3col-{self.semantic_counter}"
            return f"heading-{self.semantic_counter}"
        elif pc_elem.tag == 'p':
            return f"paragraph-{self.semantic_counter}"
        elif 'bg-fullbleed' in pc_elem.classes:
            return f"hero-section-{self.semantic_counter}"
        elif 'layout-3col' in layout_classes:
            return f"grid-3col-{self.semantic_counter}"
        elif 'layout-2col' in layout_classes:
            return f"grid-2col-{self.semantic_counter}"
        
        return f"element-{self.semantic_counter}"
    
    def extract_css_rules(self, css_content: str) -> Dict[str, str]:
        """CSSルールを抽出"""
        rules = {}
        
        # メディアクエリ以外のルールを抽出
        pattern = r'([^{}@]+)\s*\{([^{}]*)\}'
        matches = re.findall(pattern, css_content, re.DOTALL)
        
        for selector, declaration in matches:
            selector = selector.strip()
            declaration = declaration.strip()
            if selector and declaration:
                rules[selector] = declaration
                
        return rules
    
    def merge_css_rules(self, pc_rules: Dict[str, str], sp_rules: Dict[str, str], 
                       class_mapping: Dict[str, str]) -> str:
        """CSSルールをマージ"""
        unified_css = []
        
        # Google Fontsインポート
        unified_css.append("/* Unified PC/SP CSS */")
        unified_css.append("@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;700&family=Inter:wght@300;400;500;600;700&display=swap');")
        unified_css.append("")
        
        # 基本スタイル
        unified_css.append("/* Base styles */")
        unified_css.append("* { box-sizing: border-box; }")
        unified_css.append("body { margin: 0; padding: 0; }")
        unified_css.append("img { max-width: 100%; height: auto; display: block; }")
        unified_css.append("")
        
        # 統合されたクラスのスタイル
        unified_css.append("/* Unified element styles */")
        processed_classes = set()
        
        for old_class, new_class in class_mapping.items():
            if new_class in processed_classes:
                continue
                
            # PC版のスタイルを基本として使用
            pc_style = pc_rules.get(f".{old_class}", "")
            if pc_style:
                unified_css.append(f".{new_class} {{ {pc_style} }}")
                processed_classes.add(new_class)
        
        # レスポンシブスタイル
        unified_css.append("")
        unified_css.append("/* Responsive styles */")
        unified_css.append("@media (max-width: 768px) {")
        
        # SP版のスタイルを上書きとして適用
        for old_class, new_class in class_mapping.items():
            if f".{old_class}" in sp_rules:
                sp_style = sp_rules[f".{old_class}"]
                unified_css.append(f"  .{new_class} {{ {sp_style} }}")
        
        # 基本レスポンシブルール
        unified_css.append("  .layout-3col, .layout-4col { flex-direction: column; }")
        unified_css.append("  .layout-2col { flex-direction: column; }")
        unified_css.append("}")
        
        return "\n".join(unified_css)


class PCSpUnifier:
    """PC/SP統合メインクラス"""
    
    def __init__(self):
        self.matcher = PCSpMatcher()
        self.css_unifier = CSSUnifier()
        
    def detect_input_files(self, pc_dir: str, sp_dir: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        """入力ファイルを自動検出"""
        pc_dir_path = Path(pc_dir)
        sp_dir_path = Path(sp_dir)
        
        # HTMLファイルを検出
        pc_html_files = list(pc_dir_path.glob("*.html"))
        sp_html_files = list(sp_dir_path.glob("*.html"))
        
        pc_html = None
        sp_html = None
        
        # index-*.htmlを優先、なければ最初のHTMLファイル
        for file in pc_html_files:
            if file.name.startswith("index-"):
                pc_html = str(file)
                break
        if not pc_html and pc_html_files:
            pc_html = str(pc_html_files[0])
            
        for file in sp_html_files:
            if file.name.startswith("index-"):
                sp_html = str(file)
                break
        if not sp_html and sp_html_files:
            sp_html = str(sp_html_files[0])
        
        # CSSファイルを検出
        pc_css_files = list(pc_dir_path.glob("*.css"))
        sp_css_files = list(sp_dir_path.glob("*.css"))
        
        pc_css = None
        sp_css = None
        
        # style-*.cssを優先
        for file in pc_css_files:
            if file.name.startswith("style-"):
                pc_css = str(file)
                break
        if not pc_css and pc_css_files:
            pc_css = str(pc_css_files[0])
            
        for file in sp_css_files:
            if file.name.startswith("style-"):
                sp_css = str(file)
                break
        if not sp_css and sp_css_files:
            sp_css = str(sp_css_files[0])
        
        pc_files = {"html": pc_html, "css": pc_css}
        sp_files = {"html": sp_html, "css": sp_css}
        
        return pc_files, sp_files
    
    def unify(self, pc_dir: str, sp_dir: str, output_dir: str) -> bool:
        """統合処理のメイン関数"""
        try:
            print(f"[INFO] PC directory: {pc_dir}")
            print(f"[INFO] SP directory: {sp_dir}")
            print(f"[INFO] Output directory: {output_dir}")
            
            # 入力ファイル検出
            pc_files, sp_files = self.detect_input_files(pc_dir, sp_dir)
            
            if not pc_files["html"] or not sp_files["html"]:
                print("[ERROR] Required HTML files not found")
                return False
                
            print(f"[INFO] PC HTML: {pc_files['html']}")
            print(f"[INFO] SP HTML: {sp_files['html']}")
            print(f"[INFO] PC CSS: {pc_files['css']}")
            print(f"[INFO] SP CSS: {sp_files['css']}")
            
            # HTMLファイル読み込み
            with open(pc_files["html"], 'r', encoding='utf-8') as f:
                pc_html = f.read()
            with open(sp_files["html"], 'r', encoding='utf-8') as f:
                sp_html = f.read()
                
            # CSSファイル読み込み
            pc_css = ""
            sp_css = ""
            if pc_files["css"]:
                with open(pc_files["css"], 'r', encoding='utf-8') as f:
                    pc_css = f.read()
            if sp_files["css"]:
                with open(sp_files["css"], 'r', encoding='utf-8') as f:
                    sp_css = f.read()
            
            # 要素抽出
            print("[INFO] Extracting elements...")
            pc_elements = self.matcher.extract_elements(pc_html)
            sp_elements = self.matcher.extract_elements(sp_html)
            
            print(f"[INFO] PC elements: {len(pc_elements)}")
            print(f"[INFO] SP elements: {len(sp_elements)}")
            
            # マッチング実行
            print("[INFO] Matching elements...")
            matches = self.matcher.match_elements(pc_elements, sp_elements)
            
            print(f"[INFO] Matched pairs: {len(matches)}")
            
            # クラス名マッピング生成
            class_mapping = {}
            for pc_idx, sp_idx in matches.items():
                pc_elem = pc_elements[pc_idx]
                sp_elem = sp_elements[sp_idx]
                
                semantic_class = self.css_unifier.generate_semantic_class(pc_elem, sp_elem)
                
                # PC版のクラス名をマッピング
                for cls in pc_elem.classes:
                    if cls not in class_mapping:
                        class_mapping[cls] = semantic_class
                        
                # SP版のクラス名をマッピング
                for cls in sp_elem.classes:
                    if cls not in class_mapping:
                        class_mapping[cls] = semantic_class
            
            # CSS統合
            print("[INFO] Merging CSS...")
            pc_css_rules = self.css_unifier.extract_css_rules(pc_css)
            sp_css_rules = self.css_unifier.extract_css_rules(sp_css)
            
            unified_css = self.css_unifier.merge_css_rules(pc_css_rules, sp_css_rules, class_mapping)
            
            # 統合HTML生成（PC版をベースに、セマンティッククラスに置き換え）
            print("[INFO] Generating unified HTML...")
            unified_html = self.generate_unified_html(pc_html, class_mapping)
            
            # 出力ディレクトリ作成
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # 統合ファイル出力
            with open(output_path / "index.html", 'w', encoding='utf-8') as f:
                f.write(unified_html)
            with open(output_path / "style.css", 'w', encoding='utf-8') as f:
                f.write(unified_css)
                
            # レポート出力
            self.generate_report(output_path, matches, pc_elements, sp_elements, class_mapping)
            
            print(f"[SUCCESS] Unified files created in {output_dir}")
            print(f"[SUCCESS] Matching rate: {len(matches)}/{len(pc_elements)} ({len(matches)/len(pc_elements)*100:.1f}%)")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Unification failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def generate_unified_html(self, pc_html: str, class_mapping: Dict[str, str]) -> str:
        """統合HTMLを生成"""
        # クラス名を置換
        unified_html = pc_html
        
        for old_class, new_class in class_mapping.items():
            # class="old_class" を class="new_class" に置換
            pattern = rf'class="([^"]*){re.escape(old_class)}([^"]*)"'
            
            def replace_class(match):
                before = match.group(1)
                after = match.group(2)
                return f'class="{before}{new_class}{after}"'
            
            unified_html = re.sub(pattern, replace_class, unified_html)
        
        # タイトルを更新
        unified_html = re.sub(r'<title>.*?</title>', '<title>Unified PC/SP Layout</title>', unified_html)
        
        # CSSリンクを更新
        unified_html = re.sub(r'<link rel="stylesheet" href="[^"]*">', '<link rel="stylesheet" href="style.css">', unified_html)
        
        return unified_html
    
    def generate_report(self, output_path: Path, matches: Dict[int, int], 
                       pc_elements: List[Element], sp_elements: List[Element],
                       class_mapping: Dict[str, str]):
        """マッチング結果レポートを生成"""
        report = {
            "summary": {
                "pc_elements": len(pc_elements),
                "sp_elements": len(sp_elements),
                "matched_pairs": len(matches),
                "matching_rate": len(matches) / len(pc_elements) if pc_elements else 0,
                "semantic_classes": len(set(class_mapping.values()))
            },
            "matches": [],
            "unmatched_pc": [],
            "unmatched_sp": [],
            "class_mapping": class_mapping
        }
        
        # マッチングペア
        for pc_idx, sp_idx in matches.items():
            pc_elem = pc_elements[pc_idx]
            sp_elem = sp_elements[sp_idx]
            
            report["matches"].append({
                "pc_index": pc_idx,
                "sp_index": sp_idx,
                "pc_content": pc_elem.content[:100],
                "sp_content": sp_elem.content[:100],
                "pc_classes": pc_elem.classes,
                "sp_classes": sp_elem.classes
            })
        
        # 未マッチ要素
        matched_pc_indices = set(matches.keys())
        matched_sp_indices = set(matches.values())
        
        for i, elem in enumerate(pc_elements):
            if i not in matched_pc_indices:
                report["unmatched_pc"].append({
                    "index": i,
                    "content": elem.content[:100],
                    "classes": elem.classes,
                    "tag": elem.tag
                })
        
        for i, elem in enumerate(sp_elements):
            if i not in matched_sp_indices:
                report["unmatched_sp"].append({
                    "index": i,
                    "content": elem.content[:100],
                    "classes": elem.classes,
                    "tag": elem.tag
                })
        
        # レポート保存
        with open(output_path / "matching_report.json", 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"[INFO] Report saved: {output_path / 'matching_report.json'}")


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="PC/SP統合プロセッサ")
    parser.add_argument("--pc-dir", required=True, help="PC版ディレクトリパス")
    parser.add_argument("--sp-dir", required=True, help="SP版ディレクトリパス")
    parser.add_argument("--output-dir", required=True, help="出力ディレクトリパス")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.pc_dir):
        print(f"[ERROR] PC directory not found: {args.pc_dir}")
        sys.exit(1)
        
    if not os.path.exists(args.sp_dir):
        print(f"[ERROR] SP directory not found: {args.sp_dir}")
        sys.exit(1)
    
    unifier = PCSpUnifier()
    success = unifier.unify(args.pc_dir, args.sp_dir, args.output_dir)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
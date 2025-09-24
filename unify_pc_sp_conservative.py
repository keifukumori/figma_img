#!/usr/bin/env python3
"""
PC/SP統合プロセッサ（保守的アプローチ）
PC版のHTML/CSSをベースとして、SP版のスタイルをメディアクエリで追加する安全な統合方式
"""

import os
import re
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Set
import logging

class ConservativePCSpUnifier:
    """保守的PC/SP統合クラス"""
    
    def __init__(self):
        self.mobile_breakpoint = "768px"
        
    def detect_input_files(self, pc_dir: str, sp_dir: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        """入力ファイルを自動検出"""
        pc_dir_path = Path(pc_dir)
        sp_dir_path = Path(sp_dir)
        
        # HTMLファイルを検出
        pc_html_files = list(pc_dir_path.glob("*.html"))
        sp_html_files = list(sp_dir_path.glob("*.html"))
        
        pc_html = None
        sp_html = None
        
        # index-*.htmlを優先
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
    
    def extract_css_rules(self, css_content: str) -> Tuple[Dict[str, str], List[str]]:
        """CSSルールとメディアクエリを抽出"""
        rules = {}
        media_queries = []
        
        # 基本的なCSSルールを抽出（メディアクエリ外）
        # コメントを除去
        css_clean = re.sub(r'/\*.*?\*/', '', css_content, flags=re.DOTALL)
        
        # メディアクエリを抽出して保存
        media_pattern = r'@media[^{]*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        media_matches = re.findall(media_pattern, css_clean, re.DOTALL)
        media_queries.extend(media_matches)
        
        # メディアクエリを除去してベースルールを抽出
        css_without_media = re.sub(media_pattern, '', css_clean, flags=re.DOTALL)
        
        # 基本ルールを抽出
        rule_pattern = r'([^{}@]+?)\s*\{([^{}]*)\}'
        matches = re.findall(rule_pattern, css_without_media, re.DOTALL)
        
        for selector, declaration in matches:
            selector = selector.strip()
            declaration = declaration.strip()
            if selector and declaration and not selector.startswith('@'):
                # 複数セレクタがカンマ区切りの場合は分割
                selectors = [s.strip() for s in selector.split(',')]
                for sel in selectors:
                    if sel:
                        rules[sel] = declaration
                        
        return rules, media_queries
    
    def extract_classes_from_css(self, css_rules: Dict[str, str]) -> Set[str]:
        """CSSルールからクラス名を抽出"""
        classes = set()
        for selector in css_rules.keys():
            # クラスセレクタを抽出（.class-name形式）
            class_matches = re.findall(r'\.([a-zA-Z0-9_-]+)', selector)
            classes.update(class_matches)
        return classes
    
    def create_unified_css(self, pc_css: str, sp_css: str) -> str:
        """統合CSSを作成"""
        unified_css = []
        
        # ヘッダー
        unified_css.append("/* Unified PC/SP CSS (Conservative Approach) */")
        
        # Google Fontsインポートを抽出
        font_imports = []
        for css in [pc_css, sp_css]:
            imports = re.findall(r'@import[^;]+;', css)
            font_imports.extend(imports)
        
        # 重複を除去してフォントインポートを追加
        seen_imports = set()
        for imp in font_imports:
            if imp not in seen_imports:
                unified_css.append(imp)
                seen_imports.add(imp)
        
        unified_css.append("")
        
        # PC版CSSを抽出（メディアクエリを除く）
        pc_rules, pc_media_queries = self.extract_css_rules(pc_css)
        sp_rules, sp_media_queries = self.extract_css_rules(sp_css)
        
        # PC版の基本スタイルを追加
        unified_css.append("/* PC Base Styles */")
        for selector, declaration in pc_rules.items():
            unified_css.append(f"{selector} {{ {declaration} }}")
        
        unified_css.append("")
        
        # PC版の既存メディアクエリを追加
        if pc_media_queries:
            unified_css.append("/* PC Media Queries */")
            for media_query in pc_media_queries:
                unified_css.append(media_query)
            unified_css.append("")
        
        # SP版のスタイルをメディアクエリとして追加
        unified_css.append(f"/* SP Styles - Mobile First */")
        unified_css.append(f"@media (max-width: {self.mobile_breakpoint}) {{")
        
        # SP版で定義されているクラスをメディアクエリ内に追加
        sp_classes = self.extract_classes_from_css(sp_rules)
        pc_classes = self.extract_classes_from_css(pc_rules)
        
        # SP版固有のスタイルまたはPC版を上書きするスタイルを追加
        for selector, declaration in sp_rules.items():
            # クラス名が含まれているかチェック
            if any(cls in selector for cls in sp_classes):
                unified_css.append(f"  {selector} {{ {declaration} }}")
        
        # 基本的なレスポンシブ調整を追加
        unified_css.append("  /* Basic responsive adjustments */")
        unified_css.append("  .container { max-width: 100% !important; padding: 0 15px; }")
        unified_css.append("  .layout-3col, .layout-4col, .layout-5col, .layout-6col, .layout-7col {")
        unified_css.append("    flex-direction: column !important;")
        unified_css.append("  }")
        unified_css.append("  .layout-2col {")
        unified_css.append("    flex-direction: column !important;")
        unified_css.append("  }")
        unified_css.append("  img { max-width: 100% !important; height: auto !important; }")
        
        unified_css.append("}")
        
        # SP版の既存メディアクエリを追加
        if sp_media_queries:
            unified_css.append("")
            unified_css.append("/* SP Media Queries */")
            for media_query in sp_media_queries:
                unified_css.append(media_query)
        
        return "\n".join(unified_css)
    
    def update_html_paths(self, html_content: str) -> str:
        """HTMLの画像パスを統合版に対応"""
        # 相対パスの画像を統合版imagesディレクトリに変更
        html_content = re.sub(r'src="\.\.\/images\/', 'src="images/', html_content)
        html_content = re.sub(r'url\(\'\.\.\/images\/', "url('images/", html_content)
        html_content = re.sub(r'url\("\.\.\/images\/', 'url("images/', html_content)
        
        # CSSリンクを更新
        html_content = re.sub(r'<link rel="stylesheet" href="[^"]*">', '<link rel="stylesheet" href="style.css">', html_content)
        
        # タイトルを更新
        html_content = re.sub(r'<title>.*?</title>', '<title>Unified PC/SP Layout</title>', html_content)
        
        return html_content
    
    def copy_images_to_unified(self, pc_dir: str, sp_dir: str, output_dir: str):
        """画像ファイルを統合ディレクトリにコピー"""
        output_images_dir = Path(output_dir) / "images"
        output_images_dir.mkdir(parents=True, exist_ok=True)
        
        # PC版の画像をコピー
        pc_images_dir = Path(pc_dir) / "../images"
        if pc_images_dir.exists():
            for img_file in pc_images_dir.glob("*"):
                if img_file.is_file():
                    import shutil
                    shutil.copy2(img_file, output_images_dir / img_file.name)
                    print(f"[INFO] Copied PC image: {img_file.name}")
        
        # SP版の画像をコピー（_sp付きで）
        sp_images_dir = Path(sp_dir) / "../images"
        if sp_images_dir.exists():
            for img_file in sp_images_dir.glob("*_sp.*"):
                if img_file.is_file():
                    import shutil
                    shutil.copy2(img_file, output_images_dir / img_file.name)
                    print(f"[INFO] Copied SP image: {img_file.name}")
    
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
            
            # ファイル読み込み
            with open(pc_files["html"], 'r', encoding='utf-8') as f:
                pc_html = f.read()
            with open(sp_files["html"], 'r', encoding='utf-8') as f:
                sp_html = f.read()
                
            pc_css = ""
            sp_css = ""
            if pc_files["css"]:
                with open(pc_files["css"], 'r', encoding='utf-8') as f:
                    pc_css = f.read()
            if sp_files["css"]:
                with open(sp_files["css"], 'r', encoding='utf-8') as f:
                    sp_css = f.read()
            
            # CSS統合
            print("[INFO] Creating unified CSS...")
            unified_css = self.create_unified_css(pc_css, sp_css)
            
            # HTML統合（PC版をベースにパス調整）
            print("[INFO] Creating unified HTML...")
            unified_html = self.update_html_paths(pc_html)
            
            # 出力ディレクトリ作成
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # ファイル出力
            with open(output_path / "index.html", 'w', encoding='utf-8') as f:
                f.write(unified_html)
            with open(output_path / "style.css", 'w', encoding='utf-8') as f:
                f.write(unified_css)
                
            # 画像ファイルをコピー
            print("[INFO] Copying images...")
            self.copy_images_to_unified(pc_dir, sp_dir, output_dir)
            
            # 簡単なレポート作成
            report = {
                "approach": "conservative",
                "base_version": "PC",
                "mobile_breakpoint": self.mobile_breakpoint,
                "files_created": {
                    "html": str(output_path / "index.html"),
                    "css": str(output_path / "style.css"),
                    "images_dir": str(output_path / "images")
                }
            }
            
            with open(output_path / "unification_report.json", 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            print(f"[SUCCESS] Conservative unified files created in {output_dir}")
            print(f"[SUCCESS] Approach: PC base + SP media queries at {self.mobile_breakpoint}")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Unification failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="PC/SP統合プロセッサ（保守的アプローチ）")
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
    
    unifier = ConservativePCSpUnifier()
    success = unifier.unify(args.pc_dir, args.sp_dir, args.output_dir)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
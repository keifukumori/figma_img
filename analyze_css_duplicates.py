#!/usr/bin/env python3
"""
CSS重複分析スクリプト
同じCSSプロパティを持つクラスを特定する
"""

import re
from collections import defaultdict

def parse_css_file(file_path):
    """CSSファイルを解析してクラスとプロパティのマッピングを作成"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # クラス定義を抽出
    class_pattern = r'\.([^{]+)\s*\{([^}]+)\}'
    matches = re.findall(class_pattern, content, re.MULTILINE | re.DOTALL)

    class_props = {}
    for class_name, properties in matches:
        class_name = class_name.strip()
        if class_name.startswith('n-'):  # n-クラスのみ対象
            # プロパティを正規化（空白、改行を除去、セミコロンで分割してソート）
            props = [p.strip() for p in properties.split(';') if p.strip()]
            props_normalized = '; '.join(sorted(props))
            class_props[class_name] = props_normalized

    return class_props

def find_duplicates(class_props):
    """同じプロパティを持つクラスを見つける"""
    prop_to_classes = defaultdict(list)

    for class_name, props in class_props.items():
        prop_to_classes[props].append(class_name)

    # 2つ以上のクラスが同じプロパティを持つものを返す
    duplicates = {props: classes for props, classes in prop_to_classes.items()
                 if len(classes) > 1}

    return duplicates

def main():
    css_file = '/Users/fukumorikei/figma_img/figma_images/TBCグループ株式会社様_Design/r-8_mens_about_pc/r-8_mens_about_pc-pc.css'

    print("CSS重複分析開始...")
    class_props = parse_css_file(css_file)
    duplicates = find_duplicates(class_props)

    print(f"\n重複が見つかったパターン数: {len(duplicates)}")
    print("=" * 80)

    for i, (props, classes) in enumerate(sorted(duplicates.items(), key=lambda x: len(x[1]), reverse=True)[:10]):
        print(f"\n【パターン {i+1}】 ({len(classes)}個のクラス)")
        print("プロパティ:")
        for prop in props.split('; '):
            print(f"  {prop}")
        print("\nクラス:")
        for class_name in sorted(classes):
            print(f"  .{class_name}")
        print("-" * 60)

if __name__ == "__main__":
    main()
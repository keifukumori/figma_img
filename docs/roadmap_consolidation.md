# Figma HTML/CSS 生成 – クラス整理とレイアウト集約 ロードマップ（現状まとめ）

## コンテキスト
- 目的: Figma の JSON から生成する HTML/CSS を、運用しやすいクラス設計に整流。
  - レイアウトは共通パーツ（グローバル/セクション基底）へ集約。
  - ENHYPEN（n-<id>）は極力使わず（または視覚の残差のみ）。
  - 影・角丸・背景など視覚はカード系に昇格し、読みやすく安全に運用。

## ここまでに実施したこと（主な変更・調査）

### 1) リポジトリ調査・ビルド確認
- 生成本体: `fetch_figma_layout.py`
- エントリ: `figma_02_build_from_json.py`（JSON→HTML/CSS、後処理も呼ぶ）
- 後処理: `tools/postprocess_dedupe.py` ほか
- オプション切替（.env）で、オフライン入力/画像/端末モードなど制御。

### 2) セクション/行/兄弟ベースの集約の導入（Ops ツール群）
- `tools/assign_section_keys.py`: 意味クラスがない `<section>` に `section-01/02…` を自動付与。
- `tools/add_section_row_alias.py`（改良）:
  - eq-cols な `fx-row` 親に `SECTION__row` を付与。
  - 親にある `g-*/ai-*/jc-*/fw-*` を読み取り、`:where(.SECTION__row){ gap/align/wrap }` を `style-common.css` に出力。
  - 値は `flex-start` など正しいハイフン表記に正規化。重複定義は置換。
  - 安定優先のため HTML のトークンは即時削除せず残す（抽出CSS確認後に段階的に削除）。
- `tools/neutralize_n_layout_in_section.py`（追加）:
  - セクション単位で `style.css` 内の `.n-*` のレイアウト系宣言（display/flex/gap/align/width/height…）のみコメントアウト（視覚は保持）。
  - 崩れ回避のため当面は停止。抽出CSSが安定後に段階的に適用。
- `tools/drop_n_if_covered.py`（バグ修正）:
  - f-string の不具合を修正。共通CSSで完全被覆された `.n-*` を HTML から削除可能に。

### 3) カード検出・影の昇格
- `tools/annotate_generic_components.py`: カード相当の要素へ `card`/`SECTION__card` を注釈。`.card{…box-shadow…}` を最小付与。
- `tools/promote_shadow_to_row_item.py`（追加）:
  - row-item 直下の `.n-*` が持つ `box-shadow` を `SECTION__row-item` 側へ昇格し、clip等でも影が見えるように。

### 4) 2カラム（画像＋テキスト）の特例見直し
- `fetch_figma_layout.py` の 2col 特例を修正：
  - 画像幅を固定320pxではなく、Figma ABB の width から算出して `flex-basis/max-width` を付与（崩れ防止）。

### 5) パイプライン/ツール構成の仕分け（使う/補助/診断）
- 新設：`tools/pipeline/`（中核）と `tools/ops/`（安全な後段オプション）。
  - pipeline: `postprocess_dedupe.py`, `unify_styles.py`, `annotate_generic_components.py`（ラッパー）
  - ops: `assign_section_keys.py`, `add_section_row_alias.py`, `drop_n_if_covered.py`, `neutralize_n_layout_in_section.py`, `promote_shadow_to_row_item.py`, `add_section_card_alias.py`
- `figma_02_build_from_json.py` と `tools/apply_project_optimizations.py` から pipeline ラッパーを参照するよう更新。
- `MANIFEST.md` を追加し、役割/呼び出しフローを明記。

### 6) 安定性の検証とロールバック
- 中和（neutralize）を広域に適用するとオートレイアウトが崩れる事象を確認 → 一旦ロールバック。
- `style-common.css` に g-40 など不足トークンを補完し、eq-cols 子の `min-width:0` など保険も維持。

## 現在の状態（安定優先）
- n-（ENHYPEN）: レイアウトを当面維持（崩れ防止）。視覚（背景/角丸/影）は引き続き n またはカード側に。
- 行/兄弟の抽出CSS: 正しい値（`flex-start`など）で出力。重複は置換し、競合させない。
- ユーティリティ: `style-common.css` に g-*/ai-*/jc-*/fw-* を網羅生成。eq-cols の保険（子 `min-width:0`）は維持。
- about セクションでの整流は問題ない状態を確認済み（崩れなし）。

## これからやること（段階移行プラン）
1) セクション単位での移行（崩れ最小）
   - section キー付与 → SECTION__row 付与・抽出 → SECTION__row-item の最小レイアウト昇格。
   - 影の昇格（row-item/cardへ）：box-shadow/角丸/背景を確実に外側で見せる。
   - 確認後に、該当セクションの HTML から `g-*/ai-*/jc-*/fw-*` を削除。
   - さらに被覆確認後、該当セクションの `n-*` のレイアウトのみ削除（視覚は残す）。

2) パイプラインへの自動配線（オプションフラグ）
   - figma_02 の後段に ops を順で実行するフラグを追加（例: `POST_SECT_KEYS=true POST_ROW_ALIAS=true POST_PROMOTE_SHADOW=true POST_DROP_N=true`）。
   - CI/ローカルの両方で同じ整理ステップが走るようにする。

3) レスポンシブ/2カラムの見直し強化
   - 画像＋テキストの検出を強化し、ABB/AL 両方から比率推定 → CSS へ一貫して反映。
   - 抽出CSSが正しく当たる範囲をログ化（差分確認を容易に）。

4) 視覚の共通化（カード）
   - `shadow-{none,sm,md,lg}` / `radius-{4,8,16,full}` / `bg-{surface,muted,accent}` 等のトークンへ昇格する演算を追加（完全一致のみ）。
   - 昇格後は n の視覚も縮小（カード基底 + MOD で管理）。

## 最終的に目指す姿
- HTML のクラスは最小・意味的・再利用しやすい：
  - グローバル: `row/col/eq-cols/__span-N`（他は極力トークンに頼らない）
  - セクション: `SECTION__row`, `SECTION__row-item`, `SECTION__heading`, `SECTION__hN`, `SECTION__text_##`, `SECTION__note_##`
  - 視覚: `card`/`SECTION__card`（必要なら `shadow-*`, `radius-*`, `bg-*`）
  - ENHYPEN(n-*): 視覚の残差のみ or 可能な限りゼロ
- パイプラインは、どのファイルでも同じ整理が自動で走り、崩れない（カバー率をログ/レポートで可視化）。

## 実行手順（例）
1) 生成（オフライン例）
```
python figma_02_build_from_json.py
```

2) パイプライン（中核）
```
python tools/pipeline/postprocess_dedupe.py --root 'figma_images/<Project>' --inject-css --backup
python tools/pipeline/unify_styles.py --root 'figma_images/<Project>'
python tools/pipeline/annotate_generic_components.py --root 'figma_images/<Project>'
```

3) Ops（段階適用）
```
# セクションキー付与 → 行抽出
python tools/ops/assign_section_keys.py --root 'figma_images/<Project>' --backup
python tools/ops/add_section_row_alias.py --root 'figma_images/<Project>' --backup

# 影の昇格（必要に応じて）
python tools/ops/promote_shadow_to_row_item.py --root 'figma_images/<Project>'

# n-* の整理（被覆確認後に）
python tools/ops/neutralize_n_layout_in_section.py --root 'figma_images/<Project>' --section <section_key> --backup
python tools/ops/drop_n_if_covered.py --root 'figma_images/<Project>' --backup
```

## メモ（ガードレール）
- 抽出CSSが正しく当たる前にトークン（g-*/ai-*）をHTMLから外さない（崩れ防止）。
- neutralize（n-*中和）はセクション限定で、小さく適用→目視確認→徐々に拡大。
- 影は clip 構造に依存するため、可能な限り row-item（外側）へ昇格してから n を縮小。

---
最短の次ステップは、対象セクション（例: about）以外にも同じ「行抽出→影昇格→段階的な n 縮小」を適用し、figma_02 の後段に ops を配線することです。問題なければ、このロードマップを基に自動化と微調整を進めます。


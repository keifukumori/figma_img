# 単一HTML（1 DOM）＋ alias ベースでの PC/SP 両対応 と n-* 段階削除 – 引き継ぎメモ

このドキュメントは、現在の生成/整流の方針・実装・現状・未解決点・次手順を、次の担当者へ引き継ぐためのまとめです。

## ユーザー要件（非交渉・中核指示）
- HTMLは常に1つ（単一DOM）。PC/SPの出し分けはCSSの@mediaのみで行う（device-pc/device-spなど2DOMは不可）。
- n-（ENHYPEN）は最終成果物から削除する（生成直後は安全アンカーとして付与可だが、整流で必ず落とす）。
- クラス設計は「運用保守しやすいこと」を最優先：
  - グローバル：ユーティリティ（fx-/g-/ai-/jc-/fw-など）
  - セクション：BEM/エイリアス（例：about__row / about__row-item / about__card）。PC/SPとも“同じエイリアス名”に収束させる。
- オートレイアウト（縦積み・等分・gap 等）の挙動はPC/SPとも崩さないこと（style-common.cssの抽出＋alias CSSで担保）。
- 視覚（shadow/border/background）はカード等の役割へ昇格し、BEM/aliasで表現（n-依存しない）。
- 暫定・崩れやすい対処（例：統合HTMLをper-frameへ機械コピー）は採用しない。設計に沿った正攻法で整流する。

## 目的（不変条件）
- HTMLは常に1つ（単一DOM）。PC/SPの出し分けはCSSの@mediaでのみ行う（2DOM: device-pc/device-sp は禁止）。
- 生成直後は崩さないために .n-*（ENHYPEN）を出すが、整流で人が読めるクラス（alias/BEM＋ユーティリティ）へ寄せ、最終的に .n-* を削除する。
- PC/SP両方のスタイルを「同じ alias（SECTION__* 等）」に当てる（aliasベース）。

## 現在の正（出力先）
- 正規の成果物は `figma_images/<Project>/` 配下。
- 確認ファイル例: `figma_images/TBCグループ株式会社様_Design/index.html`（単一HTML）。

## いまの生成と修正点（コード側）
- `.env`（主）
  - `OUTPUT_DIR=figma_images`
  - `DEVICE_MODE=both`（PC+SP生成）
  - `SINGLE_DOM=true`（単一DOM併産）
  - `OFFLINE_MODE=true` + `SP_INPUT_JSON_FILE` + `SP_FRAME_NODE_ID` でSPもローカルJSONから生成
  - エイリアス付与の強化（収束を上げる）:
    - `N_CLASS_ALIAS_MODE=add`
    - `N_CLASS_ALIAS_NAMESPACE=section`, `N_CLASS_ALIAS_STYLE=bem`, `N_CLASS_ALIAS_TOKEN_JOINER=_`
    - `N_CLASS_ALIAS_TOKEN_FILTER=aggressive`
    - `N_CLASS_ALIAS_UNIQUE_ONLY=false`, `N_CLASS_ALIAS_DROP_N_UNIQUE=false`

- `fetch_figma_layout.py`（主な修正）
  1) SINGLE_DOM の生成時:
     - single/ に出した単一DOM（index.html/style.css）をルートに昇格し、2DOM再出力をスキップ（上書き防止）。
  2) 単一DOMのCSSでは、PC/SPそれぞれの `.n-*` セレクタを可能な範囲で alias（SECTION__* 等）へ置換して出力（単一HTMLでもSP@mediaが当たるようにする）。

- `figma_02_build_from_json.py`（Opsの配線）
  - 後段OpsをCLI/ENVで切り替え可能に（POST_OPS_*）。
  - 追加Ops: `canonicalize_bem_variants.py`、`alias_overrides_apply.py`（後述）を呼べるスイッチを追加。

- 新規ツール
  - `tools/alias_overrides_apply.py`（ラッパー: `tools/ops/alias_overrides_apply.py`）
    - エイリアスの表記ぶれ/命名ぶれを `{ "from": "to" }` マップでHTML/CSSへ一括適用（完全一致置換）。

## 整流（Ops）フロー – 生成直後に必ず自動適用
- 推奨ENV（自動化）:
  - `POST_OPS_ASSIGN_SECTIONS=true`
  - `POST_OPS_ADD_SECTION_ROW_ALIAS=true`
  - `POST_OPS_ADD_SECTION_CARD_ALIAS=true`
  - `POST_OPS_ENSURE_STYLE_ORDER=true`（style-common.css を style.css の後に）
  - `POST_OPS_ESCALATE_ALIAS_SPECIFICITY=true`（:where(.alias) に加えて .alias を併記）
  - `POST_OPS_MIRROR_N_SELECTORS=true`（複合/@mediaセレクタを alias にミラー）
  - `POST_OPS_DROP_N_IF_COVERED=true`
  - `POST_OPS_DROP_N_STRICT=true`
  - `POST_OPS_ALLOW_MEDIA_LAYOUT=true` / `POST_OPS_ALLOW_COMPLEX_LAYOUT=true`
  - `POST_OPS_PRUNE_UNUSED_N_CSS=true`
  - `POST_OPS_CANONICALIZE_BEM=true`（表記ぶれ正規化）
  - （必要時）`POST_OPS_ALIAS_OVERRIDES=true`, `POST_OPS_ALIAS_OVERRIDES_MAP=alias_overrides.json`

- フロー詳細:
  1) セクションキー付与（不足時）
  2) 行抽出（`SECTION__row` 付与＋ `style-common.css` に gap/align/wrap 等を抽出）
  3) 視覚昇格（`SECTION__card`/`row-item` 等に昇格）
  4) 読み込み順/特異性の担保（後読み＋`.alias{}`）
  5) ミラー（`.n-*` の複合/媒体セレクタを alias に複製）
  6) n-* の削除（strict：完全被覆＋緩和でレイアウトのみ可）
  7) 未使用 .n-* CSS の剪定
  8) ブロッカーのレポート（`n_drop_blockers.json`）

## 既知の問題と現状
- 単一HTMLは出ているが、SP@mediaが当たらない箇所が残る：
  - 原因: エイリアス未付与/収束ぶれにより、CSS置換（`.n-* → alias`）対象が見つからない箇所がある。行抽出/視覚昇格/ミラーの再適用が単一DOM版に反映不足。
- n-* は生成のたびに復活する（仕様）：
  - 整流（自動）までを必ず一連で回して毎回削除する運用が前提。
- これまでの削除実績（TBC, 単一DOM対象）：
  - `drop_n_if_covered` 適用で 664 件の n-* をHTMLから削除、CSS側は 884 セレクタ/ルール削除。
  - 残存 n-* は 165（当時の集計）。ブロッカー（593クラス分）は JSON に出力済み。

## 直近のTODO（優先順）
1) 単一DOMの整流を再適用（バックアップ付き）
   - ensure-style-order → escalate-alias-specificity
   - add_section_row_alias / add_section_card_alias
   - mirror_n_selectors_to_alias（@media含め）
   - drop_n_if_covered（--strict --allow-media-layout --allow-complex-layout）
   - prune_unused_n_css_rules
2) エイリアス収束の安定化
   - canonicalize_bem_variants を通す
   - alias_overrides.json を（必要になり次第）導入し、ぶれを強制収束
3) 視覚の完全昇格
   - annotate_generic_components → build_alias_css_from_html（カード等の背景/影/角丸をSECTION__*へ）
4) 再度 drop/prune
   - ブロッカーが減っていれば追加で n-* を削除

## 検証手順（チェックリスト）
- 単一HTML（2DOMなし）であること
  - index.html に `device-pc` / `device-sp` が存在しない（SINGLE_DOM昇格済み）
- PC/SP 表示
  - PC: Auto Layout（横並び/等分/gap）が効く、視覚（shadow/border）が出る
  - SP（@media）: 縦積み/等分が効く、視覚が出る（alias CSSが当たっている）
- n-* 削除
  - HTMLの n-* が最小化されている
  - CSSの未使用 n-* セレクタが剪定されている
- レポート
  - `n_drop_blockers.json` に残った理由が出る（未被覆/未ミラー/媒体依存/alias不足）

## コマンド（例）
```bash
# ビルド（.envを使う）
python figma_02_build_from_json.py

# 単一DOM（ルート）に整流適用（バックアップ付き）
ROOT='figma_images/TBCグループ株式会社様_Design'
python tools/ops/ensure_style_link_order.py --root "$ROOT" --backup
python tools/ops/escalate_alias_specificity.py --root "$ROOT" --backup
python tools/ops/add_section_row_alias.py --root "$ROOT" --backup
python tools/ops/add_section_card_alias.py --root "$ROOT" --backup
python tools/ops/mirror_n_selectors_to_alias.py --root "$ROOT" --backup
python tools/ops/drop_n_if_covered.py --root "$ROOT" --strict --allow-media-layout --allow-complex-layout --backup
python tools/ops/prune_unused_n_css_rules.py --root "$ROOT" --backup
python tools/ops/report_n_drop_blockers.py --root "$ROOT"

# ぶれの正規化（必要時）
python tools/canonicalize_bem_variants.py --root "$ROOT" --backup
python tools/ops/alias_overrides_apply.py --root "$ROOT" --map alias_overrides.json --backup
```

## 補足
- 単一HTMLでSPが当たらない時は、HTML側に alias/SECTION__row などの目印が不足しているか、CSS側がまだ .n-* 前提になっている。整流（抽出/昇格/ミラー）を当て直す。
- n-* は生成直後は必ず付く（仕様）。POST_OPS_* をONにして「生成→整流」を自動で回すことで、毎回n-*削除を維持する。

## 未解決/注意事項
- alias収束のぶれ： canonicalize + overrides で潰す。最初は空の overrides で回し、divergenceを見て最小限登録。
- Waste report の最終段で combined_css_file 名参照の警告が一時的に出る箇所あり（SINGLE_DOM分岐後のログ類を要微修正）。

---
本ドキュメントを次担当へ渡し、以降は「単一HTML＋aliasベース＋自動整流（POST_OPS_*）」を前提に進めてください。

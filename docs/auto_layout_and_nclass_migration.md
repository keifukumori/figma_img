# Figma → HTML/CSS ジェネレータ 安定化メモ（Auto Layout と n- 移行）

このドキュメントは、今回の調整内容と設計方針、変更箇所、今後の運用手順を整理したものです。生成物（HTML/CSS）を直接編集せず、ジェネレータとポスト処理のみで安定・一般化することを前提としています。

## 目的
- 別デザインでも同じ規則で再現できるジェネレーション（再現性）
- レイアウト/タイポ/例外の役割分離に基づく運用保守性
- 最終的に `.n-*`（固有クラス）をゼロに近づける段階的移行

## 方針（役割分離）
- レイアウト: ユーティリティ/BEM（`fx-row|fx-col`, `g-*`, `jc-*`, `ai-*`, `fw-wrap`, `min-w-0` 等）
- タイポ: トークン（`TEXT_TOKEN_MODE=section_local` もしくは `role`、`figma-style-*` も併用）
- 例外（固有見た目）: `.n-*`（段階的に alias/トークンに移管し削減）

## 問題と解決の要点

### 1) alias への色/余白の伝搬で広域崩れ
- 問題: `.n-*` の `color:` や `padding:` を alias（例: `about__text`）へ複製し、広域に伝搬 → 白文字や余白の意図しない波及。
- 対策:
  - `tools/mirror_n_selectors_to_alias.py` で `color` と `margin/padding` をミラーから除外
  - `tools/alias_graft_for_residual_n.py` で `color` と `margin/padding` を含むルールはグラフト対象外
  - 生成器（`fetch_figma_layout.py`）で alias 出力を「ビジュアル限定（背景/枠/影など）＋構造 alias（`__row-item`/`__card`）には内側 padding 許可」に制限

### 2) Auto Layout の取りこぼし
- 問題: Auto Layout の `gap` は出るが、子要素の `flex:`（basis/配分）がフィルタで落ち、2 カラム配分が効かないケース
- 対策:
  - 非テキスト要素でも `flex:`/`align-self` を許可（`fetch_figma_layout.py:add_node_styles`）
  - Auto Layout 情報（gap/justify/align/wrap）を `layout_info` に格納し、`fx/g/jc/ai/fw-wrap` を確実に付与
  - 子要素の配分は Auto Layout 優先（ABB フォールバック）。`.n-*` に `flex: 0 0 <px|%>; min-width:0` を出力
  - デバッグ用に `.env: DEBUG_AL=true` で `data-al-mode/gap/justify/align` を HTML に付与

### 3) DOM ネストの破損
- 問題: クラス追記処理（グラフト）が 1 行のタグ置換で“残りの行”を捨て、`<p>` の閉じタグが失われ不正ネスト化
- 対策:
  - `tools/alias_graft_for_residual_n.py` の HTML 置換を修正（置換前後の文字列を保持）
  - 空/空白のみの TEXT ノードは出力しない（`fetch_figma_layout.py` の TEXT 分岐で早期 return）

### 4) ラッパーの自動縮約/背景ラッパー追加で構造がズレる
- 方針変更:
  - `.env: FLATTEN_SHALLOW_WRAPPERS=false`（薄いラッパーを潰さない）
  - `.env: SECTION_WRAPPER_MODE=full`（従来の `<section> > .container > .inner` で Figma 構造を維持）
  - 横 padding は trim→clamp へ（`HPAD_MODE=clamp`）

## 主要な変更（ファイルと箇所）

### fetch_figma_layout.py（生成器）
- Auto Layout 反映強化
  - layout_info に `gap/justify/align/wrap` を保存（`analyze_layout_structure`）
  - `generate_layout_class` で `fx-row|fx-col`, `g-*`, `jc-*`, `ai-*`, `fw-wrap` を付与
  - 子要素へ `flex:`/`min-width:0`/`align-self` を出力（`_child_auto_layout_rules`）
  - 非テキスト要素のフィルタで `flex:`/`align-self` を許可（`add_node_styles`）
- alias への出力
  - alias には「ビジュアル限定」を出力（背景/枠/影/フィルタなど）。構造 alias（`__row-item`/`__card`）のみ内側 padding を許可
  - fallback の text-size-* に color を含めるかを `.env: FALLBACK_TEXT_CLASS_INCLUDE_COLOR` で制御（既定は false 推奨）
- ネスト/構造の安定
  - 空 TEXT をスキップ
  - `.env: FLATTEN_SHALLOW_WRAPPERS=false`, `SECTION_WRAPPER_MODE=full` を推奨
  - 横 padding 正規化を clamp に（`HPAD_MODE=clamp`）
- デバッグ
  - `.env: DEBUG_AL=true` で `data-al-*` 属性を HTML に埋め込み
  - 位置ベース行グループの可否/閾値を `.env: ALLOW_POSITION_GROUPING`, `POSITION_Y_OVERLAP_THRESHOLD` で調整

### tools/mirror_n_selectors_to_alias.py（ミラー）
- alias へミラー時に `color` と `margin/padding` を除外（spacing/色の広域伝搬を防止）

### tools/alias_graft_for_residual_n.py（グラフト）
- ルール本文に `color` または `margin/padding` を含む場合はグラフトしない
- HTML クラス追記の置換を安全化（行の前後を保持して閉じタグ破損を防止）

### tools/report_n_drop_blockers.py（レポート）
- `style.css` と `style-common.css` を解析し、`.n-*` が落ちない理由（missing_props、selector_complex/media）を JSON で出力
  - 出力先: `figma_images/<Project>/n_drop_blockers.json`
  - `by_class[n-xxx]` ごとに `missing_props`（カバーされていないプロパティ）や `alias_contexts` を集計

### .env（設定）
- 代表的な変更
  - `FLATTEN_SHALLOW_WRAPPERS=false`
  - `SECTION_WRAPPER_MODE=full`
  - `HPAD_MODE=clamp`
  - `N_NODE_VISUAL_ONLY=true`（.n-* は見た目中心。レイアウトはユーティリティ/alias）
  - `N_CLASS_ALIAS_UNIQUE_ONLY=false`（共有 alias CSS を出力）
  - `POSTPROCESS_COMMON=true`, `POSTPROCESS_COMPONENTS=true`
  - `POST_OPS_*` は strict で `.n-*` の削減に寄与

## n- の段階的削減フロー
1. レポート生成: `python tools/report_n_drop_blockers.py --root <出力ディレクトリ>`
2. `missing_props` を確認し、ユーティリティ/BEM/alias/トークンへ移管（必要に応じて alias override）
3. `drop_n_if_covered`（strict）でHTMLから `.n-*` を削除、未使用 CSS を剪定
4. 反復し、`.n-*` を最小化→ゼロへ

## トークン化ガイド（何をどこへ落とし込むか）

この章は「どの要素の見た目を、どの層（トークン/alias/ユーティリティ）に落とすか」の具体指針です。最終的に `.n-*` を不要にするための移管先の決め方です。

- レイアウト（並び・間隔・折返し）
  - ユーティリティへ: `fx-row|fx-col`, `g-<px>`（itemSpacing）, `jc-*`（主軸揃え）, `ai-*`（交差軸揃え）, `fw-wrap`, `min-w-0`
  - 子の配分（2カラムなど）: 子要素に `flex: 0 0 <px|%>`（Auto Layout/ABB由来）を付与。将来的に比率ユーティリティ化する場合は `basis-*` マクロへ移管可
  - 原則として alias にレイアウトは置かない（構造 alias の内側 padding のみ例外）

- タイポグラフィ（フォント/サイズ/行間/字間/装飾/変形/整列）
  - トークンへ:
    - 役割ベース（推奨）: `TEXT_TOKEN_MODE=role` → `t-heading--h1/h2/h3/h4`, `t-body`, `t-note`
    - セクションローカル: `TEXT_TOKEN_MODE=section_local` → `about__heading`, `about__text_01` など
  - Figma スタイル名ベース: `figma-style-*` を補助的に併用（同名スタイルの再利用に有効）
  - ポイント: テキスト色は基本トークン（または `.n-*` が残る間は .n 側）で管理し、alias へは伝搬しない

- 余白（padding/margin）
  - コンテナ gap（`g-<px>`）中心に統一。要素側の大きな padding は避ける
  - ブロック間の余白は spacing ユーティリティ（`pb-<px>`, `pt-<px>`, `px-<px>`, `py-<px>`）をブロック側に付与
  - 構造 alias（`__row-item`/`__card`）のみ内側 padding を alias 側で許容
  - alias への `margin/padding` ミラー/グラフトは無効化済み

- 色/背景/影/枠（ビジュアル）
  - セクション BEM alias へ: 共通の見た目（例: カードの白背景＋影＋角丸）→ `section__card`
  - 汎用ユーティリティ（将来）: 背景色/枠/影をトークン化する場合は、専用ユーティリティ or 変数設計（CSS Variables）を導入
  - 注意: alias への `color` は伝搬しない。テキスト色はトークン or `.n-*`（移行中）に保持

- 画像関連
  - 比率は `aspect-ratio`（可能ならユーティリティ化）
  - 横いっぱいに出す背景画像ブロックは `bg-fullbleed` を用いる
  - 行先頭の画像ブリードなどのマクロ（例: `card-img-bleed-x`）は、将来 `macros.json` にて定義・適用

### 決定フロー（n- → 置き換え先）
1. レポートで `missing_props` を見る
2. 各プロパティの置き場を決める
   - flex/basis/min-width → 子 `.n-*` の flex（将来 `basis-*` マクロへ）
   - display/flex-direction/gap/jc/ai/flex-wrap → ユーティリティ
   - padding/margin → ブロック側 spacing ユーティリティ（例外: `__row-item`/`__card` の内側 padding）
   - color/line-height/font-weight/… → タイポトークン（role or section_local）
   - background/border/box-shadow → セクション BEM alias（例: `section__card`）
3. 置換後に `drop_n_if_covered`（strict）を実行し、`.n-*` を削除

## トラブルシューティング
- 見出しや本文の下余白が大きい/小さい: コンテナ gap に寄せるのが基本。要素側の大きな padding は避け、必要ならブロック側の spacing ユーティリティ（例: `pb-24`）を使用
- 同型パーツの統一が弱い: `POSTPROCESS_COMPONENTS=true`、alias override の適用、`TEXT_TOKEN_MODE=role` への切替を検討
- 行グループ誤判定: `.env` の `ALLOW_POSITION_GROUPING=false` あるいは `POSITION_Y_OVERLAP_THRESHOLD` を上げて抑制

## 参考（主な変更点のコード位置）
- `fetch_figma_layout.py`
  - Auto Layout 解析: `analyze_layout_structure`, `generate_layout_class`, `_child_auto_layout_rules`
  - ノードスタイル許可: `add_node_styles`（`flex:`/`align-self` 許可）
  - alias 出力ポリシー（ビジュアル限定＋構造 alias 内側 padding）: ノードCSS出力部
  - 空 TEXT スキップ: TEXT 分岐の早期 return
  - デバッグ属性: `DEBUG_AL` による `data-al-*` 出力
- `tools/mirror_n_selectors_to_alias.py`
  - `_strip_text_color`: `color`/`margin`/`padding` の除外
- `tools/alias_graft_for_residual_n.py`
  - `_has_text_color`/`_has_spacing` で除外、HTML置換の安全化
- `tools/report_n_drop_blockers.py`
  - `n_drop_blockers.json` の生成

## 次アクション
- いま生成した `n_drop_blockers.json` をレビューし、優先的に移管すべき `missing_props` を洗い出し
- 必要に応じて alias override マップ（語彙固定）を用意
- `TEXT_TOKEN_MODE=role` での実証（見出し/本文の統一強化）が必要なら切替テスト

以上により、生成ロジックだけで安定・再現性を確保しつつ、`.n-*` からトークン/alias/ユーティリティへの段階的移行を進められます。

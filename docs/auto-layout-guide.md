# Figma Auto Layout → HTML/CSS ガイドと今回の対応まとめ

## 概要（Executive Summary）
- 目的: FigmaのAuto LayoutをHTML/CSSにできるだけ忠実に反映し、レイアウトの揺れや不自然な余白を抑える。
- 主な課題: 2カラム行での横幅揺れ、余白の二重取り、非表示/装飾レイヤーが出力に混入。
- 対応方針: 「左=固定（FIXED）、右=残り（FILL）」の意図を崩さず、間隔はgapで一元管理。コンテンツ（img）がアイテム幅を押し広げないよう制御。ノイズは除外。

---

## 問題の整理（何が起きたか / 何をやりたかったか）
- やりたいこと
  - Figmaでは「画像＋テキスト」の2カラム行が繰り返し出てくる。左の画像エリアは固定幅、右のテキストは残り幅で可変、という設計意図。
  - 文章ブロックではAuto Layoutの`itemSpacing`（均一な間隔）に沿って、過不足ない余白で読みやすくしたい。
- 起きていた問題
  - HTML/CSSに変換後、2カラムの左画像エリア幅がセクションによって微妙に変化（揺れ）。
  - 見出しと本文の間やブロック間の余白が、意図より広がる/詰まる（gapと既定marginの二重取り）。
  - Figma上で非表示のレイヤーや、装飾（下線など）の細い矩形が出力に混ざり、行判定や余白に影響。

---

## 非エンジニア向け説明（やさしい言葉で）
- 写真と文章を横に並べた行で、写真の横幅が場所によって少しずつ違って見える現象がありました。
- また、文章同士のスキマが必要以上に広がったり、逆に詰まったりすることがありました。
- わたしたちは「写真の幅は設計どおりに固定・文章は残りの幅を使う」というルールに揃えました。文章の間のスキマは1カ所（コンテナ）の設定でまとめて管理し、余計な二重の余白は無くしました。
- さらに、Figmaで非表示にしている要素や、飾り（下線など）は出力しないようにして、表示が乱れないようにしています。

---

## 初級エンジニア向け（全体ロジックと対応）
- 症状の主因
  - Flexboxの最小幅推定（min-content）と、`img`の`width/max-width:100%`が干渉し、列幅がコンテンツに押されて揺れる。
  - 「2カラム等分」CSSが、FigmaのFIXED幅を上書きしてしまう。
  - Auto Layoutの`itemSpacing`と見出し(`h*`)の既定`margin`が重なり、余白が二重取りになる。
  - 非表示レイヤー/装飾矩形が出力に混ざる。
- 対応概要
  - 2カラム安定化（左=固定、右=残り）
    - 左カラムがFigmaでFIXEDならラッパーに`width:[px]; flex:0 0 [px]`を付与（親がHORIZONTALのAuto Layout）。
    - `.layout-2col > * { min-width:0 }`でコンテンツの押し広げを無効化。
    - 先頭カラムの`img`は`width:100%`を付けず、`height:auto; display:block`に（幅主張をしない）。
  - 等分CSSの抑止
    - FIXEDが含まれる場合、比率ベースの`flex-basis:%`付与（等分・比率化）を抑止し、固定幅を尊重。
  - 余白の二重取り解消
    - Auto Layout内の`h1..h6, p`は既定`margin:0`にし、間隔は`gap`で一元管理。
    - `itemSpacing<0`は0へ（重ねない方針）。
  - ノイズ除外
    - `visible:false`のノードは除外。
    - `layoutPositioning:ABSOLUTE`かつ高さが極小（例: ≦14px）の矩形は装飾とみなしフローから除外。
- 確認のコツ
  - DevToolsで左カラムのラッパーに`width`と`flex-basis`が出ているか、右は`flex:1`で残り幅を取っているか確認。
  - 余白は`gap`で効いていること（見出し/段落の`margin`が増やしていないこと）を確認。

---

## 中上級エンジニア向け（詳細と設計判断）
### 1) Figma → CSSマッピング指針
- コンテナ
  - `layoutMode: HORIZONTAL|VERTICAL` → `display:flex` + `flex-direction: row|column`
  - `itemSpacing` → `gap`（負値は0へ丸め）
  - `paddingTop/Right/Bottom/Left` → `padding`
  - `primaryAxisAlignItems / counterAxisAlignItems` → `justify-content / align-items`
  - `layoutWrap: WRAP` → `flex-wrap: wrap`
- 子の寸法
  - Sizing（横方向 / HORIZONTAL親下）:
    - FIXED → `flex:0 0 auto` ＋ ラッパーに`width:px`を許容
    - FILL / `layoutGrow>0` → `flex:1 1 auto`
    - HUG / undefined → `flex:0 1 auto`
  - Sizing（縦方向 / VERTICAL親下）: 高さは柔軟（`skip_h`）を基本としつつ、`aspect-ratio`や`min-height`で崩れを防ぐ。
- constraints
  - LEFT_RIGHT → `width:100%`、CENTER → `margin:auto`または`align-self:center` 等、main/cross軸に応じ変換（実装済）。

### 2) 2カラム幅揺れの根本と対処
- 根本: Flexアイテムの`min-width:auto`でコンテンツのmin-content幅が幅決定に影響、さらに`img width/max-width:100%`が「親いっぱい」を主張。
- 対処:
  - `.layout-2col > * { min-width:0 }`で押し広げを抑止。
  - 先頭カラムの`img`は幅を主張しない（`width:100%`を使わず`height:auto`のみ）。
  - 左カラムFIXED時はラッパーに`width:[px]; flex:0 0 [px]`を付け、固定＋残り配分を明示。
  - 子にFIXEDが含まれる場合、比率付与（`flex-basis:%`）はスキップし、固定優先に。

### 3) 余白設計
- Auto Layoutの`itemSpacing`を第一級（`gap`）とし、`h*/p`の規定`margin`はリセット。
- `paragraph_spacing`は`margin-bottom`として付与（過不足があればここで調整）。

### 4) ノイズ除外
- `visible:false` は除外。
- 下線等は`layoutPositioning:ABSOLUTE`かつ極薄（≦14px）を装飾とみなしフロー除外。

### 5) 既知の限界
- HUG/FILLの厳密挙動（入れ子・wrap時）や、マスク・imageTransformの完全再現は追加実装の余地あり。
- テキストの禁則・改行規則差による高さの微ズレ。

---

## チェックリスト（検収・QA）
- 2カラム行で、左の画像エリアに`width(px)`と`flex:0 0 px`が付与されているか？
- 右のテキストエリアは`flex:1`で残り幅を取得しているか？
- `.layout-2col > * { min-width:0 }`が効いているか？先頭カラムの`img`に`width:100%`が付いていないか？
- Auto Layout内で、`h*/p`の既定`margin`が0になり、間隔は`gap`で統一されているか？
- 非表示や装飾の薄いABSOLUTE矩形が出力に混ざっていないか？

---

## ロールバック/リスク管理
- 今回の調整は局所的（スタイル注入・子ルール判定のガード）で、広範な仕様変更は避けた。
- 不具合発生時は、
  - 2カラム安定化（`min-width:0`/img幅主張抑止/固定幅の`flex:0 0 px`）の個別無効化が容易。
  - 等分CSSの適用/抑止を切替可能（環境変数・ガード条件）。

---

## 付録：よくある質問（FAQ）
- Q: どうして`img width:100%`を外すと揃うの？
  - A: Flex行の幅決定にコンテンツのmin-content幅が影響するため、`width/max-width:100%`は「親いっぱい」を主張して列幅を押し広げます。外すことで列幅はラッパー（カラム）の指定に従うだけになり安定します。
- Q: Figma側の幅（例えば320px）はどこから？
  - A: Auto Layout内の子の`layoutSizingHorizontal: FIXED`と`absoluteBoundingBox.width`に対応。任意の固定ではなくFigmaの指定値です。

---

## まとめ
- 「左=固定、右=残り」というAuto Layoutの意図を保ちながら、Flexbox特有の幅決定ルールや既定マージン/装飾ノイズによる揺れを抑えました。余白は`gap`で一元管理し、コンテンツは列幅を主張しない方針にすることで、Figmaの見た目に近い安定した出力を得ています。


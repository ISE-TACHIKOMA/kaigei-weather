# かいげい 気象データ配信

VRChat ワールド「潜水艦チルワ」の気象モニター用に、実際の気象・海象データを4時間ごとに画像にして配信する。

- データ: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0)
- 公開ファイル:
  - `docs/wx2.png`（データ画像。東経 122〜206° × 北緯 10〜46°, 2° ごと 43×19）, `docs/wx2.json`（更新時刻・格子の範囲など）
  - `docs/wx3.png`（外側の粗い格子。東経 40〜205° × 南緯 70°〜北緯 80°, 5° ごと 34×31。1日 1回更新）, `docs/wx3.json`
  - `docs/wx.png`, `docs/wx.json`（以前のワールド用。東経 122〜152° × 北緯 10〜40°, 1.5° ごと 21×21。wx2 の格子から補間して作る）
  - `docs/feed_state.json`（前回の取得時刻と API の使用量の記録。次の実行で使う）
- 更新の間隔（Open-Meteo の無料枠 1日 10,000 回に収めるため）:
  - 内側の現在の気象: 4時間ごと
  - 内側の 1週間予報と海況（波・海流）: 12時間ごと（日本時間の日付が変わった後と、その 12時間後）
  - 外側の格子: 1日 1回（日本時間の日付が変わった後）
  - 合計 1日 約 8,300 回。手動で実行しても上限（直近 24時間 9,500 回）を超えそうなときは、前回の値を使い回す
  - すべて取り直すときは `python fetch_weather.py docs --full`

## 公開のしかた（最初の1回だけ）

1. GitHub で新しい **Public** リポジトリを作る（例: `kaigei-weather`）
2. このフォルダの中身をすべてアップロード（`.github` フォルダも含む）
3. リポジトリの Settings → Pages → Branch を `main` / `/docs` にして Save
4. Actions タブ → 「update weather」→ Run workflow（以後は4時間ごとに自動）
5. `https://<ユーザー名>.github.io/kaigei-weather/wx.png` が開けたら完了
6. Unity の SubmarineSystem/WeatherSystem の `Data Url` にその URL を入れる（今は wx2.png / wx2.json と wx3.png / wx3.json。メニュー「潜水艦/改修15」で設定される）

# かいげい 気象データ配信

VRChat ワールド「潜水艦チルワ」の気象モニター用に、実際の気象・海象データを1時間ごとに画像にして配信する。

- データ: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0)
- 公開ファイル: `docs/wx.png`（データ画像）, `docs/wx.json`（更新時刻など）

## 公開のしかた（最初の1回だけ）

1. GitHub で新しい **Public** リポジトリを作る（例: `kaigei-weather`）
2. このフォルダの中身をすべてアップロード（`.github` フォルダも含む）
3. リポジトリの Settings → Pages → Branch を `main` / `/docs` にして Save
4. Actions タブ → 「update weather」→ Run workflow（以後は毎時自動）
5. `https://<ユーザー名>.github.io/kaigei-weather/wx.png` が開けたら完了
6. Unity の SubmarineSystem/WeatherSystem の `Data Url` にその URL を入れる

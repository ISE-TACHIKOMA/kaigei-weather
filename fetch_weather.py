# 実際の気象・海象データを取得して、VRChat ワールド用の画像 (wx.png) と情報 (wx.json) を作る
# データ: Open-Meteo (https://open-meteo.com/, CC BY 4.0)  Weather Forecast API / Marine Weather API
# 使い方: python fetch_weather.py <出力フォルダ>
#
# wx.png の形式 (WeatherSystem.cs / WeatherMap.shader と一致させること)
#   N×N の格子 (東経 122〜152°, 北緯 10〜40°, 下の行が南) を横に 3 枚並べる (幅 3N, 高さ N)
#   タイル0: R=気圧 950〜1050 hPa   G=気温 -20〜40 ℃      B=雲量 0〜100 %
#   タイル1: R=風 東向き -40〜40 m/s G=風 北向き -40〜40   B=波高 0〜15 m
#   タイル2: R=海流 東向き -2〜2 m/s G=海流 北向き -2〜2  B=陸 (255) / 海 (0)
#   タイル3: R=現在の降水量 sqrt(0〜30 mm/h)
#   タイル4〜10: 1週間予報 (今日 = タイル4)
#     下段 (画像の下半分): R=最高気温 -20〜40 ℃  G=最低気温 -20〜40 ℃  B=降水量 sqrt(0〜200 mm/日)
#     上段 (画像の上半分): R=天気コード (WMO, そのまま 0〜99)  G=最大風速 0〜40 m/s
#   画像は幅 11N, 高さ 2N。下半分の左 3 タイルは以前と同じ形式 (古いワールドも読める)
import json, math, os, sys, time, urllib.request
from datetime import datetime, timezone
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs"
os.makedirs(OUT, exist_ok=True)
LON0, LON1, LAT0, LAT1, N = 122.0, 152.0, 10.0, 40.0, 21
lons = [LON0 + (LON1 - LON0) * i / (N - 1) for i in range(N)]
lats = [LAT0 + (LAT1 - LAT0) * j / (N - 1) for j in range(N)]
points = [(lat, lon) for lat in lats for lon in lons]  # j (緯度) が外側

def fetch(base, fields, chunk=100, daily=None):
    out = []
    for k in range(0, len(points), chunk):
        part = points[k:k + chunk]
        url = (base + "?latitude=" + ",".join(f"{p[0]:.2f}" for p in part) +
               "&longitude=" + ",".join(f"{p[1]:.2f}" for p in part) + "&current=" + ",".join(fields))
        if daily:
            url += "&daily=" + ",".join(daily) + "&forecast_days=7&timezone=Asia%2FTokyo"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = json.loads(r.read())
                break
            except Exception as e:
                if attempt == 3:
                    raise
                time.sleep(5)
        if isinstance(data, dict):
            data = [data]
        for d in data:
            c = dict(d.get("current", {}))
            c["_daily"] = d.get("daily", {})
            out.append(c)
        time.sleep(1)
    return out

DAILY = ["weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "wind_speed_10m_max"]
wx = fetch("https://api.open-meteo.com/v1/forecast",
           ["pressure_msl", "temperature_2m", "cloud_cover", "wind_speed_10m", "wind_direction_10m", "precipitation"], daily=DAILY)
sea = fetch("https://marine-api.open-meteo.com/v1/marine",
            ["wave_height", "ocean_current_velocity", "ocean_current_direction"])

def fill_missing(rows, key):
    """値が欠けた地点を、まわりの地点の平均で埋める"""
    for _ in range(3):
        for idx, r in enumerate(rows):
            if r.get(key) is not None:
                continue
            j, i = divmod(idx, N)
            vals = [rows[jj * N + ii].get(key) for jj in range(max(0, j - 1), min(N, j + 2))
                    for ii in range(max(0, i - 1), min(N, i + 2))]
            vals = [v for v in vals if v is not None]
            if vals:
                r[key] = sum(vals) / len(vals)

for k in ("pressure_msl", "temperature_2m", "cloud_cover", "wind_speed_10m", "wind_direction_10m", "precipitation"):
    fill_missing(wx, k)

def enc(v, lo, hi):
    return max(0, min(255, int(round((v - lo) / (hi - lo) * 255))))

img = Image.new("RGB", (N * 11, N * 2))
px = img.load()
stats = {"pressure": [], "temp": []}
for idx, (w, m) in enumerate(zip(wx, sea)):
    j, i = divmod(idx, N)
    row = 2 * N - 1 - j                        # 下半分 (画像の上 = 北)
    top = N - 1 - j                            # 上半分
    p = w.get("pressure_msl") or 1013.0
    t = w.get("temperature_2m")
    t = 15.0 if t is None else t
    c = w.get("cloud_cover") or 0.0
    ws = (w.get("wind_speed_10m") or 0.0) / 3.6
    wd = math.radians(w.get("wind_direction_10m") or 0.0)   # 吹いてくる方位
    wu, wv = -ws * math.sin(wd), -ws * math.cos(wd)
    land = m.get("wave_height") is None
    wave = 0.0 if land else m["wave_height"]
    cs = 0.0 if land or m.get("ocean_current_velocity") is None else m["ocean_current_velocity"] / 3.6
    cd = math.radians(m.get("ocean_current_direction") or 0.0)  # 流れていく方位
    cu, cv = cs * math.sin(cd), cs * math.cos(cd)
    px[i, row] = (enc(p, 950, 1050), enc(t, -20, 40), enc(c, 0, 100))
    px[N + i, row] = (enc(wu, -40, 40), enc(wv, -40, 40), enc(wave, 0, 15))
    px[2 * N + i, row] = (enc(cu, -2, 2), enc(cv, -2, 2), 255 if land else 0)
    pr = w.get("precipitation") or 0.0
    px[3 * N + i, row] = (enc(math.sqrt(max(pr, 0.0)), 0, math.sqrt(30)), 0, 0)
    dl = w.get("_daily") or {}
    for day in range(7):
        def g(key, default):
            vals = dl.get(key) or []
            v = vals[day] if day < len(vals) else None
            return default if v is None else v
        tmax, tmin = g("temperature_2m_max", t), g("temperature_2m_min", t)
        rain = g("precipitation_sum", 0.0)
        code = int(g("weather_code", 0))
        wmax = g("wind_speed_10m_max", 0.0) / 3.6
        x = (4 + day) * N + i
        px[x, row] = (enc(tmax, -20, 40), enc(tmin, -20, 40), enc(math.sqrt(max(rain, 0.0)), 0, math.sqrt(200)))
        px[x, top] = (max(0, min(255, code)), enc(wmax, 0, 40), 0)
    stats["pressure"].append(p)
    stats["temp"].append(t)

img.save(os.path.join(OUT, "wx.png"))
now = datetime.now(timezone.utc)
days = (wx[0].get("_daily") or {}).get("time") or []
meta = {"updated": now.strftime("%Y-%m-%dT%H:%MZ"), "source": "Open-Meteo (CC BY 4.0)", "days": days,
        "grid": N, "lon": [LON0, LON1], "lat": [LAT0, LAT1],
        "pressure_min": round(min(stats["pressure"]), 1), "pressure_max": round(max(stats["pressure"]), 1)}
with open(os.path.join(OUT, "wx.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False)
with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
    f.write("<!doctype html><meta charset=utf-8><title>KAIGEI weather feed</title>"
            "<p>VRChat world data. Weather data by <a href=https://open-meteo.com/>Open-Meteo.com</a> (CC BY 4.0).</p>"
            f"<p>Updated {meta['updated']}</p><img src=wx.png width=630 style=image-rendering:pixelated>")
print("ok", meta)

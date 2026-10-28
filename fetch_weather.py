# 実際の気象・海象データを取得して、VRChat ワールド用の画像 (wx.png) と情報 (wx.json) を作る
# データ: Open-Meteo (https://open-meteo.com/, CC BY 4.0)  Weather Forecast API / Marine Weather API
# 使い方: python fetch_weather.py <出力フォルダ>
#
# wx.png の形式 (WeatherSystem.cs / WeatherMap.shader と一致させること)
#   N×N の格子 (東経 122〜152°, 北緯 10〜40°, 下の行が南) を横に 3 枚並べる (幅 3N, 高さ N)
#   タイル0: R=気圧 950〜1050 hPa   G=気温 -20〜40 ℃      B=雲量 0〜100 %
#   タイル1: R=風 東向き -40〜40 m/s G=風 北向き -40〜40   B=波高 0〜15 m
#   タイル2: R=海流 東向き -2〜2 m/s G=海流 北向き -2〜2  B=陸 (255) / 海 (0)
import json, math, os, sys, time, urllib.request
from datetime import datetime, timezone
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs"
os.makedirs(OUT, exist_ok=True)
LON0, LON1, LAT0, LAT1, N = 122.0, 152.0, 10.0, 40.0, 21
lons = [LON0 + (LON1 - LON0) * i / (N - 1) for i in range(N)]
lats = [LAT0 + (LAT1 - LAT0) * j / (N - 1) for j in range(N)]
points = [(lat, lon) for lat in lats for lon in lons]  # j (緯度) が外側

def fetch(base, fields, chunk=100):
    out = []
    for k in range(0, len(points), chunk):
        part = points[k:k + chunk]
        url = (base + "?latitude=" + ",".join(f"{p[0]:.2f}" for p in part) +
               "&longitude=" + ",".join(f"{p[1]:.2f}" for p in part) + "&current=" + ",".join(fields))
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
        out += [d.get("current", {}) for d in data]
        time.sleep(1)
    return out

wx = fetch("https://api.open-meteo.com/v1/forecast",
           ["pressure_msl", "temperature_2m", "cloud_cover", "wind_speed_10m", "wind_direction_10m"])
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

for k in ("pressure_msl", "temperature_2m", "cloud_cover", "wind_speed_10m", "wind_direction_10m"):
    fill_missing(wx, k)

def enc(v, lo, hi):
    return max(0, min(255, int(round((v - lo) / (hi - lo) * 255))))

img = Image.new("RGB", (N * 3, N))
px = img.load()
stats = {"pressure": [], "temp": []}
for idx, (w, m) in enumerate(zip(wx, sea)):
    j, i = divmod(idx, N)
    row = N - 1 - j                            # 画像の上 = 北
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
    stats["pressure"].append(p)
    stats["temp"].append(t)

img.save(os.path.join(OUT, "wx.png"))
now = datetime.now(timezone.utc)
meta = {"updated": now.strftime("%Y-%m-%dT%H:%MZ"), "source": "Open-Meteo (CC BY 4.0)",
        "grid": N, "lon": [LON0, LON1], "lat": [LAT0, LAT1],
        "pressure_min": round(min(stats["pressure"]), 1), "pressure_max": round(max(stats["pressure"]), 1)}
with open(os.path.join(OUT, "wx.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False)
with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
    f.write("<!doctype html><meta charset=utf-8><title>KAIGEI weather feed</title>"
            "<p>VRChat world data. Weather data by <a href=https://open-meteo.com/>Open-Meteo.com</a> (CC BY 4.0).</p>"
            f"<p>Updated {meta['updated']}</p><img src=wx.png width=630 style=image-rendering:pixelated>")
print("ok", meta)

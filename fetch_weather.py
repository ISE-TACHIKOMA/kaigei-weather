# 実際の気象・海象データを取得して、VRChat ワールド用の画像と情報を作る
# データ: Open-Meteo (https://open-meteo.com/, CC BY 4.0)  Weather Forecast API / Marine Weather API
# 使い方: python fetch_weather.py <出力フォルダ> [--full]
#   --full: 前回のデータを使い回さず、すべて取り直す
#
# 出力
#   wx2.png / wx2.json : 内側の細かい格子。東経 122〜206° (= 西経 154°、ハワイまで) × 北緯 10〜46°, 2° ごと
#                        NX = 43 × NY = 19 (画像 473×38)。東経 180° より東も 180 より大きい値のまま (例: 真珠湾 = 202.03)
#   wx3.png / wx3.json : 外側の粗い格子。東経 40〜205° × 南緯 70°〜北緯 80°, 5° ごと
#                        NX3 = 34 × NY3 = 31 (画像 374×62)。海図全体 (東経 38〜207°, 南緯 71°〜北緯 80°) を覆う
#                        (端の 1〜2° は端の値)。内側の格子の範囲にある点は API に問い合わせず、内側の格子から補間して埋める
#                        ワールドは内側の格子の範囲では wx2 を (端の 2.5° で滑らかに切り替えて)、それ以外では wx3 を使う
#   wx.png / wx.json   : 以前のワールド用 (東経 122〜152°, 北緯 10〜40°, 1.5° ごと 21×21)。
#                        wx2 の格子から双線形補間で作る (陸の判定と天気コードは一番近い格子)
#   feed_state.json    : 前回の取得時刻と API の使用量の記録 (次の実行で使う)
#
# 画像の形式 (WeatherSystem.cs と一致させること)。格子 NX×NY (下の行が南、左の列が西)
#   タイル0: R=気圧 950〜1050 hPa   G=気温 -20〜40 ℃      B=雲量 0〜100 %
#            (wx3 は 気圧 920〜1070 hPa, 気温 -60〜45 ℃。南極・シベリアの寒さや南極海の低気圧が入るように)
#   タイル1: R=風 東向き -40〜40 m/s G=風 北向き -40〜40   B=波高 0〜15 m
#   タイル2: R=海流 東向き -2〜2 m/s G=海流 北向き -2〜2  B=陸 (255) / 海 (0)
#   タイル3: R=現在の降水量 sqrt(0〜30 mm/h)
#   タイル4〜10: 1週間予報 (今日 = タイル4)
#     下段 (画像の下半分): R=最高気温 -20〜40 ℃ (wx3 は -60〜45)  G=最低気温 (同じ)  B=降水量 sqrt(0〜200 mm/日)
#     上段 (画像の上半分): R=天気コード (WMO, そのまま 0〜99)  G=最大風速 0〜40 m/s
#   画像は幅 11×NX, 高さ 2×NY。下半分の左 3 タイルは最初の形式と同じ (古いワールドも読める)
#   wx3 の陸の点の波高・海流は、まわりの海の値で埋める (粗い格子を補間したとき、海岸の近くで弱まらないように。
#   陸かどうかはタイル2 の B で分かる)
#
# API の使用量 (Open-Meteo の無料枠: 1日 10,000 / 1時間 5,000 / 1分 600。1地点 = 1回、変数が 10 を超えると 変数/10 倍)
#   GitHub Actions で 4時間ごと (UTC 0, 4, 8, 12, 16, 20 時) に実行する。毎回取り直すのは内側の格子の現在の気象だけで、
#   ・内側の現在の気象 (6変数)                       : 毎回        817 地点 × 1.0           =   817
#   ・内側の 1週間予報 (+5変数で 11変数) と海況 (海の点だけ): 12時間ごと 817 × 0.1 増し + 779 = 約 861 増し
#   ・外側の気象 + 1週間予報 (11変数) と海況 (海の点だけ)  : 1日 1回   918 × 1.1 + 622     = 約 1,632
#   → 1日 約 8,255 回 (4 × 817 + 2 × 1,678 + 1,632)。直近 22時間の使用量を feed_state.json に記録し、
#     9,500 を超えそうなら、使い回せるもの (予報・海況・外側の格子) は前回の画像の値を使い回す
#   12時間ごと・1日 1回の取り直しは、日本時間の日付が変わった後の最初の実行 (UTC 16 時) に合わせる (予報の「今日」がずれないように)
import json, math, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from PIL import Image

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
FULL = "--full" in sys.argv
OUT = ARGS[0] if ARGS else "docs"
os.makedirs(OUT, exist_ok=True)

# 内側の格子 (wx2)
LON0, LON1, LAT0, LAT1, NX, NY = 122.0, 206.0, 10.0, 46.0, 43, 19
lons = [LON0 + (LON1 - LON0) * i / (NX - 1) for i in range(NX)]
lats = [LAT0 + (LAT1 - LAT0) * j / (NY - 1) for j in range(NY)]
points = [(lat, lon) for lat in lats for lon in lons]  # j (緯度) が外側
# 外側の格子 (wx3)
XLON0, XLON1, XLAT0, XLAT1, NX3, NY3 = 40.0, 205.0, -70.0, 80.0, 34, 31
xlons = [XLON0 + (XLON1 - XLON0) * i / (NX3 - 1) for i in range(NX3)]
xlats = [XLAT0 + (XLAT1 - XLAT0) * j / (NY3 - 1) for j in range(NY3)]
xpoints = [(lat, lon) for lat in xlats for lon in xlons]
# 以前の格子 (wx)
OLON0, OLON1, OLAT0, OLAT1, ON = 122.0, 152.0, 10.0, 40.0, 21

# 陸 (#) と海 (.) の格子。上の行が北。ETOPO 2022 (1分) の格子点の標高から作った (標高 0 m 以上 = 陸)
# 陸の点は海況 (Marine API) を問い合わせない (API の使用量を減らすため)
INNER_MASK = [
    "########..#...#............................",
    "#######...##...............................",
    "####.......................................",
    "###........................................",
    "..##.....#.................................",
    "...#...###.................................",
    ".....###...................................",
    "...........................................",
    "...........................................",
    "...........................................",
    "...........................................",
    "...........................................",
    "...........................................",
    "...........................................",
    "#..........................................",
    "...........................................",
    "...........................................",
    ".#.........................................",
    "...........................................",
]
OUTER_MASK = [
    "...........#......................",
    "....#.....#####.....#.#...........",
    "....#.##################........##",
    ".###########################.#.###",
    "#######################..#......##",
    "####################....#.........",
    "#####################.............",
    "##.#################..............",
    "##.#############.#................",
    "################...#..............",
    "##.##############.................",
    "###...##########..................",
    ".###...###.###....................",
    "###....##...##....................",
    "###...............................",
    "##.............##.................",
    "#...........#.###.................",
    ".............#..#...##............",
    "................#.................",
    "#.#...............##.#............",
    ".#..............######............",
    ".#.............########...........",
    "...............########...........",
    "....................###...........",
    "..................................",
    "..........................#.......",
    "..................................",
    "..................................",
    "..................................",
    "..................................",
    "#########################.........",
]

def mask_land(mask, nx, ny, idx):
    j, i = divmod(idx, nx)
    return mask[ny - 1 - j][i] == "#"

DAYS = 7
CHUNK = 100          # 1 回の問い合わせの地点数
PER_MINUTE = 500     # Open-Meteo の無料枠は 1分 600 回まで。余裕を見て 500 に抑える
BUDGET = 9500        # 直近の使用量の上限 (無料枠は 1日 10,000)
WINDOW_H = 22        # 使用量を数える時間 (24時間だと、GitHub Actions の実行が遅れたとき前日の同じ時刻の実行まで数えてしまうため 22時間)
REUSE_SLOW_H = 11    # 内側の予報・海況を取り直す間隔 (時間。実行は 4時間ごとなので実質 12時間)
REUSE_OUTER_H = 23   # 外側の格子を取り直す間隔 (時間。実質 1日 1回)
used = 0.0           # 今回の使用量 (重み付きの回数)
requests_made = 0
errors = []

CURRENT = ["pressure_msl", "temperature_2m", "cloud_cover", "wind_speed_10m", "wind_direction_10m", "precipitation"]
DAILY = ["weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "wind_speed_10m_max"]
MARINE = ["wave_height", "ocean_current_velocity", "ocean_current_direction"]

def weight(nvars):
    """1地点あたりの回数 (変数が 10 を超えると 変数/10 倍。予報は 7日なので日数の割り増しは無し)"""
    return max(1.0, nvars / 10.0)

def api_lon(lon):
    """Open-Meteo は経度 -180〜180 しか受け付けないので、180 より東は 360 を引いて送る"""
    return lon - 360.0 if lon > 180.0 else lon

def fetch(base, pts, fields, daily=None):
    """pts の地点の current (と daily) を取得する。戻り値は地点ごとの dict (daily は "_daily" に入れる)"""
    global requests_made, used
    out = []
    w = weight(len(fields) + (len(daily) if daily else 0))
    for k in range(0, len(pts), CHUNK):
        part = pts[k:k + CHUNK]
        t0 = time.time()
        url = (base + "?latitude=" + ",".join(f"{p[0]:.2f}" for p in part) +
               "&longitude=" + ",".join(f"{api_lon(p[1]):.2f}" for p in part) + "&current=" + ",".join(fields))
        if daily:
            url += "&daily=" + ",".join(daily) + f"&forecast_days={DAYS}&timezone=Asia%2FTokyo"
        for attempt in range(5):
            try:
                requests_made += 1
                used += len(part) * w
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = json.loads(r.read())
                break
            except Exception as e:
                errors.append(f"{base.split('/')[2]} #{k // CHUNK} try{attempt}: {e}")
                if attempt == 4:
                    raise
                # 429 (回数の制限) のときは 1 分待つ
                time.sleep(65 if isinstance(e, urllib.error.HTTPError) and e.code == 429 else 5)
        if isinstance(data, dict):
            data = [data]
        if len(data) != len(part):
            raise RuntimeError(f"地点の数が合わない: {len(data)} != {len(part)}")
        for d in data:
            c = dict(d.get("current", {}))
            c["_daily"] = d.get("daily", {})
            out.append(c)
        # 1分あたりの回数を抑える
        wait = len(part) * w * 60.0 / PER_MINUTE - (time.time() - t0)
        if wait > 0:
            time.sleep(wait)
    return out

def fetch_marine(pts, land):
    """海の点だけ海況を取得する。陸の点は {} (= 陸の扱い)"""
    sea_idx = [k for k in range(len(pts)) if not land[k]]
    got = fetch("https://marine-api.open-meteo.com/v1/marine", [pts[k] for k in sea_idx], MARINE) if sea_idx else []
    out = [{} for _ in pts]
    for k, m in zip(sea_idx, got):
        out[k] = m
    return out

def fill_missing(rows, key, nx, ny):
    """値が欠けた地点を、まわりの地点の平均で埋める"""
    for _ in range(3):
        for idx, r in enumerate(rows):
            if r.get(key) is not None:
                continue
            j, i = divmod(idx, nx)
            vals = [rows[jj * nx + ii].get(key) for jj in range(max(0, j - 1), min(ny, j + 2))
                    for ii in range(max(0, i - 1), min(nx, i + 2))]
            vals = [v for v in vals if v is not None]
            if vals:
                r[key] = sum(vals) / len(vals)

# ---- 物理量の格子 (index = j * nx + i) ----
def new_grid():
    return {"p": [], "t": [], "c": [], "wu": [], "wv": [], "wave": [], "cu": [], "cv": [], "land": [], "rain": [],
            "tmax": [[] for _ in range(DAYS)], "tmin": [[] for _ in range(DAYS)], "drain": [[] for _ in range(DAYS)],
            "code": [[] for _ in range(DAYS)], "wmax": [[] for _ in range(DAYS)]}

def set_current(G, k, w):
    """現在の気象 (Forecast API の current) を格子の k 番目に入れる"""
    p = w.get("pressure_msl") or 1013.0
    t = w.get("temperature_2m")
    t = 15.0 if t is None else t
    ws = (w.get("wind_speed_10m") or 0.0) / 3.6
    wd = math.radians(w.get("wind_direction_10m") or 0.0)   # 吹いてくる方位
    G["p"][k] = p; G["t"][k] = t; G["c"][k] = w.get("cloud_cover") or 0.0
    G["wu"][k] = -ws * math.sin(wd); G["wv"][k] = -ws * math.cos(wd)
    G["rain"][k] = max(w.get("precipitation") or 0.0, 0.0)

def set_daily(G, k, w):
    dl = w.get("_daily") or {}
    t = G["t"][k]
    for day in range(DAYS):
        def g(key, default):
            vals = dl.get(key) or []
            v = vals[day] if day < len(vals) else None
            return default if v is None else v
        G["tmax"][day][k] = g("temperature_2m_max", t)
        G["tmin"][day][k] = g("temperature_2m_min", t)
        G["drain"][day][k] = max(g("precipitation_sum", 0.0), 0.0)
        G["code"][day][k] = int(g("weather_code", 0))
        G["wmax"][day][k] = g("wind_speed_10m_max", 0.0) / 3.6

def set_marine(G, k, m, mask_is_land):
    land = mask_is_land or m.get("wave_height") is None
    cs = 0.0 if land or m.get("ocean_current_velocity") is None else m["ocean_current_velocity"] / 3.6
    cd = math.radians(m.get("ocean_current_direction") or 0.0)  # 流れていく方位
    G["wave"][k] = 0.0 if land else m["wave_height"]
    G["cu"][k] = cs * math.sin(cd); G["cv"][k] = cs * math.cos(cd)
    G["land"][k] = 1 if land else 0

def blank_grid(n):
    G = new_grid()
    for key in ("p", "t", "c", "wu", "wv", "wave", "cu", "cv", "land", "rain"):
        G[key] = [0.0] * n
    for key in ("tmax", "tmin", "drain", "code", "wmax"):
        G[key] = [[0.0] * n for _ in range(DAYS)]
    return G

# ---- 格子の補間 ----
def sample(src, snx, sny, s_lon0, s_lon1, s_lat0, s_lat1, lon, lat):
    """格子 src を (lon, lat) で双線形補間した値の dict (陸の判定と天気コードは一番近い格子、波・海流は海の格子だけで補間)"""
    x = min(max((lon - s_lon0) / (s_lon1 - s_lon0) * (snx - 1), 0.0), snx - 1.0)
    y = min(max((lat - s_lat0) / (s_lat1 - s_lat0) * (sny - 1), 0.0), sny - 1.0)
    i0, j0 = min(int(x), snx - 2), min(int(y), sny - 2)
    fx, fy = x - i0, y - j0
    taps = [(j0 * snx + i0, (1 - fx) * (1 - fy)), (j0 * snx + i0 + 1, fx * (1 - fy)),
            (j0 * snx + snx + i0, (1 - fx) * fy), (j0 * snx + snx + i0 + 1, fx * fy)]
    near = (j0 + (1 if fy > 0.5 else 0)) * snx + i0 + (1 if fx > 0.5 else 0)

    def bi(arr):
        return sum(arr[k] * wt for k, wt in taps)

    def bi_sea(arr):
        """波・海流は海の格子だけで補間 (陸の 0 で弱まらないように)"""
        s = sum(wt for k, wt in taps if not src["land"][k])
        return sum(arr[k] * wt for k, wt in taps if not src["land"][k]) / s if s > 0 else 0.0

    land = src["land"][near]
    v = {key: bi(src[key]) for key in ("p", "t", "c", "wu", "wv", "rain")}
    for key in ("wave", "cu", "cv"):
        v[key] = 0.0 if land else bi_sea(src[key])
    v["land"] = land
    for key in ("tmax", "tmin", "drain", "wmax"):
        v[key] = [bi(src[key][day]) for day in range(DAYS)]
    v["code"] = [src["code"][day][near] for day in range(DAYS)]
    return v

def put(G, k, v):
    """sample の結果を格子の k 番目に入れる"""
    for key in ("p", "t", "c", "wu", "wv", "rain", "wave", "cu", "cv", "land"):
        G[key][k] = v[key]
    for key in ("tmax", "tmin", "drain", "wmax", "code"):
        for day in range(DAYS):
            G[key][day][k] = v[key][day]

def resample_legacy(src):
    """以前の格子 (21×21, 1.5°) へ補間"""
    dst = blank_grid(ON * ON)
    for j in range(ON):
        lat = OLAT0 + (OLAT1 - OLAT0) * j / (ON - 1)
        for i in range(ON):
            lon = OLON0 + (OLON1 - OLON0) * i / (ON - 1)
            put(dst, j * ON + i, sample(src, NX, NY, LON0, LON1, LAT0, LAT1, lon, lat))
    return dst

def fill_sea_on_land(G, nx, ny):
    """陸の点の波高・海流を、まわりの海の点の平均で埋める (粗い格子を補間したとき海岸の近くで弱まらないように)"""
    have = [not G["land"][k] for k in range(nx * ny)]
    for _ in range(4):
        new = list(have)
        for k in range(nx * ny):
            if have[k]:
                continue
            j, i = divmod(k, nx)
            nb = [jj * nx + ii for jj in range(max(0, j - 1), min(ny, j + 2))
                  for ii in range(max(0, i - 1), min(nx, i + 2)) if have[jj * nx + ii]]
            if nb:
                for key in ("wave", "cu", "cv"):
                    G[key][k] = sum(G[key][q] for q in nb) / len(nb)
                new[k] = True
        have = new
    for k in range(nx * ny):
        if not have[k]:
            G["wave"][k] = G["cu"][k] = G["cv"][k] = 0.0

# ---- 画像の読み書き ----
RANGE2 = {"p": (950, 1050), "t": (-20, 40)}
RANGE3 = {"p": (920, 1070), "t": (-60, 45)}

def enc(v, lo, hi):
    return max(0, min(255, int(round((v - lo) / (hi - lo) * 255))))

def dec(c, lo, hi):
    return lo + c / 255.0 * (hi - lo)

def write_image(grid, nx, ny, path, rng=RANGE2):
    (p0, p1), (t0, t1) = rng["p"], rng["t"]
    img = Image.new("RGB", (nx * 11, ny * 2))
    px = img.load()
    for idx in range(nx * ny):
        j, i = divmod(idx, nx)
        row = 2 * ny - 1 - j                       # 下半分 (画像の上 = 北)
        top = ny - 1 - j                           # 上半分
        land = grid["land"][idx]
        px[i, row] = (enc(grid["p"][idx], p0, p1), enc(grid["t"][idx], t0, t1), enc(grid["c"][idx], 0, 100))
        px[nx + i, row] = (enc(grid["wu"][idx], -40, 40), enc(grid["wv"][idx], -40, 40), enc(grid["wave"][idx], 0, 15))
        px[2 * nx + i, row] = (enc(grid["cu"][idx], -2, 2), enc(grid["cv"][idx], -2, 2), 255 if land else 0)
        px[3 * nx + i, row] = (enc(math.sqrt(grid["rain"][idx]), 0, math.sqrt(30)), 0, 0)
        for day in range(DAYS):
            x = (4 + day) * nx + i
            px[x, row] = (enc(grid["tmax"][day][idx], t0, t1), enc(grid["tmin"][day][idx], t0, t1),
                          enc(math.sqrt(grid["drain"][day][idx]), 0, math.sqrt(200)))
            px[x, top] = (max(0, min(255, grid["code"][day][idx])), enc(grid["wmax"][day][idx], 0, 40), 0)
    img.save(path)

def read_image(path, nx, ny, rng=RANGE2):
    """前回の画像を物理量の格子に戻す (使い回し用)。無い・大きさが違うときは None。
    8bit の値は 戻す → 書く で変わらないので、使い回しても劣化しない"""
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return None
    if img.size != (nx * 11, ny * 2):
        return None
    (p0, p1), (t0, t1) = rng["p"], rng["t"]
    px = img.load()
    G = blank_grid(nx * ny)
    for idx in range(nx * ny):
        j, i = divmod(idx, nx)
        row = 2 * ny - 1 - j
        top = ny - 1 - j
        a, b, c, r = px[i, row], px[nx + i, row], px[2 * nx + i, row], px[3 * nx + i, row]
        G["p"][idx] = dec(a[0], p0, p1); G["t"][idx] = dec(a[1], t0, t1); G["c"][idx] = dec(a[2], 0, 100)
        G["wu"][idx] = dec(b[0], -40, 40); G["wv"][idx] = dec(b[1], -40, 40); G["wave"][idx] = dec(b[2], 0, 15)
        G["cu"][idx] = dec(c[0], -2, 2); G["cv"][idx] = dec(c[1], -2, 2); G["land"][idx] = 1 if c[2] > 127 else 0
        G["rain"][idx] = dec(r[0], 0, math.sqrt(30)) ** 2
        for day in range(DAYS):
            x = (4 + day) * nx + i
            lo, hi = px[x, row], px[x, top]
            G["tmax"][day][idx] = dec(lo[0], t0, t1); G["tmin"][day][idx] = dec(lo[1], t0, t1)
            G["drain"][day][idx] = dec(lo[2], 0, math.sqrt(200)) ** 2
            G["code"][day][idx] = hi[0]; G["wmax"][day][idx] = dec(hi[1], 0, 40)
    return G

def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def parse_utc(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)

# ---- 何を取り直すか決める ----
now = datetime.now(timezone.utc)
stamp = now.strftime("%Y-%m-%dT%H:%MZ")
today_jst = (now + timedelta(hours=9)).strftime("%Y-%m-%d")
state = {} if FULL else load_json(os.path.join(OUT, "feed_state.json"))
log = []
for e in state.get("log", []):
    try:
        if now - parse_utc(e[0]) < timedelta(hours=WINDOW_H):
            log.append(e)
    except Exception:
        pass
used24 = sum(e[1] for e in log)

def age_h(key):
    try:
        return (now - parse_utc(state[key])).total_seconds() / 3600.0
    except Exception:
        return 1e9

prev2 = None if FULL else read_image(os.path.join(OUT, "wx2.png"), NX, NY)
have3 = (not FULL) and os.path.exists(os.path.join(OUT, "wx3.png")) and "outer" in state
inner_land = [mask_land(INNER_MASK, NX, NY, k) for k in range(NX * NY)]
inside = [LON0 <= lon <= LON1 and LAT0 <= lat <= LAT1 for (lat, lon) in xpoints]   # 内側の格子の範囲
xfetch = [k for k in range(NX3 * NY3) if not inside[k]]
outer_land = [mask_land(OUTER_MASK, NX3, NY3, k) for k in range(NX3 * NY3)]

cost_fast = NX * NY * weight(len(CURRENT))
cost_slow = NX * NY * (weight(len(CURRENT) + len(DAILY)) - weight(len(CURRENT))) + sum(1 for x in inner_land if not x) * weight(len(MARINE))
cost_outer = len(xfetch) * weight(len(CURRENT) + len(DAILY)) + sum(1 for k in xfetch if not outer_land[k]) * weight(len(MARINE))

need_slow = prev2 is None or "inner_slow" not in state or age_h("inner_slow") >= REUSE_SLOW_H or state.get("inner_days0") != today_jst
need_outer = not have3 or age_h("outer") >= REUSE_OUTER_H or state.get("outer_days0") != today_jst
# 直近の使用量が上限を超えそうなら、使い回せるものは使い回す (前回のデータがあるときだけ)
if need_outer and have3 and used24 + cost_fast + (cost_slow if need_slow else 0) + cost_outer > BUDGET:
    print(f"外側の格子は使用量の上限のため前回のまま (直近22時間 {used24:.0f})")
    need_outer = False
if need_slow and prev2 is not None and used24 + cost_fast + cost_slow > BUDGET:
    print(f"内側の予報・海況は使用量の上限のため前回のまま (直近22時間 {used24:.0f})")
    need_slow = False
print(f"取得: 内側の現在の気象" + (" + 予報・海況" if need_slow else "") + (" / 外側の格子" if need_outer else "") +
      f"  (見込み {cost_fast + (cost_slow if need_slow else 0) + (cost_outer if need_outer else 0):.0f} 回, 直近22時間 {used24:.0f} 回)")

# ---- 内側の格子 (wx2) ----
wx = fetch("https://api.open-meteo.com/v1/forecast", points, CURRENT, daily=DAILY if need_slow else None)
for k in CURRENT:
    fill_missing(wx, k, NX, NY)
G = blank_grid(NX * NY) if need_slow else prev2
for k, w in enumerate(wx):
    set_current(G, k, w)
if need_slow:
    for k, w in enumerate(wx):
        set_daily(G, k, w)
    sea = fetch_marine(points, inner_land)
    for k, m in enumerate(sea):
        set_marine(G, k, m, inner_land[k])
    days = (wx[0].get("_daily") or {}).get("time") or []
    state["inner_slow"] = stamp
    state["inner_days"] = days
    state["inner_days0"] = days[0] if days else ""
days = state.get("inner_days") or []
base_meta = {"updated": stamp, "source": "Open-Meteo (CC BY 4.0)", "days": days,
             "forecast_updated": state.get("inner_slow", stamp)}

write_image(G, NX, NY, os.path.join(OUT, "wx2.png"))
meta2 = dict(base_meta, nx=NX, ny=NY, lon=[LON0, LON1], lat=[LAT0, LAT1],
             pressure_min=round(min(G["p"]), 1), pressure_max=round(max(G["p"]), 1))
with open(os.path.join(OUT, "wx2.json"), "w", encoding="utf-8") as f:
    json.dump(meta2, f, ensure_ascii=False)

L = resample_legacy(G)
write_image(L, ON, ON, os.path.join(OUT, "wx.png"))
meta = dict(base_meta, grid=ON, lon=[OLON0, OLON1], lat=[OLAT0, OLAT1],
            pressure_min=round(min(L["p"]), 1), pressure_max=round(max(L["p"]), 1))
with open(os.path.join(OUT, "wx.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False)

# ---- 外側の格子 (wx3) ----
if need_outer:
    fpts = [xpoints[k] for k in xfetch]
    xw = fetch("https://api.open-meteo.com/v1/forecast", fpts, CURRENT, daily=DAILY)
    xm = fetch_marine(fpts, [outer_land[k] for k in xfetch])
    X = blank_grid(NX3 * NY3)
    rows = [{} for _ in range(NX3 * NY3)]
    for k, w in zip(xfetch, xw):
        rows[k] = w
    # 内側の範囲の点は欠けた扱いにせず、あとで内側の格子から埋める (fill_missing で周りに混ざらないよう仮の値を入れておく)
    for k in range(NX3 * NY3):
        if inside[k]:
            v = sample(G, NX, NY, LON0, LON1, LAT0, LAT1, xpoints[k][1], xpoints[k][0])
            rows[k] = {"pressure_msl": v["p"], "temperature_2m": v["t"], "cloud_cover": v["c"], "precipitation": v["rain"],
                       "wind_speed_10m": math.hypot(v["wu"], v["wv"]) * 3.6,
                       "wind_direction_10m": math.degrees(math.atan2(-v["wu"], -v["wv"])) % 360}
    for key in CURRENT:
        fill_missing(rows, key, NX3, NY3)
    for k in xfetch:
        set_current(X, k, rows[k])
        set_daily(X, k, rows[k])
    for k, m in zip(xfetch, xm):
        set_marine(X, k, m, outer_land[k])
    for k in range(NX3 * NY3):
        if inside[k]:
            put(X, k, sample(G, NX, NY, LON0, LON1, LAT0, LAT1, xpoints[k][1], xpoints[k][0]))
    fill_sea_on_land(X, NX3, NY3)
    xdays = ((xw[0].get("_daily") or {}).get("time") or []) if xw else []
    state["outer"] = stamp
    state["outer_days"] = xdays
    state["outer_days0"] = xdays[0] if xdays else ""
    write_image(X, NX3, NY3, os.path.join(OUT, "wx3.png"), RANGE3)
    meta3 = {"updated": stamp, "source": "Open-Meteo (CC BY 4.0)", "days": xdays, "nx": NX3, "ny": NY3,
             "lon": [XLON0, XLON1], "lat": [XLAT0, XLAT1], "p_range": list(RANGE3["p"]), "t_range": list(RANGE3["t"]),
             "inner_filled": [LON0, LON1, LAT0, LAT1],
             "pressure_min": round(min(X["p"]), 1), "pressure_max": round(max(X["p"]), 1)}
    with open(os.path.join(OUT, "wx3.json"), "w", encoding="utf-8") as f:
        json.dump(meta3, f, ensure_ascii=False)

# ---- 記録 ----
log.append([stamp, round(used, 1)])
state["log"] = log
with open(os.path.join(OUT, "feed_state.json"), "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False)

with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
    f.write("<!doctype html><meta charset=utf-8><title>KAIGEI weather feed</title>"
            "<p>VRChat world data. Weather data by <a href=https://open-meteo.com/>Open-Meteo.com</a> (CC BY 4.0).</p>"
            f"<p>Updated {stamp} (forecast/marine {state.get('inner_slow', '-')}, outer grid {state.get('outer', '-')})</p>"
            f"<h3>wx2.png (122E-154W / 10-46N, 2&deg;, {NX}&times;{NY})</h3>"
            "<img src=wx2.png width=946 style=image-rendering:pixelated>"
            f"<h3>wx3.png (40E-155W / 70S-80N, 5&deg;, {NX3}&times;{NY3})</h3>"
            "<img src=wx3.png width=748 style=image-rendering:pixelated>"
            f"<h3>wx.png (122-152E / 10-40N, 1.5&deg;, {ON}&times;{ON}, legacy)</h3>"
            "<img src=wx.png width=630 style=image-rendering:pixelated>")
print("ok", meta2)
print(f"requests={requests_made} used={used:.0f} ({WINDOW_H}h {used24 + used:.0f}) errors={len(errors)}")
for e in errors:
    print("  ", e)

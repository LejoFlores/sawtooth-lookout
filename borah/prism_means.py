"""PRISM daily 4 km mean temperature and precipitation, area-weighted over any polygons (the truth for new basins).

Source: the PRISM web service, services.nacse.org/prism/data/get/us/4km/<var>/<YYYYMMDD>, one zip per day and variable,
read in memory. Four requests at a time. PRISM day D is the 24 h ending 12 UTC on D. As in static/prism_basin_daily.csv,
the output's date is the calendar day D - 1, the day most of that 24 h falls on.
Weights: the area overlap of each PRISM cell with each polygon (polygon_means.weights), on the cells around the polygons.
PRISM covers only the US, so HUC8s reaching into Canada are averaged over their US part: prism_cover is the share of
the polygon's area with data (1 for most), and polygon-days below MIN_COVER are left out.

Output: OUT/prism_WYyyyy.csv with columns date, basin, tmean_C, ppt_mm, prism_cover, one file per water year (October-September).
A water year whose file exists is skipped. Days PRISM can't serve (for example in the future) are left out.
Usage: python prism_means.py --polygons P.gpkg [--layer L] --id ID [--keep K.csv] --out OUT [--wy 2000-2026]
"""
import argparse
import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
import polygon_means as PM  # noqa: E402

URL = "https://services.nacse.org/prism/data/get/us/4km/{var}/{d:%Y%m%d}"
RES = 1 / 24
LAT0, LON0 = 49.9375 - RES / 2, -125.0208333 + RES / 2      # centre of the upper-left PRISM cell
SESSION = requests.Session()
MIN_COVER = 0.5      # a polygon-day needs PRISM data on at least half its area


def fetch(var, d):
    """-> the day's grid [lat, lon] (no-data < -9000), or None if PRISM has no file for it."""
    from PIL import Image
    for k in range(6):
        try:
            r = SESSION.get(URL.format(var=var, d=d), timeout=180)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            name = [n for n in z.namelist() if n.endswith(".tif")][0]
            return np.array(Image.open(io.BytesIO(z.read(name))), dtype="f4")
        except (requests.RequestException, zipfile.BadZipFile, IndexError):
            if k == 5:
                raise
            time.sleep(5 * 2 ** k)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--polygons", required=True)
    ap.add_argument("--layer")
    ap.add_argument("--id", required=True)
    ap.add_argument("--keep")
    ap.add_argument("--out", required=True)
    ap.add_argument("--wy", default="2000-2026", help="first-last water year")
    a = ap.parse_args()
    g = PM.load_polygons(a.polygons, a.layer, a.id, a.keep)
    ids = list(np.array(g[a.id], dtype=str))
    x0, y0, x1, y1 = g.to_crs(4326).total_bounds
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    W = sub = None
    w0, w1 = (int(x) for x in a.wy.split("-"))
    today = pd.Timestamp.now().normalize()
    for wy in range(w0, w1 + 1):
        f = out / f"prism_WY{wy}.csv"
        if f.exists():
            continue
        t1 = time.time()
        # calendar days of the water year -> PRISM days one later
        days = [d for d in pd.date_range(f"{wy - 1}-10-01", f"{wy}-09-30") if d + pd.Timedelta(days=1) < today]
        rows = []
        with ThreadPoolExecutor(4) as ex:
            T = list(ex.map(lambda d: fetch("tmean", d + pd.Timedelta(days=1)), days))
            P = list(ex.map(lambda d: fetch("ppt", d + pd.Timedelta(days=1)), days))
        for d, t, p in zip(days, T, P):
            if t is None or p is None:
                continue
            if W is None:
                lat, lon = LAT0 - RES * np.arange(t.shape[0]), LON0 + RES * np.arange(t.shape[1])
                jy = np.where((lat > y0 - 2 * RES) & (lat < y1 + 2 * RES))[0]
                jx = np.where((lon > x0 - 2 * RES) & (lon < x1 + 2 * RES))[0]
                sub = np.ix_(jy, jx)
                W = PM.weights(g, lat[jy], lon[jx])
            tv, pv = t[sub].reshape(-1), p[sub].reshape(-1)
            ok = ((tv > -9000) & (pv > -9000)).astype("f4")
            cov = W @ ok                       # share of each polygon's area with PRISM data (it stops at the border)
            with np.errstate(invalid="ignore", divide="ignore"):
                tm, pm = (W @ (np.where(ok > 0, tv, 0) )) / cov, (W @ (np.where(ok > 0, pv, 0))) / cov
            for b, tt, pp, cc in zip(ids, tm, pm, cov):
                if cc >= MIN_COVER:
                    rows.append((d.date(), b, round(float(tt), 3), round(float(pp), 3), round(float(cc), 3)))
        df = pd.DataFrame(rows, columns=["date", "basin", "tmean_C", "ppt_mm", "prism_cover"])
        tmp = f.with_suffix(".tmp")
        df.to_csv(tmp, index=False)
        tmp.rename(f)
        print(f"WY{wy}: {df.date.nunique()} of {len(days)} days, {df.basin.nunique()} basins, {time.time() - t1:.0f}s", flush=True)
        if df.empty and days:
            sys.exit(f"WY{wy}: no rows written")


if __name__ == "__main__":
    main()

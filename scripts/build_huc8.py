"""Build the static files for the screened Idaho water-supply HUC8 basins shown on the Idaho map.

Inputs:
  idaho_huc8_screen.gpkg (layer huc8: huc8, name, tier)   89 HUC8s touching Idaho, screened against NRCS water supply
      forecast points and SNOTEL sites. Tiers "1: ..." (forecast point inside, snow sites) and "2: ..." (snow sites,
      feeds a forecast point downstream) are kept.
  <means>/gefs/YYYYMMDD.npz, <means>/ecmwf/YYYYMMDD.npz   reforecast HUC8 means for all 89 (branch reforecast-means,
      folder idaho_huc8/): GEFS t2m/precip [member, day 1-35, basin], ECMWF [member, lead 0-45, basin]
Outputs (static/):
  huc8_units.csv                          huc8, name, tier of the units kept
  weights_huc8_gefs.npz, weights_huc8_ecmwf.npz   area shares on the live GEFS 0.25 deg grid and the 1.5 deg nodes
  clim_huc8_gefs.npz, clim_huc8_ecmwf.npz reforecast week-2 statistics per start, member, unit. ECMWF keeps the same
                                          starts as clim_ecmwf.npz, to match the calibration and keep the file small.
  huc8_calibration.csv, huc8_scores.csv   logistic calibration per product/event/season pooled over the HUC8s, and
                                          pooled and per-HUC8 hindcast scores, against <means>/prism_basin_daily.csv
                                          (PRISM HUC8 means). HUC8s mostly in Canada have no PRISM truth: they are
                                          left out of the hindcast and use the pooled calibration.
Run: HINDCAST_DATA=... python3 scripts/build_huc8.py idaho_huc8_screen.gpkg <means folder>  (from the repository root;
HINDCAST_DATA is only needed because build_west.py, whose hindcast this reuses, reads it at import)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ews import common as C  # noqa: E402

W2 = C.A["week2"]


def weights(G, lat, lon):
    """As ews.common.weights, for the polygons in G."""
    from shapely.geometry import box
    import geopandas as gpd
    x0, y0, x1, y1 = G.total_bounds
    dy, dx = abs(lat[1] - lat[0]), abs(lon[1] - lon[0])
    jy, jx = np.where((lat > y0 - dy) & (lat < y1 + dy))[0], np.where((lon > x0 - dx) & (lon < x1 + dx))[0]
    cg = gpd.GeoSeries([box(lon[i] - dx / 2, lat[j] - dy / 2, lon[i] + dx / 2, lat[j] + dy / 2) for j in jy for i in jx],
                       crs=4326).to_crs(5070)
    w = np.zeros((len(G), len(jy), len(jx)))
    for k, geom in enumerate(G.to_crs(5070).geometry):
        w[k] = cg.intersection(geom).area.values.reshape(len(jy), len(jx))
    return lat[jy], lon[jx], (w / w.sum((1, 2), keepdims=True)).astype("f4")


def main(gpkg, means):
    import geopandas as gpd
    means = Path(means)
    G = gpd.read_file(gpkg, layer="huc8").to_crs(4326)
    order = list(np.load(sorted((means / "gefs").glob("*.npz"))[0])["basins"].astype(str))
    keep = G[G.tier.str[0].isin(["1", "2"])].sort_values("huc8").reset_index(drop=True)
    idx = np.array([order.index(h) for h in keep.huc8])
    keep[["huc8", "name", "tier"]].to_csv(C.STATIC / "huc8_units.csv", index=False)
    la, lo, w = weights(keep, np.arange(50, 40, -0.25), np.arange(-120, -105, 0.25))
    np.savez_compressed(C.STATIC / "weights_huc8_gefs.npz", lat=la, lon=lo, w=w)
    la, lo, w = weights(keep, np.arange(55.5, 29.9, -1.5), np.arange(-130.5, -100.4, 1.5))
    np.savez_compressed(C.STATIC / "weights_huc8_ecmwf.npz", lat=la, lon=lo, w=w)
    names = np.array(list(keep.huc8), dtype="U8")
    a, b = W2
    st, T, P = [], [], []
    for f in sorted((means / "gefs").glob("*.npz")):
        d = np.load(f)
        s = (d["days"] >= a) & (d["days"] <= b)
        t, p = np.full((11, len(idx)), np.nan, "f4"), np.full((11, len(idx)), np.nan, "f4")
        n = d["t2m"].shape[0]
        t[:n], p[:n] = d["t2m"][:, s][:, :, idx].mean(1), d["precip"][:, s][:, :, idx].sum(1)
        st.append(f.stem); T.append(t); P.append(p)
    np.savez_compressed(C.STATIC / "clim_huc8_gefs.npz", starts=pd.DatetimeIndex(st).values.astype("datetime64[D]"),
                        basins=names, T_week2=np.stack(T), P_week2=np.stack(P))
    print("gefs", len(st), np.stack(T).shape)
    L = np.arange(a - 1, b)
    st, T, P = [], [], []
    for s0 in pd.DatetimeIndex(C.load_climate("ecmwf")["starts"]):
        f = means / "ecmwf" / f"{s0:%Y%m%d}.npz"
        if not f.exists():
            continue
        d = np.load(f)
        st.append(s0); T.append(d["t2m"][:, L][:, :, idx].mean(1).astype("f4")); P.append(d["precip"][:, L][:, :, idx].sum(1).astype("f4"))
    np.savez_compressed(C.STATIC / "clim_huc8_ecmwf.npz", starts=pd.DatetimeIndex(st).values.astype("datetime64[D]"),
                        basins=names, T_week2=np.stack(T), P_week2=np.stack(P))
    print("ecmwf", len(st), np.stack(T).shape)
    # hindcast against PRISM, as build_west does against CPC
    from scripts import build_west as BW
    raw = {}
    for s0 in st:
        d = np.load(means / "ecmwf" / f"{s0:%Y%m%d}.npz")
        raw[s0] = (d["t2m"][:, :, idx], d["precip"][:, :, idx])
    pr = pd.read_csv(means / "prism_basin_daily.csv", parse_dates=["date"], dtype={"basin": str})
    To = pr.pivot(index="date", columns="basin", values="tmean_C").asfreq("D").reindex(columns=names)
    Po = pr.pivot(index="date", columns="basin", values="ppt_mm").asfreq("D").reindex(columns=names)
    missing = [h for h in names if To[h].isna().all()]
    have = [h for h in names if h not in missing]
    for h in missing:                                         # placeholder so the window statistics are finite
        To[h], Po[h] = To[have[0]], Po[have[0]]
    R = BW.hindcast(raw, To, Po, names, prefix="huc8")
    R = R[~R.huc4.isin(missing)].reset_index(drop=True)
    S = BW.calibrate(R, prefix="huc8")
    print("no PRISM truth:", missing)
    pd.set_option("display.width", 250)
    print(S[(S.huc4 == "all") & S.event.isin(C.A["events"])].to_string(index=False))


if __name__ == "__main__":
    main(*sys.argv[1:3])

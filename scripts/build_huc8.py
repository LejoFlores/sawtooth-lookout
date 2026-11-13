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
There is no per-HUC8 truth yet, so odds use the five-basin calibration (static/calibration.csv).
Run: python3 scripts/build_huc8.py idaho_huc8_screen.gpkg <means folder>   (from the repository root)
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


if __name__ == "__main__":
    main(*sys.argv[1:3])

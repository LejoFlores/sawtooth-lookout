"""Build the static files for the West-wide HUC4 view, from the 1.5 deg western box archive (a local folder,
$HINDCAST_DATA/west; not in this repository) and a HUC4 polygon file.

Inputs:
  west/gefs, west/gefs_t2m/YYYYMMDD.npz    GEFSv12 reforecast box means [member, day 8-35, 18, 21] (exact overlap of
                                            the native cells with each 1.5 deg box), Wednesday starts 2000-2019
  west/ecmwf, west/ecmwf_t2m/YYYYMMDD.npz  ECMWF reforecast on its 1.5 deg grid [member, lead 0-45, 18, 21]
  west/obs/cpc_precip_west.npz, cpc_tmean_west.npz   CPC gauge precipitation and station temperature box means (truth)
  HUC4 polygons (USGS Watershed Boundary Dataset WBDHU4, regions 10, 11, 13-18), columns huc4, name
Outputs (static/):
  west_units.csv                           the HUC4 units kept (at least 60% of their area in gauged US boxes)
  weights_west_gefs.npz                    unit shares on the live GEFS 0.25 deg grid (box means of 0.25 deg cells,
                                           then box -> unit, composed)
  weights_west_ecmwf.npz                   unit shares on the 1.5 deg nodes the live ECMWF field is sampled at
  clim_west_gefs.npz, clim_west_ecmwf.npz  reforecast week-2 statistics per start, member, unit
  west_calibration.csv, west_scores.csv    logistic calibration per product/event/season (units pooled) and
                                           per-unit and pooled hindcast scores
  map/west_huc4.geojson                    simplified unit outlines for the web map
The hindcast pairs each Wednesday GEFS start with the latest ECMWF reforecast start at least two days old.
Run: HINDCAST_DATA=... python3 scripts/build_west.py huc4_all.gpkg   (from the repository root)
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ews import common as C  # noqa: E402
from scripts.build_static import auc, fit, wy  # noqa: E402

D = Path(os.environ["HINDCAST_DATA"]) / "west"
BLAT, BLON = np.arange(55.5, 29.9, -1.5), np.arange(-130.5, -100.4, 1.5)      # box centres of the archive
NB = len(BLAT) * len(BLON)
W2 = C.A["week2"]


def units(gpkg):
    import geopandas as gpd
    from shapely.geometry import box
    zp, zt = np.load(D / "obs/cpc_precip_west.npz"), np.load(D / "obs/cpc_tmean_west.npz")
    ok = ((np.isfinite(zp["precip"][-4000:]).mean(0) > 0.9) & (np.isfinite(zt["tmean"][-4000:]).mean(0) > 0.9)).ravel()
    G = gpd.read_file(gpkg)
    G5 = G.to_crs(5070)
    G5["geometry"] = G5.buffer(0)
    cells = gpd.GeoSeries([box(lo - .75, la - .75, lo + .75, la + .75) for la in BLAT for lo in BLON], crs=4326).to_crs(5070)
    w = np.zeros((len(G), NB))
    for i, g in enumerate(G5.geometry):
        for b in cells.sindex.query(g, predicate="intersects"):
            w[i, b] = g.intersection(cells.iloc[b]).area
    w[:, ~ok] = 0
    keep = w.sum(1) / G5.area.values >= 0.6
    G, w = G[keep].sort_values("huc4"), w[keep][np.argsort(G[keep].huc4.values)]
    G = G.reset_index(drop=True)
    w = (w / w.sum(1, keepdims=True)).astype("f4")
    G[["huc4", "name"]].to_csv(C.STATIC / "west_units.csv", index=False)
    out = G[["huc4", "name", "geometry"]].to_crs(4326)
    out["geometry"] = out.geometry.simplify(0.02, preserve_topology=True)
    (C.STATIC / "map").mkdir(exist_ok=True)
    out.to_file(C.STATIC / "map/west_huc4.geojson", driver="GeoJSON", COORDINATE_PRECISION=3)
    return G, w


def build_weights(w):
    wb = w.reshape(len(w), len(BLAT), len(BLON))
    np.savez_compressed(C.STATIC / "weights_west_ecmwf.npz", lat=BLAT, lon=BLON, w=wb)
    gl, gn = np.arange(56.25, 29.2, -0.25), np.arange(-131.25, -99.7, 0.25)

    def overlap(c, centres):                                  # share of each box covered by each 0.25 deg cell
        o = np.clip(np.minimum(c[None] + .125, centres[:, None] + .75) - np.maximum(c[None] - .125, centres[:, None] - .75), 0, None)
        return o / o.sum(1, keepdims=True)
    wg = np.einsum("hyx,yj,xi->hji", wb, overlap(gl, BLAT), overlap(gn, BLON)).astype("f4")
    assert np.allclose(wg.sum((1, 2)), 1, atol=1e-4)
    np.savez_compressed(C.STATIC / "weights_west_gefs.npz", lat=gl, lon=gn, w=wg)


def build_climate(w, names):
    a, b = W2
    g = dict(starts=[], T_week2=[], P_week2=[])
    ft = {Path(f).stem for f in glob.glob(str(D / "gefs_t2m/*.npz"))}
    for f in sorted(glob.glob(str(D / "gefs/*.npz"))):
        if Path(f).stem not in ft:
            continue
        p, t = np.load(f), np.load(D / "gefs_t2m" / Path(f).name)
        s = (p["days"] >= a) & (p["days"] <= b)
        T = np.full((11, len(w)), np.nan, "f4"); P = T.copy()
        tt, pp = t["t2m"][:, s].mean(1).reshape(-1, NB), p["precip"][:, s].sum(1).reshape(-1, NB)
        T[:len(tt)], P[:len(pp)] = np.nan_to_num(tt) @ w.T, np.nan_to_num(pp) @ w.T
        T[:len(tt)][~np.isfinite(tt).all(1)] = np.nan
        g["starts"].append(Path(f).stem); g["T_week2"].append(T); g["P_week2"].append(P)
    e = dict(starts=[], T_week2=[], P_week2=[])
    L = np.arange(a - 1, b)                                   # lead L is calendar day start + L, i.e. day L + 1
    raw = {}
    for f in sorted(glob.glob(str(D / "ecmwf_t2m/*.npz"))):
        t, p = np.load(f)["t2m"].reshape(10, -1, NB), np.load(D / "ecmwf" / Path(f).name)["precip"].reshape(10, -1, NB)
        raw[pd.Timestamp(Path(f).stem)] = (np.nan_to_num(t) @ w.T, np.nan_to_num(p) @ w.T)   # [member, lead, unit]
        e["starts"].append(Path(f).stem)
        e["T_week2"].append(raw[pd.Timestamp(Path(f).stem)][0][:, L].mean(1))
        e["P_week2"].append(raw[pd.Timestamp(Path(f).stem)][1][:, L].sum(1))
    for name, r in (("gefs", g), ("ecmwf", e)):
        np.savez_compressed(C.STATIC / f"clim_west_{name}.npz", starts=pd.DatetimeIndex(r["starts"]).values.astype("datetime64[D]"),
                            basins=names, T_week2=np.stack(r["T_week2"]).astype("f4"), P_week2=np.stack(r["P_week2"]).astype("f4"))
    return raw


def truth(w):
    zp, zt = np.load(D / "obs/cpc_precip_west.npz"), np.load(D / "obs/cpc_tmean_west.npz")
    P = pd.DataFrame(np.nan_to_num(zp["precip"].reshape(len(zp["dates"]), -1)) @ w.T, index=pd.DatetimeIndex(zp["dates"])).asfreq("D")
    T = pd.DataFrame(np.nan_to_num(zt["tmean"].reshape(len(zt["dates"]), -1)) @ w.T, index=pd.DatetimeIndex(zt["dates"])).asfreq("D")
    return T, P.shift(-1)                                     # CPC labels the 12Z-12Z day by its end date


def hindcast(raw, To, Po, names, prefix="west"):
    cg, ce = C.load_climate(f"{prefix}_gefs"), C.load_climate(f"{prefix}_ecmwf")
    est = pd.DatetimeIndex(sorted(raw))
    rows = []
    for i, t0 in enumerate(pd.DatetimeIndex(cg["starts"])):
        if t0.month not in (11, 12, 1, 2, 3, 4, 5, 6):
            continue
        y = wy([t0])[0]
        T, P = cg["T_week2"][i], cg["P_week2"][i]
        ok = np.isfinite(T).all(1) & np.isfinite(P).all(1)
        if ok.sum() < 5:
            continue
        sg = C.shares(C.member_percentiles(T[ok], P[ok], *C.reference(cg, t0, "week2", exclude_wy=y)))
        prods = {"week2_gefs": sg}
        old = est[est <= t0 - pd.Timedelta(days=2)]
        if len(old) and (t0 - old[-1]).days <= 5:
            L = (t0 - old[-1]).days + np.arange(W2[0] - 1, W2[1])
            te, pe = raw[old[-1]]
            se = C.shares(C.member_percentiles(te[:, L].mean(1), pe[:, L].sum(1), *C.reference(ce, t0, "week2", exclude_wy=y)))
            prods["week2"] = {ev: (sg[ev] + se[ev]) / 2 for ev in C.EVENTS}
        op = C.observed_percentiles(To, Po, t0, *W2)
        if op is None:
            continue
        for prod, sh in prods.items():
            r = pd.DataFrame(dict(product=prod, issue=t0.date(), wy=y, season=C.season(t0), huc4=names))
            for ev, (s, tail) in C.EVENTS.items():
                r[f"share_{ev}"] = sh[ev]
                r[f"obs_{ev}"] = (op[s][0] <= C.A["tail"] if tail == "lo" else op[s][0] >= 1 - C.A["tail"]).astype(float)
            rows.append(r)
    return pd.concat(rows, ignore_index=True)


def calibrate(R, prefix="west"):
    cal, sc = [], []
    for (prod, se), g in R.groupby(["product", "season"]):
        for ev in C.EVENTS:
            share, o, yy = g[f"share_{ev}"].values, g[f"obs_{ev}"].values, g.wy.values
            x = C._logit(share)
            a, b = fit(x, o)
            cal.append(dict(product=prod, event=ev, season=se, a=a, b=b, n=len(o), base_rate=o.mean()))
            q = np.zeros_like(share)
            for y in np.unique(yy):
                ca, cb = fit(x[yy != y], o[yy != y])
                q[yy == y] = 1 / (1 + np.exp(-(ca + cb * x[yy == y])))
            al, clim = q >= C.A["alert_odds"], np.mean((o.mean() - o) ** 2)
            base = dict(product=prod, season=se, event=ev)
            sc.append(dict(base, huc4="all", n=len(o), base_rate=o.mean(), roc=auc(share, o),
                           bss_calibrated=1 - np.mean((q - o) ** 2) / clim,
                           alert_right=o[al].mean() if al.any() else np.nan,
                           events_caught=al[o == 1].mean() if (o == 1).any() else np.nan))
            for h, k in g.groupby("huc4").indices.items():
                sc.append(dict(base, huc4=h, n=len(k), base_rate=o[k].mean(), roc=auc(share[k], o[k]),
                               bss_calibrated=np.nan, alert_right=o[k][al[k]].mean() if al[k].any() else np.nan,
                               events_caught=al[k][o[k] == 1].mean() if (o[k] == 1).any() else np.nan))
    pd.DataFrame(cal).round(4).to_csv(C.STATIC / f"{prefix}_calibration.csv", index=False)
    S = pd.DataFrame(sc).round(3)
    S.to_csv(C.STATIC / f"{prefix}_scores.csv", index=False)
    return S


if __name__ == "__main__":
    G, w = units(sys.argv[1])
    names = np.array(list(G.huc4), dtype="U4")
    print(len(G), "HUC4 units", flush=True)
    build_weights(w)
    raw = build_climate(w, names)
    To, Po = truth(w)
    To.columns = Po.columns = names
    R = hindcast(raw, To, Po, names)
    S = calibrate(R)
    pd.set_option("display.width", 250)
    print(S[(S.huc4 == "all") & S.event.isin(C.A["events"])].to_string(index=False))

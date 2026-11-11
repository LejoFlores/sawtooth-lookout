"""Config, static files and the alarm arithmetic shared by the live run, the replay and build_static."""
import os
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
CFG = tomllib.loads((HERE / "config.toml").read_text())
STATIC = HERE / CFG["output"]["static"]
PRODUCTS = Path(os.environ.get("EWS_PRODUCTS", HERE / CFG["output"]["products"]))
BASINS = list(CFG["basins"])
A = CFG["alarms"]

# event -> (statistic, tail). Statistics: P window total, T window mean, WD = zT - z(sqrt P) (warm-dry index).
EVENTS = {"dry": ("P", "lo"), "wet": ("P", "hi"), "warm": ("T", "hi"), "cold": ("T", "lo"),
          "warm-dry": ("WD", "hi"), "cold-wet": ("WD", "lo")}


def season(t):
    m = pd.Timestamp(t).month
    return next((k for k, v in A["seasons"].items() if m in v), None)


def weights(lat, lon, basins=None):
    """Area share of each basin in each cell of a regular grid -> (jy, jx, w[basin, len(jy), len(jx)]).
    Build-time only (needs geopandas and the basin polygons)."""
    import geopandas as gpd
    from shapely.geometry import box
    gpkg = STATIC / "basins.gpkg"
    b = gpd.read_file(gpkg).set_index("basin").loc[basins or BASINS]
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    lo = ((lon + 180) % 360) - 180
    x0, y0, x1, y1 = b.total_bounds
    dy, dx = abs(lat[1] - lat[0]), abs(lon[1] - lon[0])
    jy = np.where((lat > y0 - dy) & (lat < y1 + dy))[0]
    jx = np.where((lo > x0 - dx) & (lo < x1 + dx))[0]
    cells = [box(lo[i] - dx / 2, lat[j] - dy / 2, lo[i] + dx / 2, lat[j] + dy / 2) for j in jy for i in jx]
    cg = gpd.GeoSeries(cells, crs=4326).to_crs(5070)
    w = np.zeros((len(b), len(jy), len(jx)))
    for k, geom in enumerate(b.to_crs(5070).geometry):
        w[k] = cg.intersection(geom).area.values.reshape(len(jy), len(jx))
    return jy, jx, (w / w.sum((1, 2), keepdims=True)).astype("f4")


def load_weights(name):
    z = np.load(STATIC / f"weights_{name}.npz")
    return z["lat"], z["lon"], z["w"]


def basin_mean(field, lat_f, lon_f, wname):
    """field[..., lat, lon] on any grid containing the static weight cells -> [..., basin]."""
    lat, lon, w = load_weights(wname)
    lo_f = ((np.asarray(lon_f, float) + 180) % 360) - 180
    iy = np.array([int(np.argmin(np.abs(np.asarray(lat_f) - v))) for v in lat])
    ix = np.array([int(np.argmin(np.abs(lo_f - v))) for v in lon])
    assert np.allclose(np.asarray(lat_f)[iy], lat, atol=1e-3) and np.allclose(lo_f[ix], lon, atol=1e-3), "grid mismatch"
    return np.einsum("bij,...ij->...b", w, field[..., iy[:, None], ix[None, :]])


def load_climate(system):
    z = np.load(STATIC / f"clim_{system}.npz")
    return {k: z[k] for k in z}


def reference(clim, t0, window, exclude_wy=None):
    """Reforecast members of starts within +-doy_halfwidth days of year of t0 -> T[n, basin], P[n, basin]."""
    st = pd.DatetimeIndex(clim["starts"])
    d = np.abs(st.dayofyear.values - pd.Timestamp(t0).dayofyear)
    ok = np.minimum(d, 365 - d) <= A["doy_halfwidth"]
    if exclude_wy is not None:
        ok &= (st.year + (st.month >= 10)).values != exclude_wy
    T, P = clim[f"T_{window}"][ok], clim[f"P_{window}"][ok]          # [start, member, basin]
    T, P = T.reshape(-1, T.shape[-1]), P.reshape(-1, P.shape[-1])
    keep = np.isfinite(T).all(1) & np.isfinite(P).all(1)
    return T[keep], P[keep]


def pct(x, ref):
    ref = np.sort(ref[np.isfinite(ref)])
    return (np.searchsorted(ref, x, "left") + np.searchsorted(ref, x, "right")) / 2 / len(ref)


def zs(x, ref):
    return (x - np.nanmean(ref)) / np.nanstd(ref)


def member_percentiles(T, P, rT, rP):
    """Live members T, P [member, basin] ranked within reference rT, rP [n, basin] -> {stat: [member, basin]}."""
    out = {k: np.full(T.shape, np.nan) for k in ("T", "P", "WD")}
    for b in range(T.shape[1]):
        zT, zP = zs(T[:, b], rT[:, b]), zs(np.sqrt(P[:, b]), np.sqrt(rP[:, b]))
        rzT, rzP = zs(rT[:, b], rT[:, b]), zs(np.sqrt(rP[:, b]), np.sqrt(rP[:, b]))
        out["T"][:, b] = pct(T[:, b], rT[:, b])
        out["P"][:, b] = pct(P[:, b], rP[:, b])
        out["WD"][:, b] = pct(zT - zP, rzT - rzP)
    return out


def shares(pc):
    """Member percentiles -> {event: share of members beyond the tail [basin]}."""
    t = A["tail"]
    return {ev: ((pc[s] <= t) if tail == "lo" else (pc[s] >= 1 - t)).mean(0) for ev, (s, tail) in EVENTS.items()}


def _logit(p):
    p = np.clip(p, 0.02, 0.98)
    return np.log(p / (1 - p))


def calibrate(share, event, product, t0, cal=None):
    """Raw member share -> calibrated odds with the logistic fit for this product, event and season (NaN if none)."""
    cal = load_calibration() if cal is None else cal
    r = cal[(cal["product"] == product) & (cal.event == event) & (cal.season == season(t0))]
    if r.empty:
        return np.full(np.shape(share), np.nan)
    a, b = r.iloc[0][["a", "b"]]
    return 1 / (1 + np.exp(-(a + b * _logit(np.asarray(share, float)))))


def load_calibration():
    return pd.read_csv(STATIC / "calibration.csv")


def load_truth():
    """PRISM basin means by calendar day -> (T, P) DataFrames [date, basin]."""
    pr = pd.read_csv(STATIC / "prism_basin_daily.csv", parse_dates=["date"])
    return (pr.pivot(index="date", columns="basin", values="tmean_C")[BASINS].asfreq("D"),
            pr.pivot(index="date", columns="basin", values="ppt_mm")[BASINS].asfreq("D"))


def observed_percentiles(To, Po, t0, a, b):
    """Observed window T, P at issue t0 ranked within the same calendar window of the other water years (ESP)."""
    def stats(w):
        dd = pd.date_range(w + pd.Timedelta(days=a - 1), w + pd.Timedelta(days=b - 1))
        return To.reindex(dd).mean().values, Po.reindex(dd).sum(min_count=len(dd)).values
    T, P = stats(t0)
    if not (np.isfinite(T).all() and np.isfinite(P).all()):
        return None
    y0, ref = t0.year + (t0.month >= 10), []
    for yy in range(2000, 2027):
        if yy == y0:
            continue
        try:
            ws = t0.replace(year=t0.year + (yy - y0))
        except ValueError:
            ws = (t0 - pd.Timedelta(days=1)).replace(year=t0.year + (yy - y0))
        t_, p_ = stats(ws)
        if np.isfinite(t_).all() and np.isfinite(p_).all():
            ref.append((t_, p_))
    rT, rP = np.array([r[0] for r in ref]), np.array([r[1] for r in ref])
    return member_percentiles(T[None], P[None], rT, rP)

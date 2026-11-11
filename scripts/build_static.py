"""Build the static files the live job needs, from the five-basin reforecast hindcast (a local folder, $HINDCAST_DATA).

Inputs (folder in $HINDCAST_DATA; the reforecast basin extracts are not in this repository):
  ext5/gefs/YYYYMMDD.npz    GEFSv12 reforecast, Wednesday starts 2000-2019, 11 members, days 8-35 (UTC days),
                            basin means at native 0.25/0.5 deg (ext5/scripts/gefs_basins.py)
  ext5/ecmwf/YYYYMMDD.npz   ECMWF reforecast (CY49R1, 10 members, every other day 2006-2025), daily by lead,
                            basin means on the 1.5 deg grid (ext5/scripts/ecmwf_basins.py)
  obs/ and ext5/prism_basin_daily.csv   PRISM basin means (PRISM day D -> calendar day D-1)
Outputs (static/):
  weights_gefs.npz, weights_ecmwf.npz   basin area shares on the live GEFS 0.25 deg grid and on the 1.5 deg nodes
                                        the live ECMWF 0.25 deg field is sampled at (as the reforecast was)
  clim_gefs.npz, clim_ecmwf.npz         reforecast window statistics per start, member, basin (the members' climate)
  prism_basin_daily.csv                 PRISM truth for the five basins (calendar days), to verify past alarms
  hindcast_issues.csv                   per Wednesday issue and basin: raw member shares, calibrated odds
                                        (leave-one-water-year-out) and the observed outcome, for every product
  calibration.csv                       logistic fit odds = 1/(1+exp(-(a + b logit(share)))) per product, event, season
  hindcast_scores.csv                   ROC, Brier skill and alert statistics at alert_odds, per product/event/season
The hindcast pairs each Wednesday GEFS start with the ECMWF reforecast start the step 2 hindcast used (the latest one at
least two days old; reforecast starts are every few days), taking ECMWF's days 8-14 counted from the Wednesday. Live,
both systems start at 00 UTC on the same day, so the live ECMWF half is a little fresher than in the hindcast.
Run: python3 scripts/build_static.py   (from the repository root; needs geopandas and scipy)
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import rankdata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ews import common as C  # noqa: E402

D = Path(os.environ["HINDCAST_DATA"])
W2, FN = C.A["week2"], C.A["fortnight"]


def wy(t):
    t = pd.DatetimeIndex(t)
    return (t.year + (t.month >= 10)).values


def build_weights():
    gl, gn = np.arange(50, 40, -0.25), np.arange(-120, -105, 0.25)
    jy, jx, w = C.weights(gl, gn)
    np.savez_compressed(C.STATIC / "weights_gefs.npz", lat=gl[jy], lon=gn[jx], w=w)
    el, en = np.arange(55.5, 29.9, -1.5), np.arange(-130.5, -100.4, 1.5)   # the reforecast's 1.5 deg western grid
    jy, jx, w = C.weights(el, en)
    np.savez_compressed(C.STATIC / "weights_ecmwf.npz", lat=el[jy], lon=en[jx], w=w)


def build_climate():
    rows = {"gefs": [], "ecmwf": []}
    for f in sorted(glob.glob(str(D / "ext5/gefs/[0-9]*.npz"))):
        d = np.load(f)
        assert list(d["basins"]) == C.BASINS
        day = d["days"]
        o = dict(start=pd.Timestamp(Path(f).stem))
        for wn, (a, b) in (("week2", W2), ("fortnight", FN)):
            s = (day >= a) & (day <= b)
            o[f"T_{wn}"], o[f"P_{wn}"] = d["t2m"][:, s].mean(1), d["precip"][:, s].sum(1)
        rows["gefs"].append(o)
    for f in sorted(glob.glob(str(D / "ext5/ecmwf/[0-9]*.npz"))):
        d = np.load(f)
        assert list(d["basins"]) == C.BASINS
        L = np.arange(W2[0] - 1, W2[1])                       # lead L is calendar day start + L, i.e. day L + 1
        rows["ecmwf"].append(dict(start=pd.Timestamp(Path(f).stem), T_week2=d["t2m"][:, L].mean(1),
                                  P_week2=d["precip"][:, L].sum(1)))
    for s, r in rows.items():
        M = max(x["T_week2"].shape[0] for x in r)
        pad = lambda a: np.concatenate([a, np.full((M - a.shape[0],) + a.shape[1:], np.nan, "f4")]).astype("f4")
        out = dict(starts=np.array([x["start"] for x in r], "datetime64[D]"), basins=np.array(C.BASINS))
        for k in r[0]:
            if k != "start":
                out[k] = np.stack([pad(x[k]) for x in r])
        np.savez_compressed(C.STATIC / f"clim_{s}.npz", **out)
        print(s, {k: v.shape for k, v in out.items()})


def build_truth():
    pr = pd.concat([pd.read_csv(D / "obs/prism_basin_daily.csv", parse_dates=["date"]),
                    pd.read_csv(D / "ext5/prism_basin_daily.csv", parse_dates=["date"])])
    pr = pr[pr.basin.isin(C.BASINS)].copy()
    pr["date"] -= pd.Timedelta(days=1)
    pr[["date", "basin", "tmean_C", "ppt_mm"]].round({"tmean_C": 3, "ppt_mm": 3}).to_csv(C.STATIC / "prism_basin_daily.csv", index=False)
    return (pr.pivot(index="date", columns="basin", values="tmean_C")[C.BASINS].asfreq("D"),
            pr.pivot(index="date", columns="basin", values="ppt_mm")[C.BASINS].asfreq("D"))


def hindcast(To, Po):
    cg, ce = C.load_climate("gefs"), C.load_climate("ecmwf")
    gs = pd.DatetimeIndex(cg["starts"])
    lagged = {}                                             # Wednesday issue -> ECMWF T, P [member, basin], days 8-14
    for f in sorted(glob.glob(str(D / "ext5/ecmwf/[0-9]*.npz"))):
        d, t_e = np.load(f), pd.Timestamp(Path(f).stem)
        for w in pd.DatetimeIndex(d["issues"]):
            L = (w - t_e).days + np.arange(W2[0] - 1, W2[1])
            if L.max() < d["t2m"].shape[1]:
                lagged[w] = (d["t2m"][:, L].mean(1), d["precip"][:, L].sum(1))
    rows = []
    for i, t0 in enumerate(gs):
        if t0.month not in (11, 12, 1, 2, 3, 4, 5, 6):
            continue
        y = wy([t0])[0]
        members = {}
        for wn in ("week2", "fortnight"):
            rT, rP = C.reference(cg, t0, wn, exclude_wy=y)
            T, P = cg[f"T_{wn}"][i], cg[f"P_{wn}"][i]
            ok = np.isfinite(T).all(1) & np.isfinite(P).all(1)
            if ok.sum() >= 5:
                members[("gefs", wn)] = C.shares(C.member_percentiles(T[ok], P[ok], rT, rP))
        if t0 in lagged:
            rT, rP = C.reference(ce, t0, "week2", exclude_wy=y)
            T, P = lagged[t0]
            ok = np.isfinite(T).all(1) & np.isfinite(P).all(1)
            if ok.sum() >= 5:
                members[("ecmwf", "week2")] = C.shares(C.member_percentiles(T[ok], P[ok], rT, rP))
        products = {}
        if ("gefs", "week2") in members and ("ecmwf", "week2") in members:
            products["week2"] = {ev: (members[("gefs", "week2")][ev] + members[("ecmwf", "week2")][ev]) / 2
                                 for ev in C.EVENTS}
        if ("gefs", "week2") in members:
            products["week2_gefs"] = members[("gefs", "week2")]
        if ("gefs", "fortnight") in members:
            products["fortnight_gefs"] = members[("gefs", "fortnight")]
        for prod, sh in products.items():
            a, b = FN if prod.startswith("fortnight") else W2
            op = C.observed_percentiles(To, Po, t0, a, b)
            if op is None:
                continue
            for bi, bn in enumerate(C.BASINS):
                r = dict(product=prod, issue=t0.date(), wy=y, season=C.season(t0), basin=bn)
                for ev, (s, tail) in C.EVENTS.items():
                    r[f"share_{ev}"] = sh[ev][bi]
                    x = op[s][0, bi]
                    r[f"obs_{ev}"] = float(x <= C.A["tail"] if tail == "lo" else x >= 1 - C.A["tail"])
                rows.append(r)
    return pd.DataFrame(rows)


def fit(x, o):
    nll = lambda c: -np.sum(o * (c[0] + c[1] * x) - np.logaddexp(0, c[0] + c[1] * x))
    return minimize(nll, [-2.0, 1.0]).x


def auc(p, o):
    o = o.astype(bool)
    if o.all() or (~o).all():
        return np.nan
    r = rankdata(p)
    return (r[o].sum() - o.sum() * (o.sum() + 1) / 2) / (o.sum() * (~o).sum())


def calibrate(R):
    cal, sc = [], []
    for (prod, se), g in R.groupby(["product", "season"]):
        for ev in C.EVENTS:
            share, o, yy = g[f"share_{ev}"].values, g[f"obs_{ev}"].values, g.wy.values
            x = C._logit(share)
            a, b = fit(x, o)
            cal.append(dict(product=prod, event=ev, season=se, a=a, b=b, n=len(o), base_rate=o.mean()))
            q = np.zeros_like(share)
            for y in np.unique(yy):                               # leave one water year out
                ca, cb = fit(x[yy != y], o[yy != y])
                q[yy == y] = 1 / (1 + np.exp(-(ca + cb * x[yy == y])))
            R.loc[g.index, f"odds_{ev}"] = q
            nw, al = len(np.unique(yy)), q >= C.A["alert_odds"]
            clim = np.mean((o.mean() - o) ** 2)
            sc.append(dict(product=prod, season=se, event=ev, n=len(o), winters=nw, base_rate=o.mean(),
                           roc=auc(share, o), bss_raw=1 - np.mean((share - o) ** 2) / clim,
                           bss_calibrated=1 - np.mean((q - o) ** 2) / clim,
                           alerts_per_season_per_basin=al.sum() / nw / len(C.BASINS),
                           alert_right=o[al].mean() if al.any() else np.nan,
                           events_caught=al[o == 1].mean() if (o == 1).any() else np.nan))
    pd.DataFrame(cal).round(4).to_csv(C.STATIC / "calibration.csv", index=False)
    S = pd.DataFrame(sc).round(3)
    S.to_csv(C.STATIC / "hindcast_scores.csv", index=False)
    R.round(4).to_csv(C.STATIC / "hindcast_issues.csv", index=False)
    return S


if __name__ == "__main__":
    C.STATIC.mkdir(exist_ok=True)
    build_weights()
    build_climate()
    To, Po = build_truth()
    R = hindcast(To, Po)
    S = calibrate(R)
    pd.set_option("display.width", 250)
    print(S[S.event.isin(C.A["events"])].to_string(index=False))

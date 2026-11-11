"""Replay the live job on past operational forecasts and score it against PRISM: a check, independent of the
reforecast hindcast, that the live code and data give the hindcast's skill.

GEFS: every Wednesday 00 UTC start Nov-Feb from the dynamical.org archive (starts Oct 2020), so WY2021-2026.
ECMWF: ECMWF open data at 0.25 deg exists from about March 2024, so the combined product is replayed for WY2025-2026.
Each start gives the GEFS-only and (when ECMWF exists) the combined week-2 odds; outcomes come from PRISM as in the
hindcast (observed window beyond the 10th/90th percentile of the same window in the other water years).
Output: $EWS_PRODUCTS/replay/replay_issues.csv and replay_scores.csv
Run (from the repository root): python3 scripts/replay.py [--first 2020-11-01] [--last 2026-02-28] [--no-ecmwf]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ews import common as C  # noqa: E402
from ews import run_daily as R  # noqa: E402
from ews import sources as S  # noqa: E402


def auc(p, o):
    o = o.astype(bool)
    if o.all() or (~o).all():
        return np.nan
    from scipy.stats import rankdata  # noqa: PLC0415
    r = rankdata(p)
    return (r[o].sum() - o.sum() * (o.sum() + 1) / 2) / (o.sum() * (~o).sum())


def score(R_):
    rows = []
    for prod, g in R_.groupby("product"):
        for ev in C.A["events"]:
            o, q, sh = g[f"obs_{ev}"].values, g[f"odds_{ev}"].values, g[f"share_{ev}"].values
            al = q >= C.A["alert_odds"]
            nw = g.wy.nunique()
            rows.append(dict(product=prod, event=ev, n=len(o), winters=nw, base_rate=o.mean(), roc=auc(sh, o),
                             bss_calibrated=1 - np.mean((q - o) ** 2) / np.mean((o.mean() - o) ** 2),
                             alerts_per_winter_per_basin=al.sum() / nw / len(C.BASINS),
                             alert_right=o[al].mean() if al.any() else np.nan,
                             events_caught=al[o == 1].mean() if (o == 1).any() else np.nan))
    return pd.DataFrame(rows).round(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", default="2020-11-01")
    ap.add_argument("--last", default="2026-02-28")
    ap.add_argument("--no-ecmwf", action="store_true")
    args = ap.parse_args()
    out = C.PRODUCTS / "replay"
    out.mkdir(parents=True, exist_ok=True)
    fp = out / "replay_issues.csv"
    done = pd.read_csv(fp) if fp.exists() else pd.DataFrame(columns=["issue", "product"])
    To, Po = C.load_truth()
    ds = S.gefs_open()
    have = pd.DatetimeIndex(ds.init_time.values)
    starts = [t for t in pd.date_range(args.first, args.last, freq="W-WED")
              if t.month in (11, 12, 1, 2) and t in have]
    rows = done.to_dict("records")
    for t0 in starts:
        want_ec = not args.no_ecmwf and t0 >= pd.Timestamp("2024-03-01")
        have_p = set(done.loc[done.issue == str(t0.date()), "product"])
        if "week2_gefs" in have_p and ("week2" in have_p or not want_ec):
            continue
        rows = [r for r in rows if r["issue"] != str(t0.date())]
        try:
            gefs = S.gefs_windows(ds, t0, R.W)
        except Exception as e:  # noqa: BLE001
            print(t0.date(), "GEFS failed", repr(e)[:200], flush=True)
            continue
        products = {"week2_gefs": R.make(t0, gefs, None)}
        if want_ec and S.ecmwf_available(t0):
            try:
                T, P, _, _ = S.ecmwf_window(t0, *R.W["week2"])
                products["week2"] = R.make(t0, gefs, (T, P))
            except Exception as e:  # noqa: BLE001
                print(t0.date(), "ECMWF failed", repr(e)[:200], flush=True)
        elif want_ec:
            print(t0.date(), "ECMWF not available", flush=True)
        op = C.observed_percentiles(To, Po, t0, *R.W["week2"])
        if op is None:
            continue
        for prod, o in products.items():
            for bi, bn in enumerate(C.BASINS):
                r = dict(issue=str(t0.date()), wy=t0.year + (t0.month >= 10), product=prod, basin=bn)
                for ev in C.A["events"] + C.A["watch_events"]:
                    v = o["basins"][bn]["week2"][ev]
                    s, tail = C.EVENTS[ev]
                    x = op[s][0, bi]
                    r[f"share_{ev}"], r[f"odds_{ev}"] = v["share"], v["odds"]
                    r[f"obs_{ev}"] = float(x <= C.A["tail"] if tail == "lo" else x >= 1 - C.A["tail"])
                rows.append(r)
        print(t0.date(), ", ".join(products), flush=True)
        pd.DataFrame(rows).to_csv(fp, index=False)
    Rr = pd.DataFrame(rows)
    sc = score(Rr)
    sc.to_csv(out / "replay_scores.csv", index=False)
    print(sc.to_string(index=False))


if __name__ == "__main__":
    main()

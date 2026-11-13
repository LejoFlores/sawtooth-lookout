"""Daily week-2 tail-risk alarms for five Idaho basins.

1. Pick the newest 00 UTC start that GEFS (35-day, data.dynamical.org) has through day 21 and, if ECMWF open data has
   the same start through day 15, use ECMWF too.
2. Per system, basin-mean week-2 (days 8-14) temperature and precipitation for every member; GEFS also days 8-21.
3. Rank each member within its own system's reforecast climate (starts within +-21 days of year, all years).
4. Share of members beyond the 10th/90th percentile for each event, GEFS and ECMWF half weight each.
5. Calibrated odds from the season's logistic fit to the hindcast (static/calibration.csv).
6. Write products/YYYYMMDD/alarms.json, latest.json, history.csv, index.html; an alert is open while week-2 odds of
   an alerting event are at or above alert_odds in an alerting season (alerts.json; notify.py turns it into issues).

Run (from the repository root): python3 -m ews.run_daily [--init YYYY-MM-DD | YYYY-MM-DD..YYYY-MM-DD | latest]
[--no-ecmwf]. A range backfills past starts oldest first; latest.json and the root page always show the newest start.
"""
import argparse
import json
import time

import numpy as np
import pandas as pd

from . import common as C
from . import sources as S

W = {"week2": tuple(C.A["week2"]), "fortnight": tuple(C.A["fortnight"])}
LABEL = C.CFG["basins"]


def pick_start(ds, init):
    have = pd.DatetimeIndex(ds.init_time.values)
    have = have[have.hour == 0]
    if init != "latest":
        t0 = pd.Timestamp(init)
        if t0 not in have or not S.gefs_complete(ds, t0, W["fortnight"][1]):
            raise SystemExit(f"GEFS start {t0.date()} missing or incomplete through day {W['fortnight'][1]}")
        return t0
    for t0 in have[::-1][:4]:
        if S.gefs_complete(ds, t0, W["fortnight"][1]):
            return t0
    raise SystemExit("no GEFS start among the last four is complete through day 21")


def system_shares(clim, t0, T, P, window):
    rT, rP = C.reference(clim, t0, window)
    pc = C.member_percentiles(T, P, rT, rP)
    return C.shares(pc), pc


def member_rows(pc, bi, daily):
    """Per member: week-2 percentiles and the alerting/watch events whose tail the member is in."""
    t = C.A["tail"]
    o = {k: np.round(pc[k][:, bi], 3).tolist() for k in ("T", "P", "WD", "WW")}
    o["events"] = [[ev for ev, (st, tail) in C.EVENTS.items()
                    if (pc[st][m, bi] <= t if tail == "lo" else pc[st][m, bi] >= 1 - t)]
                   for m in range(pc["T"].shape[0])]
    if daily is not None:
        o["daily_P_mm"] = np.round(daily[:, :, bi], 2).tolist()
    return o


def make(t0, gefs, ecmwf=None):
    cal = C.load_calibration()
    cg = C.load_climate("gefs")
    sg, pg = system_shares(cg, t0, *gefs["week2"], "week2")
    sf, _ = system_shares(cg, t0, *gefs["fortnight"], "fortnight")
    systems = {"gefs": int(gefs["week2"][0].shape[0])}
    if ecmwf is not None:
        se, pe = system_shares(C.load_climate("ecmwf"), t0, ecmwf[0], ecmwf[1], "week2")
        systems["ecmwf"] = int(ecmwf[0].shape[0])
        week2, prod = {ev: (sg[ev] + se[ev]) / 2 for ev in C.EVENTS}, "week2"
    else:
        se, week2, prod = None, sg, "week2_gefs"
    sea = C.season(t0)
    d0 = t0 + pd.Timedelta(days=W["week2"][0] - 1)
    out = dict(init=str(t0.date()), season=sea, systems=systems, week2_product=prod,
               week2_dates=[str(d0.date()), str((t0 + pd.Timedelta(days=W["week2"][1] - 1)).date())],
               fortnight_dates=[str(d0.date()), str((t0 + pd.Timedelta(days=W["fortnight"][1] - 1)).date())],
               alert_odds=C.A["alert_odds"], alerting=sea in C.A["alert_seasons"], basins={})
    base = cal[(cal["product"] == prod) & (cal.season == sea)].set_index("event")["base_rate"]
    for bi, bn in enumerate(C.BASINS):
        b = dict(name=LABEL[bn], week2={}, fortnight_gefs={})
        for ev in C.EVENTS:
            odds = float(C.calibrate(week2[ev][bi], ev, prod, t0, cal))
            b["week2"][ev] = dict(share=round(float(week2[ev][bi]), 3), odds=round(odds, 3),
                                  share_gefs=round(float(sg[ev][bi]), 3),
                                  share_ecmwf=None if se is None else round(float(se[ev][bi]), 3),
                                  base_rate=round(float(base.get(ev, np.nan)), 3),
                                  alert=bool(out["alerting"] and ev in C.A["events"] and odds >= C.A["alert_odds"]))
            fo = float(C.calibrate(sf[ev][bi], ev, "fortnight_gefs", t0, cal))
            b["fortnight_gefs"][ev] = dict(share=round(float(sf[ev][bi]), 3), odds=round(fo, 3))
        # members for the page: week-2 percentiles of T, P and the warm-dry index, and daily precipitation (mm)
        b["members"] = {"gefs": member_rows(pg, bi, gefs.get("daily_P"))}
        if se is not None:
            b["members"]["ecmwf"] = member_rows(pe, bi, ecmwf[2] if len(ecmwf) > 2 else None)
        b["week2_mean"] = dict(T_C=round(float(np.mean(gefs["week2"][0][:, bi])), 2),
                               P_mm=round(float(np.mean(gefs["week2"][1][:, bi])), 1))
        out["basins"][bn] = b
    out["alerts"] = [dict(basin=bn, event=ev, odds=out["basins"][bn]["week2"][ev]["odds"])
                     for bn in C.BASINS for ev in C.A["events"] if out["basins"][bn]["week2"][ev]["alert"]]
    return out


def history_rows(o):
    rows = []
    for bn, b in o["basins"].items():
        for ev, v in b["week2"].items():
            rows.append(dict(init=o["init"], basin=bn, event=ev, product=o["week2_product"], share=v["share"],
                             odds=v["odds"], share_gefs=v["share_gefs"], share_ecmwf=v["share_ecmwf"],
                             fortnight_share=b["fortnight_gefs"][ev]["share"],
                             fortnight_odds=b["fortnight_gefs"][ev]["odds"], alert=v["alert"]))
    return pd.DataFrame(rows)


def run_one(ds, t0, use_ecmwf):
    print("GEFS start", t0.date(), flush=True)
    gefs = S.gefs_windows(ds, t0, W)
    ec, ec_more = None, {}
    if use_ecmwf and S.ecmwf_available(t0):
        # The S3 mirror throttles (503) bursts of range requests: retry the whole download more gently before
        # falling back to GEFS only.
        for attempt, workers in enumerate((8, 3, 1)):
            try:
                T, P, _, daily = S.ecmwf_window(t0, *W["week2"], workers=workers)
                Ts, Ps = S.ecmwf_split(T), S.ecmwf_split(P)
                ec = (Ts["ecmwf"], Ps["ecmwf"], S.ecmwf_split(daily)["ecmwf"])
                ec_more = {k[:-6]: (Ts[k], Ps[k]) for k in Ts if k != "ecmwf"}
                break
            except Exception as e:  # noqa: BLE001 - a failed ECMWF download falls back to GEFS only
                print(f"ECMWF download failed ({workers} workers):", repr(e)[:300], flush=True)
                if attempt < 2:
                    time.sleep(60)
    print("ECMWF", "yes" if ec is not None else "missing, GEFS only", flush=True)
    o = make(t0, gefs, ec)
    C.PRODUCTS.mkdir(parents=True, exist_ok=True)
    d = C.PRODUCTS / f"{t0:%Y%m%d}"
    d.mkdir(exist_ok=True)
    json.dump(o, open(d / "alarms.json", "w"), indent=1)
    lp = C.PRODUCTS / "latest.json"
    newest = not lp.exists() or json.load(open(lp))["init"] <= o["init"]
    if newest:
        json.dump(o, open(lp, "w"), indent=1)
    hp = C.PRODUCTS / "history.csv"
    h = history_rows(o)
    if hp.exists():
        old = pd.read_csv(hp)
        h = pd.concat([old[old.init != o["init"]], h]).sort_values(["init", "basin", "event"])
    h.to_csv(hp, index=False)
    from . import west
    for prefix in ("huc8", "west"):                    # extra unit sets never block the Idaho products
        try:
            if west.enabled(prefix):
                west.run(ds, t0, ec_more.get(prefix) if ec is not None else None, newest, prefix)
        except Exception as e:  # noqa: BLE001
            print(f"{prefix} units failed:", repr(e)[:500], flush=True)
    from . import page
    page.write(o, h, root=newest)
    if not newest:                                     # backfill: refresh the root page's trend with the new row
        page.write(json.load(open(lp)), h, root=True)
    for a in o["alerts"]:
        print(f"ALERT {LABEL[a['basin']]}: {a['event']} week 2, odds {a['odds']:.0%}")
    print("alerts:", len(o["alerts"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="latest")
    ap.add_argument("--no-ecmwf", action="store_true")
    args = ap.parse_args()
    ds = S.gefs_open()
    if ".." in args.init:
        a, b = args.init.split("..")
        for t in pd.date_range(a, b, freq="D"):
            try:
                run_one(ds, pick_start(ds, str(t.date())), not args.no_ecmwf)
            except SystemExit as e:
                print(t.date(), "skipped:", e, flush=True)
    else:
        run_one(ds, pick_start(ds, args.init), not args.no_ecmwf)


if __name__ == "__main__":
    main()

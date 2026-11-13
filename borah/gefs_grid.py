"""GEFSv12 reforecast daily 2 m temperature and precipitation on the native grid, cropped to the western US.

Source: s3://noaa-gefs-retrospective/GEFSv12/reforecast (NOAA open data, anonymous HTTPS). Wednesday 00 UTC starts run
35 days with the control and 10 perturbed members (other starts stop at day 16, so only Wednesdays are used).
Days 1-10 come from the Days:1-10 files (0.25 deg), days 11-35 from the Days:10-35 files (0.5 deg). Both grids are kept
as they are (no regridding), so any polygon mean later matches the way the live 0.25 deg GEFS is averaged.

Forecast day d of start t0 covers leads 24(d-1) < L <= 24d hours, i.e. the UTC calendar day t0 + d - 1 (as in the step 2
hindcast and the live Sawtooth Lookout job):
  t2m  daily mean of the 6-hourly 2 m temperatures at L = 24d-18, -12, -6, 24d (degC)
  pr   daily total of the four 6 h accumulations ending in the day (mm)
Output, one NetCDF per start: OUT/gefs/YYYY/YYYYMMDD.nc with
  t2m_hi, pr_hi  [member, day_hi (1-10),  lat_hi, lon_hi]   0.25 deg
  t2m_lo, pr_lo  [member, day_lo (11-35), lat_lo, lon_lo]   0.5 deg
  complete       [member, var] fraction of the expected values found on the worst day (1 = complete; 0 = member missing)
Domain (cell centres): 29-57 N, 131.5-99.5 W. About 120 MB is downloaded per member (1.3 GB per start), ~8 MB written.

Usage (every mode skips starts whose output already exists, so any run can simply be repeated):
  python gefs_grid.py --out DIR [--task K --ntasks N] [--only YYYYMMDD,...] [--months 11,12,1]      # fetch + grid
  python gefs_grid.py --out DIR --fetch-only --raw RAW [...]   # download raw GRIB only (login node, no decoding)
  python gefs_grid.py --out DIR --raw RAW [--clean-raw] [...]  # grid from RAW (compute node without internet)
  python gefs_grid.py --list [--months ...]                    # print the start dates and their count
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast"
MEMBERS = ["c00"] + [f"p{k:02d}" for k in range(1, 11)]
VARS = {"tmp_2m": "t2m", "apcp_sfc": "pr"}
WINDOWS = {"1-10": ("hi", range(1, 11)), "10-35": ("lo", range(11, 36))}
LAT = (29.0, 57.0)          # cell-centre bounds of the crop
LON = (-131.5, -99.5)
FIRST, LAST = "2000-01-01", "2019-12-31"

SESSION = requests.Session()
SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=64))


def get(url, rng=None, tries=7):
    """HTTP GET with an optional inclusive byte range, retried with backoff. None on 404."""
    h = {"Range": f"bytes={rng[0]}-{'' if rng[1] is None else rng[1]}"} if rng else {}
    for k in range(tries):
        try:
            r = SESSION.get(url, headers=h, timeout=180)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if k == tries - 1:
                raise
            time.sleep(2 ** k)


def url(t0, mem, window, var):
    return f"{BASE}/{t0:%Y}/{t0:%Y%m%d}00/{mem}/Days:{window}/{var}_{t0:%Y%m%d}00_{mem}.grib2"


def lead(step):
    """'246 hour fcst' -> (246, None); '240-246 hour acc fcst' -> (246, 240)."""
    s = step.split()[0]
    if "-" in s:
        a, b = (int(x) for x in s.split("-"))
        return b, a
    return int(s), None


def selection(idx_text, var):
    """Parse a wgrib2 .idx -> [(byte start, byte end or None, lead h)] of the messages used, and the byte range spanning them."""
    rows = [ln.split(":") for ln in idx_text.strip().split("\n")]
    starts = [int(r[1]) for r in rows]
    ends = [s - 1 for s in starts[1:]] + [None]
    keep = []
    for r, s, e in zip(rows, starts, ends):
        L, L0 = lead(r[5])
        if var == "tmp_2m" and r[3] == "TMP" and L0 is None and L % 6 == 0:
            keep.append((s, e, L))
        elif var == "apcp_sfc" and r[3] == "APCP" and L0 is not None and L - L0 == 6 and L % 6 == 0:
            keep.append((s, e, L))
    return keep


def raw_paths(raw, t0, mem, window, var):
    d = Path(raw) / f"{t0:%Y%m%d}"
    stem = f"{mem}_{var}_{window}"
    return d / f"{stem}.grib2", d / f"{stem}.idx"


def fetch_part(t0, mem, window, var, raw=None, read_raw=False):
    """-> (selected messages, bytes covering them, offset of those bytes in the file), or None if the file is missing."""
    if read_raw:
        g, i = raw_paths(raw, t0, mem, window, var)
        if not i.exists():
            return None
        keep = selection(i.read_text(), var)
        return keep, g.read_bytes(), keep[0][0]
    idx = get(url(t0, mem, window, var) + ".idx")
    if idx is None:
        return None
    text = idx.decode()
    keep = selection(text, var)
    if not keep:
        return None
    buf = get(url(t0, mem, window, var), (keep[0][0], keep[-1][1]))
    if raw is not None:
        g, i = raw_paths(raw, t0, mem, window, var)
        g.parent.mkdir(parents=True, exist_ok=True)
        tmp = g.with_suffix(".part")
        tmp.write_bytes(buf)
        tmp.rename(g)
        i.write_text(text)       # written last: its presence marks the part complete
    return keep, buf, keep[0][0]


def decode(keep, buf, off):
    """Decode the selected messages -> (fields[n, lat, lon] cropped, lat, lon, leads)."""
    import eccodes
    fields, leads, lat, lon = [], [], None, None
    for s, e, L in keep:
        msg = buf[s - off:(None if e is None else e - off + 1)]
        assert msg[:4] == b"GRIB", "byte range does not start a GRIB message"
        n = int.from_bytes(msg[8:16], "big")
        h = eccodes.codes_new_from_message(msg[:n])
        try:
            ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
            la0, la1 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees"), eccodes.codes_get(h, "latitudeOfLastGridPointInDegrees")
            lo0, di = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees"), eccodes.codes_get(h, "iDirectionIncrementInDegrees")
            v = eccodes.codes_get_values(h).reshape(nj, ni)
        finally:
            eccodes.codes_release(h)
        if lat is None:
            la, lo = np.linspace(la0, la1, nj), ((lo0 + di * np.arange(ni) + 180) % 360) - 180
            jy = np.where((la >= LAT[0] - 1e-6) & (la <= LAT[1] + 1e-6))[0]
            jx = np.where((lo >= LON[0] - 1e-6) & (lo <= LON[1] + 1e-6))[0]
            lat, lon = la[jy], lo[jx]
        fields.append(v[np.ix_(jy, jx)])
        leads.append(L)
    return np.array(fields, "f4"), lat, lon, np.array(leads)


def daily(fields, leads, days, how):
    """[n, y, x] at leads (h) -> [len(days), y, x] daily mean or sum, and the fewest values found on any day / 4."""
    day = np.ceil(leads / 24).astype(int)
    out = np.full((len(days),) + fields.shape[1:], np.nan, "f4")
    worst = 4
    for k, d in enumerate(days):
        m = day == d
        worst = min(worst, int(m.sum()))
        if m.sum() == 4:
            out[k] = fields[m].mean(0) if how == "mean" else np.maximum(fields[m], 0).sum(0)
    return out, worst / 4


def member(t0, mem, raw=None, read_raw=False, fetch_only=False):
    res = {}
    for var, short in VARS.items():
        for window, (g, days) in WINDOWS.items():
            part = fetch_part(t0, mem, window, var, raw, read_raw)
            if part is None:
                return None
            if fetch_only:
                continue
            f, lat, lon, leads = decode(*part)
            if var == "tmp_2m":
                f -= 273.15
            res[f"{short}_{g}"], res[f"c_{short}_{g}"] = daily(f, leads, list(days), "mean" if var == "tmp_2m" else "sum")
            res[f"lat_{g}"], res[f"lon_{g}"] = lat, lon
    return res


def write(path, t0, res, ok):
    import xarray as xr
    r0 = next(r for r in res if r is not None)
    ds = xr.Dataset(coords=dict(member=np.array(MEMBERS), day_hi=np.arange(1, 11), day_lo=np.arange(11, 36),
                                lat_hi=r0["lat_hi"], lon_hi=r0["lon_hi"], lat_lo=r0["lat_lo"], lon_lo=r0["lon_lo"],
                                var=np.array(["t2m", "pr"])))
    for g in ("hi", "lo"):
        for v, units, name in (("t2m", "degC", "daily mean 2 m temperature"), ("pr", "mm", "daily precipitation")):
            shp = r0[f"{v}_{g}"].shape
            a = np.stack([r[f"{v}_{g}"] if r is not None else np.full(shp, np.nan, "f4") for r in res])
            ds[f"{v}_{g}"] = (("member", f"day_{g}", f"lat_{g}", f"lon_{g}"), a, dict(units=units, long_name=name))
    comp = np.array([[min(r["c_t2m_hi"], r["c_t2m_lo"]), min(r["c_pr_hi"], r["c_pr_lo"])] if r is not None else [0, 0]
                     for r in res], "f4")
    ds["complete"] = (("member", "var"), comp)
    ds.attrs = dict(source="NOAA GEFSv12 reforecast, s3://noaa-gefs-retrospective", start=f"{t0:%Y-%m-%d}T00Z",
                    day_convention="day d covers leads 24(d-1) < L <= 24d h (UTC calendar day start + d - 1)",
                    members_found=int(sum(ok)), made_by="sawtooth-lookout borah/gefs_grid.py")
    enc = {v: dict(zlib=True, complevel=4, chunksizes=(1,) + ds[v].shape[1:]) for v in ("t2m_hi", "pr_hi", "t2m_lo", "pr_lo")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.nc")
    ds.to_netcdf(tmp, encoding=enc)
    tmp.rename(path)


def start(t0, out, raw, read_raw, fetch_only, clean_raw, workers):
    f = Path(out) / "gefs" / f"{t0:%Y}" / f"{t0:%Y%m%d}.nc"
    if f.exists():
        return "exists"
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda m: member(t0, m, raw, read_raw, fetch_only), MEMBERS))
    ok = [r is not None for r in res]
    if not any(ok):
        return "MISSING (no member found)"
    if fetch_only:
        return f"fetched {sum(ok)} members"
    write(f, t0, res, ok)
    if clean_raw and raw is not None:
        import shutil
        shutil.rmtree(Path(raw) / f"{t0:%Y%m%d}", ignore_errors=True)
    worst = min(min(r["c_t2m_hi"], r["c_t2m_lo"], r["c_pr_hi"], r["c_pr_lo"]) for r in res if r is not None)
    return f"{sum(ok)} members, complete {worst:.2f}"


def starts(months=None):
    d = pd.date_range(FIRST, LAST, freq="W-WED")
    return d[d.month.isin(months)] if months else d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="archive root; files go to OUT/gefs/YYYY/YYYYMMDD.nc")
    ap.add_argument("--raw", help="folder for raw GRIB (with --fetch-only), or to read raw GRIB from")
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--clean-raw", action="store_true", help="delete a start's raw GRIB once its NetCDF is written")
    ap.add_argument("--task", type=int, default=int(os.environ.get("SLURM_ARRAY_TASK_ID", 0)))
    ap.add_argument("--ntasks", type=int, default=int(os.environ.get("NTASKS", 1)))
    ap.add_argument("--only", help="comma-separated YYYYMMDD starts")
    ap.add_argument("--months", help="comma-separated months to keep (default: all)")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 4)) * 2)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    todo = starts([int(m) for m in a.months.split(",")] if a.months else None)
    if a.only:
        todo = pd.DatetimeIndex([pd.Timestamp(x) for x in a.only.split(",")])
    if a.list:
        print("\n".join(f"{t:%Y%m%d}" for t in todo))
        print(len(todo), "starts", file=sys.stderr)
        return
    todo = todo[a.task::a.ntasks]
    if a.fetch_only and not a.raw:
        ap.error("--fetch-only needs --raw")
    read_raw = a.raw is not None and not a.fetch_only
    print(f"task {a.task}/{a.ntasks}: {len(todo)} starts, workers {a.workers}, "
          f"{'fetch only' if a.fetch_only else 'from raw' if read_raw else 'fetch + grid'}", flush=True)
    bad = 0
    for t0 in todo:
        t1 = time.time()
        try:
            msg = start(t0, a.out, a.raw, read_raw, a.fetch_only, a.clean_raw, a.workers)
        except Exception as e:  # noqa: BLE001  keep going; a rerun retries the start
            msg, bad = f"FAILED {repr(e)[:300]}", bad + 1
        print(f"{t0:%Y-%m-%d} {msg} {time.time() - t1:.0f}s", flush=True)
    print(f"done, {bad} failed", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

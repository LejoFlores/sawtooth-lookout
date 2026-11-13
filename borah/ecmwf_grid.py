"""ECMWF extended-range reforecast daily 2 m temperature and precipitation, cropped to the western US.

Source: Planette's Icechunk copy of the ECMWF S2S reforecasts, s3://planette-ifs-46-day/reforecasts (us-east-2,
anonymous, CC BY 4.0): IFS CY49R1, 10 perturbed members, 46 daily leads, starts every other day 2006 to mid 2025, on a
1.5 deg grid. That grid is the reforecast's native resolution, so nothing is regridded; the live job samples ECMWF open
data at the same 1.5 deg nodes.

Lead L is the calendar day start + L (checked against observations in the step 2 hindcast), so forecast day d = L + 1.
  t2m  2 m temperature, daily mean (degC)
  pr   precipitation (mm/day, from the stored kg m-2 s-1 rate, negatives set to 0)
Output, one NetCDF per start: OUT/ecmwf/YYYY/YYYYMMDD.nc, t2m and pr [member, lead, lat, lon], 29.25-56.25 N,
131.25-99.75 W (the WEST_LAT x WEST_LON nodes of the step 2 hindcast plus one row and column of margin).

Usage: python ecmwf_grid.py --out DIR [--task K --ntasks N] [--only YYYYMMDD,...] [--months ...] [--list]
Every run skips starts whose output already exists.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

LAT = (28.5, 57.0)
LON = (-132.0, -99.0)


def open_cube():
    import icechunk
    import xarray as xr
    st = icechunk.s3_storage(bucket="planette-ifs-46-day", prefix="reforecasts", region="us-east-2", anonymous=True)
    store = icechunk.Repository.open(st).readonly_session("main").store
    return xr.open_zarr(store, group="single/1p5latx1p5lon", consolidated=False, chunks=None)


def crop_index(lat, lon):
    lo = ((np.asarray(lon, float) + 180) % 360) - 180
    jy = np.where((lat >= LAT[0]) & (lat <= LAT[1]))[0]
    jx = np.where((lo >= LON[0]) & (lo <= LON[1]))[0]
    jx = jx[np.argsort(lo[jx])]
    return jy, jx, lat[jy], lo[jx]


def write(path, t0, s, jy, jx, la, lo):
    import xarray as xr
    sub = s.sel(init_time=t0).isel(lat=xr.DataArray(jy, dims="lat"), lon=xr.DataArray(jx, dims="lon"))
    t = sub.t2m.values.astype("f4") - 273.15
    p = np.maximum(sub.pr.values.astype("f4") * 86400.0, 0)
    ds = xr.Dataset(dict(t2m=(("member", "lead", "lat", "lon"), t, dict(units="degC")),
                         pr=(("member", "lead", "lat", "lon"), p, dict(units="mm/day"))),
                    coords=dict(member=s.number.values, lead=s.lead.values, lat=la, lon=lo))
    ds.attrs = dict(source="ECMWF IFS CY49R1 extended-range reforecast (CC BY 4.0), via s3://planette-ifs-46-day",
                    start=f"{t0:%Y-%m-%d}T00Z", lead_convention="lead L is the calendar day start + L",
                    made_by="sawtooth-lookout borah/ecmwf_grid.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.nc")
    ds.to_netcdf(tmp, encoding={v: dict(zlib=True, complevel=4) for v in ("t2m", "pr")})
    tmp.rename(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--task", type=int, default=int(os.environ.get("SLURM_ARRAY_TASK_ID", 0)))
    ap.add_argument("--ntasks", type=int, default=int(os.environ.get("NTASKS", 1)))
    ap.add_argument("--only")
    ap.add_argument("--months")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    s = open_cube()
    inits = pd.DatetimeIndex(s.init_time.values)
    if a.months:
        inits = inits[inits.month.isin([int(m) for m in a.months.split(",")])]
    if a.only:
        inits = pd.DatetimeIndex([pd.Timestamp(x) for x in a.only.split(",")])
    if a.list:
        print("\n".join(f"{t:%Y%m%d}" for t in inits))
        print(len(inits), "starts", file=sys.stderr)
        return
    jy, jx, la, lo = crop_index(s.lat.values, s.lon.values)
    todo = inits[a.task::a.ntasks]
    print(f"task {a.task}/{a.ntasks}: {len(todo)} starts", flush=True)
    bad = 0
    for t0 in todo:
        f = Path(a.out) / "ecmwf" / f"{t0:%Y}" / f"{t0:%Y%m%d}.nc"
        if f.exists():
            continue
        t1 = time.time()
        for k in range(4):
            try:
                write(f, t0, s, jy, jx, la, lo)
                print(f"{t0:%Y-%m-%d} ok {time.time() - t1:.0f}s", flush=True)
                break
            except Exception as e:  # noqa: BLE001
                if k == 3:
                    bad += 1
                    print(f"{t0:%Y-%m-%d} FAILED {repr(e)[:300]}", flush=True)
                time.sleep(5 * 2 ** k)
    print(f"done, {bad} failed", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

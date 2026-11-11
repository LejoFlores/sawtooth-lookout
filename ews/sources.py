"""Live ensemble data, reduced to basin window statistics the way the reforecasts were.

Day d of a start t0 is the UTC day t0 + d - 1, i.e. lead hours (24(d-1), 24d]. Window temperature is the mean of the
6-hourly 2 m temperatures at leads 24(a-1)+6 ... 24b; window precipitation is the total over (24(a-1), 24b].
"""
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from . import common as C

SO = {"client_kwargs": {"trust_env": True}}


# ------------------------------------------------------------------------------------------------------------ GEFS
def gefs_open():
    import xarray as xr
    ds = xr.open_zarr(C.CFG["source"]["gefs_forecast"], storage_options=SO, chunks=None)
    if float(ds.longitude.max()) > 180:
        ds = ds.assign_coords(longitude=((ds.longitude + 180) % 360) - 180).sortby("longitude")
    return ds


def gefs_complete(ds, t0, day):
    """True when member 0 has 2 m temperature at the end of forecast day `day` over Idaho."""
    lt = np.timedelta64(24 * day, "h")
    if lt not in ds.lead_time.values:
        return False
    v = ds.temperature_2m.sel(init_time=t0, ensemble_member=ds.ensemble_member[0], lead_time=lt,
                              latitude=44, longitude=-114, method="nearest")
    return bool(np.isfinite(v.load().values))


def gefs_windows(ds, t0, windows):
    """-> {window: (T[member, basin], P[member, basin])} for windows {name: (a, b)}."""
    lat, lon, _ = C.load_weights("gefs")
    sub = ds.sel(init_time=t0, latitude=slice(lat.max() + 0.01, lat.min() - 0.01),
                 longitude=slice(lon.min() - 0.01, lon.max() + 0.01))
    bmax = max(b for _, b in windows.values())
    sub = sub.sel(lead_time=sub.lead_time[sub.lead_time <= np.timedelta64(24 * bmax, "h")])
    T = sub.temperature_2m.load()
    P = sub.precipitation_surface.load()
    lh = (T.lead_time.values / np.timedelta64(1, "h")).astype(float)
    Tb = C.basin_mean(T.values, T.latitude.values, T.longitude.values, "gefs")           # [member, lead, basin]
    Pb = C.basin_mean(P.values, P.latitude.values, P.longitude.values, "gefs")
    amt = Pb * np.diff(lh, prepend=0.0)[None, :, None] * 3600.0                           # rate over the step -> mm
    out = {}
    for wn, (a, b) in windows.items():
        tsel = (lh > 24 * (a - 1)) & (lh <= 24 * b) & (lh % 6 == 0)
        psel = (lh > 24 * (a - 1)) & (lh <= 24 * b)
        assert tsel.sum() == 4 * (b - a + 1), f"GEFS {wn}: {tsel.sum()} temperature steps"
        out[wn] = (Tb[:, tsel].mean(1), amt[:, psel].sum(1))
    day = np.ceil(lh / 24).astype(int)                                                    # UTC forecast day
    out["daily_P"] = np.stack([amt[:, day == d].sum(1) for d in range(1, bmax + 1)], 1)    # [member, day, basin] mm
    return out


# ----------------------------------------------------------------------------------------------------------- ECMWF
def _ecmwf_url(t0, step, ext):
    return (f"{C.CFG['source']['ecmwf_open']}/{t0:%Y%m%d}/00z/ifs/0p25/enfo/"
            f"{t0:%Y%m%d}000000-{step}h-enfo-ef.{ext}")


def _get(url, session=None, method="get", **kw):
    """HTTP with retries: the S3 mirror answers 503 (slow down) under load."""
    import time
    f = getattr(session or requests, method)
    import random
    for attempt in range(8):
        try:
            r = f(url, timeout=120, **kw)
            if r.status_code in (500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}", response=r)
            return r
        except requests.RequestException:
            if attempt == 7:
                raise
            time.sleep(min(2 ** attempt, 30) * (0.5 + random.random()))       # jittered backoff, up to ~2 min total


def ecmwf_available(t0, step=360):
    return _get(_ecmwf_url(t0, step, "index"), method="head").status_code == 200


def _index(t0, step, param):
    r = _get(_ecmwf_url(t0, step, "index"))
    r.raise_for_status()
    rows = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    return [x for x in rows if x["param"] == param and x.get("levtype") == "sfc"]


def _fetch(t0, step, entry, session):
    rng = f"bytes={entry['_offset']}-{entry['_offset'] + entry['_length'] - 1}"
    r = _get(_ecmwf_url(t0, step, "grib2"), session, headers={"Range": rng})
    r.raise_for_status()
    return r.content


def _decode_basins(buf):
    """One GRIB message on the global 0.25 deg grid -> (member number, basin means at the 1.5 deg sampling nodes)."""
    import eccodes
    h = eccodes.codes_new_from_message(buf)
    try:
        ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
        la0 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
        la1 = eccodes.codes_get(h, "latitudeOfLastGridPointInDegrees")
        lo0 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
        di = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
        num = eccodes.codes_get(h, "number") if eccodes.codes_is_defined(h, "number") else 0
        v = eccodes.codes_get_values(h).reshape(nj, ni)
    finally:
        eccodes.codes_release(h)
    lat, lon = np.linspace(la0, la1, nj), lo0 + di * np.arange(ni)
    return int(num), C.basin_mean(v, lat, lon, "ecmwf")


def ecmwf_window(t0, a, b, workers=8):
    """ECMWF ENS open data for window days a..b (b <= 15) ->
    (T[member, basin], P[member, basin], members, daily_P[member, day 1-15, basin] in mm)."""
    assert b <= 15
    tsteps = list(range(24 * (a - 1) + 6, 24 * b + 1, 6))
    jobs = [(s, e) for s in tsteps for e in _index(t0, s, "2t")]
    psteps = list(range(24, 361, 24))                                                    # tp accumulates from 0 h
    p0, p1 = 24 * (a - 1), 24 * b
    jobs += [(s, e) for s in psteps for e in _index(t0, s, "tp")]
    sess = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=workers)
    sess.mount("https://", adapter)

    def one(job):
        s, e = job
        num, vals = _decode_basins(_fetch(t0, s, e, sess))
        return e["param"], s, num, vals
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, jobs))
    members = sorted({r[2] for r in res})
    mi = {m: i for i, m in enumerate(members)}
    nb = len(C.BASINS)
    T = np.full((len(members), len(tsteps), nb), np.nan)
    tp = np.zeros((len(members), len(psteps) + 1, nb))                                  # index k = step 24k
    for param, s, num, vals in res:
        if param == "2t":
            T[mi[num], tsteps.index(s)] = vals - 273.15
        else:
            tp[mi[num], s // 24] = vals * 1000.0                                          # m -> mm
    daily = np.maximum(np.diff(tp, axis=1), 0)
    P = np.maximum(tp[:, p1 // 24] - tp[:, p0 // 24], 0)
    return T.mean(1), P, np.array(members), daily

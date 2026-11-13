"""Area-weighted polygon (basin) means of the gridded reforecast archive written by gefs_grid.py and ecmwf_grid.py.

Each grid cell is a lon/lat box; its weight in a polygon is the area of their overlap (computed in CONUS Albers,
EPSG:5070), normalised per polygon. This is the same rule as ews/common.weights, so means match the live job's.

Output, one .npz per start, in the layout the five-basin hindcast (ext5/gefs, ext5/ecmwf) and scripts/build_static.py use:
  OUT/gefs/YYYYMMDD.npz   t2m, precip [member, day, basin] float32 for days 1-35; days, members, basins, complete
  OUT/ecmwf/YYYYMMDD.npz  t2m, precip [member, lead, basin] float32 for leads 0-45; leads, members, basins
  OUT/basins.csv          the basin order (id, area_km2, cells used per grid)
Usage:
  python polygon_means.py --polygons huc8.gpkg [--layer huc8] --id huc8 [--keep list.csv] --system gefs|ecmwf \
      --archive ARCHIVE --out OUT [--task K --ntasks N]
--keep takes a CSV whose first column (or the --id column) lists the polygon ids to use, in that order.
Every run skips starts whose output already exists (delete OUT to redo after changing the polygons).
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load_polygons(path, layer, idcol, keep):
    import geopandas as gpd
    g = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    g[idcol] = g[idcol].astype(str)
    g = g.dissolve(idcol, as_index=False)
    if keep:
        k = pd.read_csv(keep, dtype=str)
        ids = list(k[idcol] if idcol in k else k.iloc[:, 0])
        missing = sorted(set(ids) - set(g[idcol]))
        if missing:
            sys.exit(f"polygons missing for {len(missing)} ids: {missing[:10]}")
        g = g.set_index(idcol).loc[ids].reset_index()
    return g.to_crs(5070)


def weights(g, lat, lon):
    """-> W[basin, lat*lon] area shares (rows sum to 1) for cell centres lat, lon (regular spacing)."""
    import geopandas as gpd
    from shapely.geometry import box
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    dy, dx = abs(lat[1] - lat[0]), abs(lon[1] - lon[0])
    cells = gpd.GeoSeries([box(x - dx / 2, y - dy / 2, x + dx / 2, y + dy / 2) for y in lat for x in lon], crs=4326).to_crs(5070)
    tree = cells.sindex
    W = np.zeros((len(g), len(cells)), "f8")
    for k, geom in enumerate(g.geometry):
        idx = tree.query(geom, predicate="intersects")
        W[k, idx] = cells.iloc[idx].intersection(geom).area.values
    s = W.sum(1, keepdims=True)
    if (s == 0).any():
        sys.exit("some polygons lie outside the archive's domain")
    return (W / s).astype("f4")


def apply(W, a):
    """a[..., lat, lon] -> [..., basin]."""
    return (a.reshape(a.shape[:-2] + (-1,)) @ W.T).astype("f4")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--polygons", required=True)
    ap.add_argument("--layer")
    ap.add_argument("--id", required=True)
    ap.add_argument("--keep")
    ap.add_argument("--system", choices=["gefs", "ecmwf"], required=True)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", type=int, default=int(os.environ.get("SLURM_ARRAY_TASK_ID", 0)))
    ap.add_argument("--ntasks", type=int, default=int(os.environ.get("NTASKS", 1)))
    a = ap.parse_args()
    import xarray as xr
    g = load_polygons(a.polygons, a.layer, a.id, a.keep)
    ids = np.array(g[a.id], dtype=str)
    files = sorted((Path(a.archive) / a.system).glob("[0-9][0-9][0-9][0-9]/[0-9]*[0-9].nc"))
    if not files:
        sys.exit(f"no archive files under {Path(a.archive) / a.system}")
    out = Path(a.out) / a.system
    out.mkdir(parents=True, exist_ok=True)
    W = {}
    with xr.open_dataset(files[0]) as d:
        grids = ["hi", "lo"] if a.system == "gefs" else [""]
        for gname in grids:
            sfx = f"_{gname}" if gname else ""
            W[gname] = weights(g, d[f"lat{sfx}"].values, d[f"lon{sfx}"].values)
            grid = (d[f"lat{sfx}"].values, d[f"lon{sfx}"].values)
            W[gname + "grid"] = grid
    if a.task == 0:
        info = pd.DataFrame({a.id: ids, "area_km2": (g.area / 1e6).round(1).values})
        for gname in grids:
            info[f"cells{('_' + gname) if gname else ''}"] = (W[gname] > 0).sum(1)
        info.to_csv(Path(a.out) / f"basins_{a.system}.csv", index=False)
    todo = files[a.task::a.ntasks]
    print(f"task {a.task}/{a.ntasks}: {len(todo)} starts, {len(ids)} polygons", flush=True)
    n = 0
    for f in todo:
        o = out / f"{f.stem}.npz"
        if o.exists():
            continue
        with xr.open_dataset(f) as d:
            for gname in grids:
                sfx = f"_{gname}" if gname else ""
                assert np.allclose(d[f"lat{sfx}"].values, W[gname + "grid"][0]) and \
                    np.allclose(d[f"lon{sfx}"].values, W[gname + "grid"][1]), f"{f.name}: grid differs"
            if a.system == "gefs":
                t = np.concatenate([apply(W["hi"], d.t2m_hi.values), apply(W["lo"], d.t2m_lo.values)], 1)
                p = np.concatenate([apply(W["hi"], d.pr_hi.values), apply(W["lo"], d.pr_lo.values)], 1)
                extra = dict(days=np.concatenate([d.day_hi.values, d.day_lo.values]), complete=d.complete.values)
            else:
                t, p = apply(W[""], d.t2m.values), apply(W[""], d.pr.values)
                extra = dict(leads=d.lead.values)
            tmp = o.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, t2m=t, precip=p, members=d.member.values.astype(str), basins=ids, **extra)
            tmp.rename(o)
        n += 1
    print(f"done, {n} written", flush=True)


if __name__ == "__main__":
    main()

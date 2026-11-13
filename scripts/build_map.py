"""Build the web map layers in static/map/ (run once; outputs are committed).

  static/map/active.geojson   the basins Sawtooth Lookout forecasts (from static/basins.gpkg)
  static/map/others.geojson   other Idaho HUC8 basins, coloured when screened as water-supply HUC8s (static/huc8_units.csv), else grey
                              (USGS Watershed Boundary Dataset, regions 16 and 17, HUC8s whose states include ID,
                              minus those mostly inside an active basin)
  static/map/idaho.geojson    state outline (us-atlas 3.0.1 states-10m, from US Census cartographic boundaries)

Run (from the repository root): python3 scripts/build_map.py WBD_16_HU2_GDB.gdb WBD_17_HU2_GDB.gdb idaho.geojson
"""
import json
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ews import common as C  # noqa: E402

TOL = 0.004                                                       # simplification tolerance, degrees (~400 m)
OUT = C.STATIC / "map"


def main(gdbs, idaho):
    OUT.mkdir(parents=True, exist_ok=True)
    act = gpd.read_file(C.STATIC / "basins.gpkg").set_index("basin").loc[C.BASINS].to_crs(4326)
    act["name"] = [C.CFG["basins"][b] for b in act.index]
    act = act.reset_index()[["basin", "name", "geometry"]]
    h8 = pd.concat([gpd.read_file(g, layer="WBDHU8")[["huc8", "name", "states", "geometry"]] for g in gdbs])
    h8 = h8[h8.states.str.contains("ID", na=False)].to_crs(5070)
    a5 = act.to_crs(5070).union_all()
    inside = h8.geometry.intersection(a5).area / h8.geometry.area
    oth = h8[inside < 0.5].to_crs(4326)[["huc8", "name", "geometry"]]
    for df, name in ((act, "active"), (oth, "others")):
        df = df.copy()
        df["geometry"] = df.geometry.simplify(TOL, preserve_topology=True)
        df.to_file(OUT / f"{name}.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)
        print(name, len(df), f"{(OUT / f'{name}.geojson').stat().st_size / 1e3:.0f} kB")
    shutil.copy(idaho, OUT / "idaho.geojson")
    json.load(open(OUT / "idaho.geojson"))


if __name__ == "__main__":
    main(sys.argv[1:3], sys.argv[3])

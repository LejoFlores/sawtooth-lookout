"""West-wide view: the same week-2 tail odds on USGS HUC4 subregions, as a map only (no alert issues).

Coarser than the Idaho basins by design: the reforecast climate is on 1.5 deg boxes, so the live GEFS field is
box-averaged the same way and the live ECMWF field is sampled at the 1.5 deg nodes, then both are area-weighted to
each HUC4 (static/weights_west_*.npz). Calibration pools all units per event and season (static/west_calibration.csv,
truth: CPC gauge precipitation and station temperature). Built by scripts/build_west.py.
Writes products/west/latest.json, history.csv, index.html and products/YYYYMMDD/west.json.
"""
import html
import json

import numpy as np
import pandas as pd

from . import common as C
from . import sources as S

W2 = tuple(C.A["week2"])
HI = 0.25                                   # map shading: odds at or above this are the top class


def enabled():
    return all((C.STATIC / f).exists() for f in ("weights_west_gefs.npz", "clim_west_gefs.npz", "west_calibration.csv"))


def _shares(system, t0, T, P):
    clim = C.load_climate(f"west_{system}")
    return C.shares(C.member_percentiles(T, P, *C.reference(clim, t0, "week2")))


def make(t0, gefs, ecmwf=None):
    """gefs, ecmwf: (T[member, unit], P[member, unit]) for week 2 -> the West product dict."""
    units = pd.read_csv(C.STATIC / "west_units.csv", dtype=str)
    cal = pd.read_csv(C.STATIC / "west_calibration.csv")
    sc = pd.read_csv(C.STATIC / "west_scores.csv", dtype={"huc4": str})
    sg = _shares("gefs", t0, *gefs)
    systems = {"gefs": int(gefs[0].shape[0])}
    if ecmwf is not None:
        se = _shares("ecmwf", t0, *ecmwf)
        systems["ecmwf"] = int(ecmwf[0].shape[0])
        sh, prod = {ev: (sg[ev] + se[ev]) / 2 for ev in C.EVENTS}, "week2"
    else:
        se, sh, prod = None, sg, "week2_gefs"
    sea = C.season(t0)
    base = cal[(cal["product"] == prod) & (cal.season == sea)].set_index("event")["base_rate"]
    roc = sc[(sc["product"] == prod) & (sc.season == sea)].set_index(["huc4", "event"])["roc"]
    out = dict(init=str(t0.date()), season=sea, systems=systems, week2_product=prod,
               week2_dates=[str((t0 + pd.Timedelta(days=W2[0] - 1)).date()), str((t0 + pd.Timedelta(days=W2[1] - 1)).date())],
               alert_odds=C.A["alert_odds"], alerting=sea in C.A["alert_seasons"], events=C.A["events"], units={})
    for i, (h, name) in enumerate(zip(units.huc4, units.name)):
        u = dict(name=name, week2={})
        for ev in C.A["events"]:
            odds = float(C.calibrate(sh[ev][i], ev, prod, t0, cal))
            r = roc.get((h, ev), np.nan)
            u["week2"][ev] = dict(share=round(float(sh[ev][i]), 3), odds=None if np.isnan(odds) else round(odds, 3),
                                  share_gefs=round(float(sg[ev][i]), 3),
                                  share_ecmwf=None if se is None else round(float(se[ev][i]), 3),
                                  base_rate=round(float(base.get(ev, np.nan)), 3),
                                  hindcast_roc=None if np.isnan(r) else round(float(r), 2))
        out["units"][h] = u
    return out


def history_rows(o):
    return pd.DataFrame([dict(init=o["init"], huc4=h, event=ev, product=o["week2_product"], share=v["share"], odds=v["odds"])
                         for h, u in o["units"].items() for ev, v in u["week2"].items()])


def run(ds, t0, ecmwf, newest=True):
    g = S.gefs_windows(ds, t0, {"week2": W2}, wname="west_gefs")["week2"]
    o = make(t0, g, ecmwf)
    p = C.PRODUCTS / "west"
    p.mkdir(parents=True, exist_ok=True)
    day = C.PRODUCTS / f"{t0:%Y%m%d}"
    day.mkdir(exist_ok=True)
    json.dump(o, open(day / "west.json", "w"))
    hp, h = p / "history.csv", history_rows(o)
    if hp.exists():
        old = pd.read_csv(hp, dtype={"huc4": str})
        h = pd.concat([old[old.init != o["init"]], h]).sort_values(["init", "huc4", "event"])
    h.to_csv(hp, index=False)
    if newest:
        json.dump(o, open(p / "latest.json", "w"))
        (p / "index.html").write_text(render(o))
    n = sum(1 for u in o["units"].values() for v in u["week2"].values() if v["odds"] is not None and v["odds"] >= o["alert_odds"])
    print(f"West: {len(o['units'])} HUC4 units, {n} unit-events at or above {o['alert_odds']:.0%}", flush=True)
    return o


def render(o):
    from . import page as Pg
    up = "../"
    lv = o["alert_odds"]
    rows = sorted(((v["odds"], u["name"], ev, v) for u in o["units"].values() for ev, v in u["week2"].items()
                   if v["odds"] is not None and v["odds"] >= lv), key=lambda r: -r[0])
    tab = "".join(f"<tr><td style='text-align:left'>{html.escape(n)}</td><td>{Pg.EV_LABEL[ev]}</td><td><b>{od:.0%}</b></td>"
                  f"<td>{v['base_rate']:.0%}</td><td>{'' if v['hindcast_roc'] is None else v['hindcast_roc']}</td></tr>"
                  for od, n, ev, v in rows[:40])
    tab = (f"<div class=wrap><table><tr><th>Subregion</th><th>Signal</th><th>Week-2 odds</th><th>Usual odds</th>"
           f"<th>Past detection skill here</th></tr>{tab}</table></div>" if rows else "<p>No subregion is at or above the alert level.</p>")
    more = f"<p class=mut>Showing the 40 highest of {len(rows)}.</p>" if len(rows) > 40 else ""
    legend = "".join(f"<span style='background:{Pg.LEVEL[k][0]}'></span>{t}" for k, t in
                     (("hi", f"odds {HI:.0%} or more"), ("mid", f"{lv:.0%} to {HI:.0%}"), ("lo", f"below {lv:.0%}")))
    btn = "".join(f"<button data-ev='{e}'>{Pg.EV_LABEL[e]}</button>" for e in o["events"])
    data = json.dumps({h: dict(name=u["name"], w=u["week2"]) for h, u in o["units"].items()})
    body = f"""<p><a href="{up}">&larr; Idaho basins</a></p>
<h2>The West, by HUC4 subregion</h2>
<p class=mut>The same week-2 signals on {len(o['units'])} large river subregions. This view is coarser than the Idaho
basins and is a map only: it opens no alerts. Shaded by the highest odds among the signals, or pick one signal.
Hover for the odds and how well the signal was detected there in past winters.</p>
<p class=evbtn><button data-ev='all' class=on>Highest of all</button>{btn}</p>
<div id=map></div><p class="mut legend">{legend}</p>
<h2>Subregions at or above {lv:.0%} odds</h2>{tab}{more}
<h2>How this works</h2>
<p class=mut>Each member's subregion-mean week-2 temperature and precipitation is ranked within its own model's
reforecast climate, and the share of members in the tail (GEFS and ECMWF half each) is turned into odds with one
logistic fit per signal and season, pooled over all subregions. Forecast fields are averaged onto 1.5 degree boxes
before the subregion mean, to match the reforecast archive. Hindcast (GEFS and ECMWF reforecasts against CPC gauge
precipitation and station temperature): detection is best for cold-wet and warm-dry weeks and weakest for dry-only
weeks, and warm-dry skill is lower in the northern interior than in California and the Southwest. "Past detection
skill" is the ROC area for that subregion and season (0.5 is no skill, 1 is perfect); it rests on about 25 events per
subregion, so treat it as rough. Subregion boundaries: USGS Watershed Boundary Dataset. Forecast data: NOAA GEFS via
dynamical.org; ECMWF open data, &copy; ECMWF, CC BY 4.0. Truth for the hindcast: NOAA CPC unified gauge analysis.</p>
<style>.evbtn button{{font:inherit;padding:4px 10px;margin:0 6px 6px 0;border:1px solid var(--line);border-radius:14px;
background:var(--lo);color:var(--fg);cursor:pointer}} .evbtn button.on{{background:var(--fg);color:var(--bg)}}</style>
<script>
(function(){{
  if (!window.L) return;
  var S = {data}, LV = {lv}, HI = {HI}, EV = {json.dumps(o['events'])}, LAB = {json.dumps({e: Pg.EV_LABEL[e] for e in o['events']})};
  var COL = {json.dumps({k: v[0] for k, v in Pg.LEVEL.items()})}, sel = 'all', layer;
  var dark = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches;
  var m = L.map('map', {{scrollWheelZoom: false, zoomSnap: 0.25}}).setView([41, -114], 5);
  L.tileLayer('https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{maxZoom: 8, opacity: dark ? 0.6 : 0.8, attribution: 'Basemap: USGS The National Map'}}).addTo(m);
  function level(v) {{ return v.odds === null ? null : v.odds >= HI ? 'hi' : v.odds >= LV ? 'mid' : 'lo'; }}
  function unitLevel(s) {{
    var evs = sel === 'all' ? EV : [sel], best = null, rank = {{lo: 0, mid: 1, hi: 2}};
    evs.forEach(function(e) {{ var l = level(s.w[e]); if (l !== null && (best === null || rank[l] > rank[best])) best = l; }});
    return best;
  }}
  function style(f) {{
    var s = S[f.properties.huc4], l = s ? unitLevel(s) : null;
    return {{color: '#0f172a', weight: 0.8, fillColor: l ? COL[l] : '#cbd5e1', fillOpacity: l === 'lo' ? 0.3 : 0.6}};
  }}
  function tip(s) {{
    return '<b>' + s.name + '</b><br>' + EV.map(function(e) {{
      var v = s.w[e];
      return LAB[e] + ': ' + (v.odds === null ? 'n/a' : Math.round(100 * v.odds) + '%') +
        ' (usual ' + Math.round(100 * v.base_rate) + '%' + (v.hindcast_roc === null ? '' : ', skill ' + v.hindcast_roc) + ')';
    }}).join('<br>');
  }}
  fetch('{up}map/west_huc4.geojson').then(function(r) {{ return r.json(); }}).then(function(g) {{
    layer = L.geoJSON(g, {{style: style, onEachFeature: function(f, l) {{
      var s = S[f.properties.huc4];
      if (s) l.bindTooltip(tip(s), {{sticky: true}});
      l.on('mouseover', function() {{ l.setStyle({{weight: 2.5}}); }});
      l.on('mouseout', function() {{ l.setStyle({{weight: 0.8}}); }});
    }}}}).addTo(m);
    m.fitBounds(layer.getBounds(), {{padding: [4, 4]}});
  }});
  document.querySelectorAll('.evbtn button').forEach(function(b) {{
    b.addEventListener('click', function() {{
      sel = b.getAttribute('data-ev');
      document.querySelectorAll('.evbtn button').forEach(function(x) {{ x.classList.toggle('on', x === b); }});
      if (layer) layer.setStyle(style);
    }});
  }});
}})();
</script>"""
    return Pg.shell(o, up, "Sawtooth Lookout: the West", body,
                    f"<link rel=stylesheet href='{up}vendor/leaflet/leaflet.css'><script src='{up}vendor/leaflet/leaflet.js'></script>")

"""Member-by-member page for the extra Idaho HUC8 units: one page that fills itself in from a small JSON per unit.

products/YYYYMMDD/huc8/<huc8>.json   that start's odds, members (week-2 percentiles, flags, daily precipitation) and
                                     the odds of the last runs
products/YYYYMMDD/huc8/index.html    the page for that start; ?b=<huc8> picks the unit
products/huc8/index.html             the same page for the newest start
The front page only links here (a click on the map), so adding units adds no rows to it.
"""
import json

import pandas as pd

from . import common as C

TREND_RUNS = 14


def write(o, mem, h, day, root=None):
    """o: unit-set product; mem: {unit: {system: member rows}}; h: the set's history; day: dated folder;
    root: products/huc8 when this is the newest start."""
    day.mkdir(parents=True, exist_ok=True)
    h = h[h.init <= o["init"]]
    inits = sorted(h.init.unique())[-TREND_RUNS:]
    h = h[h.init.isin(inits)]
    tr = {u: g for u, g in h.groupby("unit")}
    for uid, u in o["units"].items():
        g = tr.get(uid)
        trend = {} if g is None else {
            ev: [None if pd.isna(x) else round(float(x), 3) for x in e.set_index("init").odds.reindex(inits)]
            for ev, e in g.groupby("event")}
        json.dump(dict(huc8=uid, name=u["name"], init=o["init"], week2=u["week2"], members=mem[uid],
                       trend=dict(init=list(inits), odds=trend)),
                  open(day / f"{uid}.json", "w"), separators=(",", ":"))
    (day / "index.html").write_text(render(o, "./", "../../"))
    if root is not None:
        (root / "index.html").write_text(render(o, f"../{o['init'].replace('-', '')}/huc8/", "../"))


def render(o, base, up):
    from . import page as Pg
    units = pd.read_csv(C.STATIC / "huc8_units.csv", dtype=str)
    U = {r.huc8: dict(name=r["name"], tier=r.tier) for _, r in units.iterrows() if r.huc8 in o["units"]}
    cfg = dict(base=base, units=U, events=o["events"], lab={e: Pg.EV_LABEL[e] for e in o["events"]},
               flag={e: Pg.FLAG[e] for e in o["events"]}, col={e: Pg.COL[e] for e in o["events"]},
               lv=o["alert_odds"], tail=C.A["tail"], w2=list(C.A["week2"]), init=o["init"],
               pscale=[[hi, bg, fg] for hi, _, bg, fg in Pg.PSCALE if hi < 1e8] + [[1e9, Pg.PSCALE[-1][2], Pg.PSCALE[-1][3]]],
               ev_tail={e: list(C.EVENTS[e]) for e in o["events"]})
    key = "".join(f"<span style='background:{bg};color:{fg}'>{lab}</span>" for _, lab, bg, fg in Pg.PSCALE)
    body = f"""<p><a href="../">&larr; Map and all basins</a></p>
<p><label>Basin <select id=pick></select></label></p>
<div id=unit><p class=mut>Pick a basin, or click one on the map.</p></div>
<div id=key hidden><p class=key>Colour key (in): {key}</p>
<p class=mut>Experimental: these basins open no alerts. Odds are calibrated against PRISM basin means, pooled over the
water-supply HUC8s. Each member's week-2 temperature and precipitation is ranked within its own model's reforecast
climate; flags mark members in an alarm tail (<b>WD</b> warm-dry, <b>D</b> dry, <b>WW</b> warm-wet, <b>CW</b>
cold-wet). The table shows the running basin-mean precipitation total (inches) from the start, wettest member first
by the end of week 2. ECMWF members stop at day 15. Past skill is the ROC area in past forecasts for this basin and
season: 0.5 is none, 1 is perfect, and it rests on about 25 events.</p></div>
<style>.two{{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}} .two svg{{max-width:100%;height:auto}}
svg text{{fill:var(--fg);font:11px Inter,system-ui,sans-serif}} svg .ax{{stroke:var(--mut);fill:none}}
select{{font:inherit;padding:3px 6px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:4px}}</style>
<script>
(function(){{
  var C = {json.dumps(cfg)};
  var pick = document.getElementById('pick'), box = document.getElementById('unit');
  function esc(s) {{ return String(s).replace(/[&<>"']/g, function(c) {{ return '&#' + c.charCodeAt(0) + ';'; }}); }}
  function pc(v) {{ return v === null || v === undefined ? 'n/a' : Math.round(100 * v) + '%'; }}
  var ids = Object.keys(C.units).sort(function(a, b) {{ return C.units[a].name.localeCompare(C.units[b].name); }});
  pick.innerHTML = '<option value="">Choose a basin</option>' + ids.map(function(i) {{
    return '<option value="' + i + '">' + esc(C.units[i].name) + ' (' + i + ')</option>'; }}).join('');
  pick.addEventListener('change', function() {{ if (pick.value) {{ history.replaceState(null, '', '?b=' + pick.value); load(pick.value); }} }});
  function pcol(v) {{
    if (v < 0.005) return ['', ''];
    for (var i = 0; i < C.pscale.length; i++) if (v < C.pscale[i][0]) return [C.pscale[i][1], C.pscale[i][2]];
    return ['', ''];
  }}
  function fmt(v) {{ if (v < 0.005) return ''; if (v < 0.05) return 'T'; var s = v.toFixed(1); return s.indexOf('0.') === 0 ? s.slice(1) : s; }}
  function tcol(p) {{ var x = 2 * p - 1; return x >= 0 ? 'rgba(220,38,38,' + (0.75 * x).toFixed(2) + ')' : 'rgba(37,99,235,' + (-0.75 * x).toFixed(2) + ')'; }}
  function oddsTable(d) {{
    var head = C.events.map(function(e) {{ return '<th>' + C.lab[e] + '</th>'; }}).join('');
    var cells = C.events.map(function(e) {{
      var v = d.week2[e];
      if (v.odds === null) return '<td class=na>n/a</td>';
      var lvl = v.odds >= C.lv ? 'hi' : (v.odds >= 1.5 * v.base_rate ? 'mid' : 'lo');
      return '<td class="' + lvl + '"><b>' + pc(v.odds) + '</b><span>vs ' + pc(v.base_rate) + ' usual</span></td>';
    }}).join('');
    var sh = C.events.map(function(e) {{ var v = d.week2[e];
      return '<td>GEFS ' + pc(v.share_gefs) + (v.share_ecmwf === null ? '' : ' · ECMWF ' + pc(v.share_ecmwf)) + '</td>'; }}).join('');
    var sk = C.events.map(function(e) {{ var v = d.week2[e]; return '<td>' + (v.hindcast_roc === null ? 'n/a' : v.hindcast_roc.toFixed(2)) + '</td>'; }}).join('');
    return '<div class=wrap><table><tr><th></th>' + head + '</tr><tr><th>Week-2 odds</th>' + cells +
      '</tr><tr><th>Members in the tail</th>' + sh + '</tr><tr><th>Past skill</th>' + sk + '</tr></table></div>';
  }}
  function scatter(d) {{
    var S = 300, m = 34, t = C.tail, n = S - 2 * m;
    function x(p) {{ return m + n * p; }} function y(p) {{ return S - m - n * p; }}
    var g = '<rect x="' + x(0) + '" y="' + y(t) + '" width="' + n + '" height="' + n * t + '" fill="#fde68a" opacity=".5"/>' +
      '<rect x="' + x(0) + '" y="' + y(1) + '" width="' + n + '" height="' + n * t + '" fill="#99f6e4" opacity=".6"/>' +
      '<rect x="' + x(1 - t) + '" y="' + y(1) + '" width="' + n * t + '" height="' + n + '" fill="#fecaca" opacity=".5"/>' +
      '<rect x="' + x(0) + '" y="' + y(1) + '" width="' + n * t + '" height="' + n + '" fill="#bfdbfe" opacity=".5"/>' +
      '<rect class=ax x="' + m + '" y="' + m + '" width="' + n + '" height="' + n + '"/>';
    [['gefs', '#64748b'], ['ecmwf', '#0f766e']].forEach(function(s) {{
      var mm = d.members[s[0]]; if (!mm) return;
      mm.T.forEach(function(T, k) {{
        var cx = x(T), cy = y(mm.P[k]);
        g += s[0] === 'gefs' ? '<circle cx="' + cx + '" cy="' + cy + '" r="3.2" fill="' + s[1] + '" opacity=".8"/>'
          : '<path d="M' + cx + ' ' + (cy - 4) + 'l4 7h-8z" fill="' + s[1] + '" opacity=".8"/>';
      }});
    }});
    g += '<text x="' + S / 2 + '" y="' + (S - 6) + '" text-anchor="middle">temperature percentile (cold to warm)</text>' +
      '<text transform="translate(12,' + S / 2 + ') rotate(-90)" text-anchor="middle">precipitation percentile (dry to wet)</text>' +
      '<text x="' + m + '" y="' + (m - 6) + '">&#9679; GEFS  &#9650; ECMWF</text>';
    return '<svg viewBox="0 0 ' + S + ' ' + S + '" width="' + S + '" height="' + S + '" role="img" aria-label="Members by week-2 temperature and precipitation percentile">' + g + '</svg>';
  }}
  function trend(d) {{
    var W = 460, H = 300, ml = 40, mr = 22, mt = 34, mb = 46, ini = d.trend.init, n = ini.length;
    var top = Math.max(0.3, C.lv + 0.05);
    C.events.forEach(function(e) {{ (d.trend.odds[e] || []).forEach(function(v) {{ if (v !== null && v > top) top = v; }}); }});
    top = Math.min(1, Math.ceil(top * 10) / 10);
    function x(i) {{ return n < 2 ? (ml + W - mr) / 2 : ml + (W - ml - mr) * i / (n - 1); }}
    function y(v) {{ return H - mb - (H - mt - mb) * v / top; }}
    var g = '<rect class=ax x="' + ml + '" y="' + mt + '" width="' + (W - ml - mr) + '" height="' + (H - mt - mb) + '"/>' +
      '<line x1="' + ml + '" x2="' + (W - mr) + '" y1="' + y(C.lv) + '" y2="' + y(C.lv) + '" stroke="#64748b" stroke-dasharray="4 3"/>';
    for (var v = 0; v <= top + 1e-9; v += 0.1) g += '<text x="' + (ml - 5) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + Math.round(100 * v) + '%</text>';
    var step = Math.max(1, Math.ceil(n / 7));
    ini.forEach(function(s, i) {{ if ((n - 1 - i) % step === 0) g += '<text x="' + x(i) + '" y="' + (H - mb + 15) + '" text-anchor="middle">' + s.slice(5) + '</text>'; }});
    C.events.forEach(function(e, k) {{
      var o = d.trend.odds[e] || [], pts = [];
      o.forEach(function(v, i) {{ if (v !== null) pts.push(x(i) + ',' + y(v)); }});
      if (pts.length > 1) g += '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + C.col[e] + '" stroke-width="2"/>';
      o.forEach(function(v, i) {{ if (v !== null) g += '<circle cx="' + x(i) + '" cy="' + y(v) + '" r="2.6" fill="' + C.col[e] + '"/>'; }});
      g += '<rect x="' + (ml + 112 * (k % 4)) + '" y="' + (8 + 0) + '" width="10" height="10" fill="' + C.col[e] + '"/><text x="' + (ml + 14 + 112 * (k % 4)) + '" y="17">' + C.lab[e].split(' (')[0] + '</text>';
    }});
    g += '<text x="' + (ml + W - mr) / 2 + '" y="' + (H - 8) + '" text-anchor="middle">forecast start (dashed line: alert level)</text>';
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="Week-2 odds over recent runs">' + g + '</svg>';
  }}
  function members(d) {{
    var rows = [], w0 = C.w2[0], w1 = C.w2[1];
    ['gefs', 'ecmwf'].forEach(function(s) {{
      var m = d.members[s]; if (!m || !m.daily_P_mm) return;
      m.daily_P_mm.forEach(function(dd, k) {{
        var c = [], a = 0; dd.forEach(function(v) {{ a += v / 25.4; c.push(a); }});
        rows.push({{sys: s, k: k, cum: c, T: m.T[k], P: m.P[k], ev: m.events[k]}});
      }});
    }});
    if (!rows.length) return '';
    var nd = Math.max.apply(null, rows.map(function(r) {{ return r.cum.length; }})), key = Math.min(w1, nd) - 1;
    function at(r, i) {{ return r.cum[Math.min(i, r.cum.length - 1)]; }}
    rows.sort(function(a, b) {{ return at(b, key) - at(a, key); }});
    var t0 = new Date(d.init + 'T00:00:00Z'), hdr = '';
    for (var i = 0; i < nd; i++) {{
      var dt = new Date(t0.getTime() + 864e5 * i);
      hdr += '<th class="' + (i + 1 >= w0 && i + 1 <= w1 ? 'w2' : '') + '">' + dt.toLocaleDateString('en-US', {{weekday: 'short', timeZone: 'UTC'}}) +
        '<br>' + dt.toLocaleDateString('en-US', {{month: 'short', day: 'numeric', timeZone: 'UTC'}}) + '<br><small>day ' + (i + 1) + '</small></th>';
    }}
    function stat(label, f) {{
      var cells = '';
      for (var i = 0; i < nd; i++) {{
        var v = rows.filter(function(r) {{ return r.cum.length > i; }}).map(function(r) {{ return r.cum[i]; }}), x = f(v), c = pcol(x);
        cells += '<td style="background:' + c[0] + ';color:' + c[1] + '">' + fmt(x) + '</td>';
      }}
      return '<tr class=sum><th colspan=5>' + label + '</th>' + cells + '</tr>';
    }}
    var body = stat('Mean', function(v) {{ return v.reduce(function(a, b) {{ return a + b; }}, 0) / v.length; }}) +
      stat('Median', function(v) {{ v = v.slice().sort(function(a, b) {{ return a - b; }}); var h = v.length >> 1; return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2; }});
    rows.forEach(function(r) {{
      var fl = C.events.filter(function(e) {{ return r.ev.indexOf(e) >= 0; }});
      var chips = fl.map(function(e) {{ return '<span class=chip style="background:' + C.flag[e][1] + '">' + C.flag[e][0] + '</span>'; }}).join('');
      var edge = fl.length ? ' style="box-shadow:inset 4px 0 0 ' + C.flag[fl[0]][1] + '"' : '', cells = '';
      for (var i = 0; i < nd; i++) {{
        if (i >= r.cum.length) {{ cells += '<td class=na></td>'; continue; }}
        var c = pcol(r.cum[i]), ring = fl.length && i + 1 >= w0 && i + 1 <= w1 ? ';outline:2px solid ' + C.flag[fl[0]][1] + ';outline-offset:-2px' : '';
        cells += '<td style="background:' + c[0] + ';color:' + c[1] + ring + '">' + fmt(r.cum[i]) + '</td>';
      }}
      var tot = r.cum[r.cum.length - 1], ct = pcol(tot);
      var wk = r.cum[Math.min(w1, r.cum.length) - 1] - (w0 >= 2 ? r.cum[w0 - 2] : 0), cw = fl.length ? [C.flag[fl[0]][1], '#fff'] : pcol(wk);
      body += '<tr><th' + edge + '>' + r.sys.toUpperCase() + ' ' + (r.k + 1) + '</th><td style="background:' + cw[0] + ';color:' + cw[1] + '"><b>' + (fmt(wk) || '0') +
        '</b><br><small style="color:inherit;opacity:.85">' + pc(r.P) + '</small></td><td style="background:' + tcol(r.T) + '">' + pc(r.T) +
        '</td><td class=flags>' + chips + '</td><td style="background:' + ct[0] + ';color:' + ct[1] + '"><b>' + fmt(tot) + '</b></td>' + cells + '</tr>';
    }});
    var summ = C.events.map(function(e) {{
      var n = rows.filter(function(r) {{ return r.ev.indexOf(e) >= 0; }}).length;
      return '<span class=chip style="background:' + C.flag[e][1] + '">' + C.flag[e][0] + '</span> ' + C.lab[e] + ': ' + n + ' of ' + rows.length + ' members';
    }}).join(' · ');
    return '<h3>Members, day by day</h3><p class=mut>' + summ + '</p><div class=wrap><table class=plume><tr><th>Member</th><th>Wk-2 P<br><small>in / pctile</small></th>' +
      '<th>Wk-2 T<br><small>pctile</small></th><th>Flags</th><th>Total<br><small>in</small></th>' + hdr + '</tr>' + body + '</table></div>';
  }}
  function load(id) {{
    if (!C.units[id]) {{ box.innerHTML = '<p class=warn>That basin is not one of the forecast HUC8s.</p>'; return; }}
    pick.value = id;
    box.innerHTML = '<p class=mut>Loading...</p>';
    fetch(C.base + id + '.json').then(function(r) {{ if (!r.ok) throw new Error(r.status); return r.json(); }}).then(function(d) {{
      var tier = C.units[id].tier === '1' ? 'Holds an NRCS water supply forecast point and snow sites.' : 'Snow sites here feed a downstream NRCS forecast point.';
      box.innerHTML = '<h2>' + esc(d.name) + ' <small>HUC8 ' + id + '</small></h2><p class=mut>' + tier + '</p>' +
        '<h3>Week-2 odds</h3>' + oddsTable(d) + '<div class=two><div><h3>Members in their own model climate</h3>' + scatter(d) +
        '</div><div><h3>How the odds have moved</h3>' + trend(d) + '</div></div>' + members(d);
      document.getElementById('key').hidden = false;
      document.title = 'Sawtooth Lookout: ' + d.name;
    }}).catch(function() {{ box.innerHTML = '<p class=warn>No data for this basin on this start.</p>'; }});
  }}
  var b = new URLSearchParams(location.search).get('b');
  if (b) load(b);
}})();
</script>"""
    return Pg.shell(o, up, "Sawtooth Lookout: Idaho water-supply basins", body)

"""index.html and figures for the products folder."""
import html
import json

import numpy as np
import pandas as pd

from . import common as C

EV_LABEL = {"warm-dry": "Warm-dry (snow eater)", "dry": "Dry", "warm-wet": "Warm-wet (rain-on-snow)", "cold-wet": "Cold-wet", "wet": "Wet", "warm": "Warm",
            "cold": "Cold"}
COL = {"warm-dry": "#c2410c", "dry": "#b45309", "warm-wet": "#be185d", "cold-wet": "#1d4ed8"}


def figure(o, h, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(2, 5, figsize=(16, 6.6), gridspec_kw=dict(height_ratios=[1.15, 1]))
    t = C.A["tail"]
    for k, (bn, b) in enumerate(o["basins"].items()):
        ax = axs[0, k]
        ax.axhspan(0, t, color="#fde68a", alpha=.5, lw=0)
        ax.axhspan(1 - t, 1, color="#99f6e4", alpha=.6, lw=0)
        ax.axvspan(1 - t, 1, color="#fecaca", alpha=.5, lw=0)
        ax.axvspan(0, t, color="#bfdbfe", alpha=.5, lw=0)
        for s, mk, c in (("gefs", "o", "#334155"), ("ecmwf", "^", "#0f766e")):
            if s in b["members"]:
                m = b["members"][s]
                ax.scatter(m["T"], m["P"], s=16, marker=mk, color=c, alpha=.75, lw=0, label=s.upper())
        ax.set(xlim=(0, 1), ylim=(0, 1), title=b["name"], xlabel="temperature percentile")
        if k == 0:
            ax.set_ylabel("precipitation percentile")
            ax.legend(loc="upper left", bbox_to_anchor=(.1, .9), fontsize=8, frameon=False)
        ax.text(.98, .02, "warm", ha="right", va="bottom", fontsize=8, color="#991b1b")
        ax.text(.02, .02, "dry", ha="left", va="bottom", fontsize=8, color="#92400e")
        ax.text(.98, .98, "wet", ha="right", va="top", fontsize=8, color="#0f766e")
        ax.text(.02, .12, "cold", ha="left", va="bottom", fontsize=8, color="#1e40af")
        ax = axs[1, k]
        g = h[h.basin == bn].copy()
        g["init"] = pd.to_datetime(g.init)
        g = g[g.init > g.init.max() - pd.Timedelta(days=45)]
        for ev in C.A["events"]:
            e = g[g.event == ev]
            ax.plot(e.init, e.odds, "-o", ms=3, color=COL[ev], label=EV_LABEL[ev])
        ax.axhline(C.A["alert_odds"], color="#64748b", ls="--", lw=1)
        ax.set(ylim=(0, 1), xlabel="forecast start")
        ax.tick_params(axis="x", labelrotation=45, labelsize=7)
        if k == 0:
            ax.set_ylabel("week-2 odds (calibrated)")
            ax.legend(loc="upper left", fontsize=8, frameon=False)
    fig.suptitle(f"Week-2 members ({o['week2_dates'][0]} to {o['week2_dates'][1]}) in their own reforecast climate, "
                 f"start {o['init']}; shaded = beyond the 10th/90th percentile", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def cell(v, alerting, alert_ev):
    odds, base = v["odds"], v["base_rate"]
    if not np.isfinite(odds):
        return "<td class=na>n/a</td>"
    lvl = "hi" if odds >= C.A["alert_odds"] else ("mid" if odds >= 1.5 * base else "lo")
    if not (alerting and alert_ev):
        lvl += " muted"
    tip = f"GEFS share {v['share_gefs']:.0%}" + ("" if v["share_ecmwf"] is None else f", ECMWF share {v['share_ecmwf']:.0%}")
    return f"<td class='{lvl}' title='{html.escape(tip)}'><b>{odds:.0%}</b><span>vs {base:.0%}</span></td>"


def write(o, h, root=True):
    """Dated pages products/YYYYMMDD/ (index.html, basin/<key>.html) always; the root pages and figure only when
    `root` (newest start)."""
    p = C.PRODUCTS
    h = h[h.init <= o["init"]]
    day = p / o["init"].replace("-", "")
    day.mkdir(parents=True, exist_ok=True)
    figure(o, h, day / "alarms.png")
    copy_assets(p)
    if root:
        figure(o, h, p / "alarms.png")
    for where, up in ([(day, "../")] + ([(p, "")] if root else [])):
        (where / "index.html").write_text(render(o, h, up))
        (where / "basin").mkdir(exist_ok=True)
        for bn in o["basins"]:
            (where / "basin" / f"{bn}.html").write_text(render_basin(o, h, bn, up + "../"))
    write_archive(h)


def copy_assets(p):
    """Leaflet and the map layers, at the products root (shared by every day's pages)."""
    import shutil
    shutil.copytree(C.HERE / "vendor" / "leaflet", p / "vendor" / "leaflet", dirs_exist_ok=True)
    shutil.copytree(C.STATIC / "map", p / "map", dirs_exist_ok=True)


def shell(o, up, title, body, head_extra=""):
    sysline = ", ".join(f"{k.upper()} {v} members" for k, v in o["systems"].items())
    note = "" if o["alerting"] else (f"<p class=warn>{o['season']} is outside the alerting season "
                                     "(Nov-Feb); odds are shown for reference.</p>")
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
{head_extra}<style>
:root{{--bg:#fff;--fg:#0f172a;--mut:#64748b;--hi:#fee2e2;--hib:#b91c1c;--mid:#fef3c7;--lo:#f8fafc;--line:#e2e8f0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--fg:#e2e8f0;--mut:#94a3b8;--hi:#4c1d1d;--hib:#fca5a5;--mid:#3f3413;--lo:#111827;--line:#1f2937}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}}
table{{border-collapse:collapse;margin:8px 0 16px;width:100%}} th,td{{border:1px solid var(--line);padding:6px 8px;text-align:center}}
th{{font-weight:600}} td b{{display:block;font-size:17px}} td span{{color:var(--mut);font-size:12px}}
td.hi{{background:var(--hi)}} td.hi b{{color:var(--hib)}} td.mid{{background:var(--mid)}} td.lo{{background:var(--lo)}}
td.muted{{opacity:.6}} .mut,small{{color:var(--mut)}} .warn{{color:var(--hib)}} img{{max-width:100%}}
.wrap{{overflow-x:auto}} {TREND_CSS} .disc{{border:1px solid var(--hib);border-radius:6px;padding:8px 10px}} a{{color:inherit}}
{PLUME_CSS}{MAP_CSS}
</style></head><body>
<h1><a href="{up or './'}" style="text-decoration:none">Sawtooth Lookout</a></h1>
<p class=mut>Week-2 snow-drought early warning for Idaho basins · Boise State University</p>
<p class=disc><b>Experimental research product. Not an official forecast.</b> For official forecasts and warnings, see the <a href="https://www.weather.gov/">National Weather Service</a>. Provided as is, without warranty.</p>
<p>Start <b>{o['init']}</b> 00 UTC ({sysline}). Week 2 = <b>{o['week2_dates'][0]} to {o['week2_dates'][1]}</b>.</p>
{note}{body}
<p class=mut>&copy; 2026 Lejo Flores and Boise State University. Products licensed
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; code (Apache 2.0) at
<a href="https://github.com/LejoFlores/sawtooth-lookout">github.com/LejoFlores/sawtooth-lookout</a>.</p>
<p class=mut><a href="{up}archive.html">Past days</a> · <a href="{up}history.csv">history.csv</a> ·
<a href="{up}latest.json">latest.json</a></p>
</body></html>"""


def odds_table(o, basins, link=True):
    evs = C.A["events"] + C.A["watch_events"]
    head = "".join(f"<th>{EV_LABEL[e]}{'' if e in C.A['events'] else '<br><small>(watch only)</small>'}</th>" for e in evs)
    rows = "".join(f"<tr><th>{(f'<a href=' + chr(39) + f'basin/{bn}.html' + chr(39) + '>' + html.escape(b['name']) + '</a>') if link else html.escape(b['name'])}</th>" +
                   "".join(cell(b["week2"][e], o["alerting"], e in C.A["events"]) for e in evs) + "</tr>"
                   for bn, b in o["basins"].items() if bn in basins)
    return f"<div class=wrap><table><tr><th>Basin</th>{head}</tr>{rows}</table></div>"


ODDS_NOTE = ("<p class=mut>Calibrated odds that the week ends in the tail of basin climate (driest, warm-and-driest or "
             "cold-and-wettest 10%), against the usual rate. Red: at or above the {lvl:.0%} alert level. Amber: at least "
             "1.5 times the usual rate. Hover for each model's raw member share.</p>")


def render_basin(o, h, bn, up):
    b = o["basins"][bn]
    body = (f"<p><a href='../'>&larr; Map and all basins</a></p><h2>{html.escape(b['name'])}</h2>"
            f"<h3>Week-2 odds</h3>{ODDS_NOTE.format(lvl=C.A['alert_odds'])}{odds_table(o, [bn], link=False)}"
            f"{trend_section(o, h, [bn]).replace('<h2>', '<h3>').replace('</h2>', '</h3>')}"
            f"{plume_section(o, [bn])}")
    return shell(o, up, f"Sawtooth Lookout: {b['name']}", body)


def render(o, h, up):
    frows = "".join(f"<tr><th>{html.escape(b['name'])}</th>" +
                    "".join(f"<td>{b['fortnight_gefs'][e]['odds']:.0%}</td>" for e in C.A["events"]) + "</tr>"
                    for b in o["basins"].values())
    alerts = ("<ul>" + "".join(f"<li><a href='basin/{a['basin']}.html'><b>{html.escape(C.CFG['basins'][a['basin']])}</b></a>: "
                               f"{EV_LABEL[a['event']]} week 2, odds {a['odds']:.0%}</li>" for a in o["alerts"]) + "</ul>") \
        if o["alerts"] else "<p>No alerts.</p>"
    west = (f"<p><a href='{up}west/'>West-wide map: the same signals on large river subregions &rarr;</a></p>"
            if (C.STATIC / "west_calibration.csv").exists() else "")
    body = f"""<h2>Alerts</h2>{alerts}
{map_section(o, h, up)}{west}
<h2>Week-2 odds</h2>
{ODDS_NOTE.format(lvl=C.A['alert_odds'])}
{odds_table(o, list(o['basins']))}
{trend_section(o, h)}
<img src="alarms.png" alt="Member percentiles and recent odds by basin">
<h2>Days 8-21 (GEFS only, heads-up)</h2>
<p class=mut>ECMWF open data stops at day 15, so the fortnight uses GEFS alone. Its hindcast skill is lower; it never alerts.</p>
<div class=wrap><table><tr><th>Basin</th>{''.join(f'<th>{EV_LABEL[e]}</th>' for e in C.A['events'])}</tr>{frows}</table></div>
<h2>How this works</h2>
<p class=mut>Each member's basin-mean week-2 temperature and precipitation is ranked within its own model's reforecast
climate (GEFSv12 2000-2019, ECMWF 2006-2025, starts within 21 days of the date). The share of members in the tail,
GEFS and ECMWF half each, is turned into odds with a logistic fit to the 2000-2025 hindcast for the season.
Nov-Feb hindcast at the 15% alert level: about 2.5-5 alerts a winter per basin, right 22-29% of the time against a
9-13% base rate, catching about half to two-thirds of events. Warm-wet (rain-on-snow) is the weakest in winter
and strongest in March-April. The member-by-member tables are on each basin's page.
Truth: PRISM Climate Group, Oregon State University (basin means). Forecast data: NOAA GEFS via dynamical.org;
ECMWF open data, &copy; ECMWF, CC BY 4.0 (reduced here to basin statistics). Basin boundaries: USGS Watershed
Boundary Dataset. State outline: US Census via us-atlas.</p>"""
    return shell(o, up, "Sawtooth Lookout", body,
                 f"<link rel=stylesheet href='{up}vendor/leaflet/leaflet.css'><script src='{up}vendor/leaflet/leaflet.js'></script>")


# ------------------------------------------------------------------------------------- member plume tables (per basin)
# Running-total precipitation by member and day, in inches, coloured on a fixed scale; members in an alarm tail in
# week 2 carry a coloured flag and outline.
PSCALE = [(0.01, "T", "#d4d4d8", "#18181b"), (0.1, ".01", "#f7f7b5", "#18181b"), (0.3, ".1", "#d6ecaa", "#18181b"),
          (0.5, ".3", "#a6dcb4", "#18181b"), (1.0, ".5", "#73c6bd", "#18181b"), (1.5, "1", "#4ba9c6", "#fff"),
          (2.0, "1.5", "#3a86c8", "#fff"), (3.0, "2", "#3561c4", "#fff"), (4.0, "3", "#4f3fc6", "#fff"),
          (5.0, "4", "#6d2fb4", "#fff"), (6.0, "5", "#86218f", "#fff"), (8.0, "6", "#6d1659", "#fff"),
          (1e9, "8+", "#450a2c", "#fff")]
FLAG = {"warm-dry": ("WD", "#ea580c"), "dry": ("D", "#ca8a04"), "warm-wet": ("WW", "#db2777"), "cold-wet": ("CW", "#2563eb")}


def _pcol(v):
    if v < 0.005:
        return "", ""
    for hi, _, bg, fg in PSCALE:
        if v < hi:
            return bg, fg
    return PSCALE[-1][2], PSCALE[-1][3]


def _fmt(v):
    if v < 0.005:
        return ""
    if v < 0.05:
        return "T"
    s = f"{v:.1f}"
    return s[1:] if s.startswith("0.") else s


def _tcol(p):
    """Week-2 temperature percentile -> diverging blue/red."""
    if p is None or not np.isfinite(p):
        return ""
    x = 2 * p - 1
    if x >= 0:
        return f"rgba(220,38,38,{0.75 * x:.2f})"
    return f"rgba(37,99,235,{-0.75 * x:.2f})"


def plume_table(o, bn):
    b = o["basins"][bn]
    t0 = pd.Timestamp(o["init"])
    w0, w1 = C.A["week2"]
    rows = []
    for sys_, m in b["members"].items():
        if "daily_P_mm" not in m:
            continue
        for k, d in enumerate(m["daily_P_mm"]):
            cum = np.cumsum(np.asarray(d) / 25.4)
            rows.append(dict(sys=sys_, k=k, cum=cum, T=m["T"][k], P=m["P"][k], ev=m["events"][k]))
    if not rows:
        return ""
    ndays = max(len(r["cum"]) for r in rows)
    key = min(w1, ndays) - 1
    rows.sort(key=lambda r: -r["cum"][min(key, len(r["cum"]) - 1)])
    days = [t0 + pd.Timedelta(days=i) for i in range(ndays)]
    hdr = "".join(f"<th class='{'w2' if w0 <= i + 1 <= w1 else ''}'>{d:%a}<br>{d:%b %-d}<br><small>day {i + 1}</small></th>"
                  for i, d in enumerate(days))

    def stat_row(label, f):
        cells = []
        for i in range(ndays):
            v = [r["cum"][i] for r in rows if len(r["cum"]) > i]
            x = f(np.array(v))
            if label.startswith("%"):
                cells.append(f"<td class=stat>{x:.0f}</td>")
            else:
                bg, fg = _pcol(x)
                cells.append(f"<td style='background:{bg};color:{fg}'>{_fmt(x)}</td>")
        return f"<tr class=sum><th colspan=5>{label}</th>{''.join(cells)}</tr>"
    body = [stat_row("Mean", np.mean), stat_row("Median", np.median),
            stat_row("% members with 0.1 in+", lambda v: 100 * np.mean(v >= 0.1))]
    for r in rows:
        alert_ev = [e for e in FLAG if e in r["ev"]]          # warm-dry colour wins over dry
        chips = "".join(f"<span class=chip style='background:{FLAG[e][1]}'>{FLAG[e][0]}</span>" for e in alert_ev)
        edge = f" style='box-shadow:inset 4px 0 0 {FLAG[alert_ev[0]][1]}'" if alert_ev else ""
        cells = []
        for i in range(ndays):
            if i >= len(r["cum"]):
                cells.append("<td class=na></td>")
                continue
            bg, fg = _pcol(r["cum"][i])
            ring = (f";outline:2px solid {FLAG[alert_ev[0]][1]};outline-offset:-2px"
                    if alert_ev and w0 <= i + 1 <= w1 else "")
            cells.append(f"<td style='background:{bg};color:{fg}{ring}'>{_fmt(r['cum'][i])}</td>")
        tot = r["cum"][-1]
        bg, fg = _pcol(tot)
        c = r["cum"]
        wk = c[min(w1, len(c)) - 1] - (c[w0 - 2] if w0 >= 2 else 0.0)                   # week-2 total (in)
        wbg, wfg = (FLAG[alert_ev[0]][1], "#fff") if alert_ev else _pcol(wk)              # flagged: the flag colour
        rows_html = (f"<tr><th{edge}>{r['sys'].upper()} {r['k'] + 1}</th>"
                     f"<td style='background:{wbg};color:{wfg}'><b>{_fmt(wk) or '0'}</b><br><small style='color:inherit;opacity:.85'>{r['P']:.0%}</small></td>"
                     f"<td style='background:{_tcol(r['T'])}'>{r['T']:.0%}</td>"
                     f"<td class=flags>{chips}</td>"
                     f"<td style='background:{bg};color:{fg}'><b>{_fmt(tot)}</b></td>{''.join(cells)}</tr>")
        body.append(rows_html)
    nflag = {e: sum(e in r["ev"] for r in rows) for e in FLAG}
    summ = " · ".join(f"<span class=chip style='background:{FLAG[e][1]}'>{FLAG[e][0]}</span> {EV_LABEL[e]}: "
                      f"{n} of {len(rows)} members" for e, n in nflag.items())
    return (f"<section id='plume-{bn}'><h3>{html.escape(b['name'])}</h3><p class=mut>{summ}</p>"
            f"<div class=wrap><table class=plume><tr><th>Member</th><th>Wk-2 P<br><small>in / pctile</small></th>"
            f"<th>Wk-2 T<br><small>pctile</small></th><th>Flags</th><th>Total<br><small>in</small></th>{hdr}</tr>"
            f"{''.join(body)}</table></div></section>")


PLUME_CSS = """
table.plume{width:auto;font:12px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace}
table.plume th,table.plume td{padding:2px 6px;min-width:34px;white-space:nowrap}
table.plume th.w2{background:var(--mid)} table.plume tr.sum th,table.plume td.stat{background:var(--lo);font-weight:600}
table.plume td.na{background:var(--bg)} .chip{display:inline-block;border-radius:3px;color:#fff;font-size:10px;
padding:0 4px;margin-right:2px;font-weight:700} .key span{display:inline-block;padding:1px 6px;font:11px ui-monospace,monospace}
.basins a{margin-right:12px}
"""


def plume_section(o, basins=None):
    basins = list(o["basins"]) if basins is None else basins
    secs = "".join(plume_table(o, bn) for bn in basins)
    if not secs:
        return ""
    key = "".join(f"<span style='background:{bg};color:{fg}'>{lab}</span>" for _, lab, bg, fg in PSCALE)
    nav = "".join(f"<a href='#plume-{bn}'>{html.escape(o['basins'][bn]['name'])}</a>" for bn in basins) \
        if len(basins) > 1 else ""
    return (f"<h2>Members, day by day</h2><p class=mut>Running basin-mean precipitation total (inches) from the start, "
            f"one row per member, wettest first by the end of week 2. Week 2 is shaded in the header. Flags mark "
            f"members whose week 2 is in an alarm tail of their own model's climate, and their week-2 cells are "
            f"outlined: <b>WD</b> warm-dry, <b>D</b> dry, <b>WW</b> warm-wet, <b>CW</b> cold-wet. Wk-2 P is the member's days 8-14 "
            f"precipitation (inches) and its percentile in its own model's climate, in the flag colour when flagged; Wk-2 T is its week-2 temperature "
            f"percentile. Flags depend on week 2 only. ECMWF members stop at day 15, so their Total covers 15 days, "
            f"not 21.</p><p class=key>Colour key (in): {key}</p>"
            f"<p class=basins>{nav}</p>{secs}")


# ---------------------------------------------------------------------------------------- how the odds are changing
TREND_RUNS = 7
STEP = 0.03          # a change smaller than this (3 points) counts as steady

TREND_CSS = """table.trend td{font-variant-numeric:tabular-nums} td.up{color:var(--hib);font-weight:700}
td.down{color:#2563eb;font-weight:700} ul.moves li{margin:2px 0}"""


def _arrow(d):
    if not np.isfinite(d) or abs(d) < STEP:
        return "steady", "–"
    return ("up", "▲") if d > 0 else ("down", "▼")


def moves(h, init):
    """Plain-language lines for alerting events whose odds crossed the alert level or moved 3 runs in a row."""
    out = []
    lvl = C.A["alert_odds"]
    for (bn, ev), g in h[h.event.isin(C.A["events"])].groupby(["basin", "event"]):
        g = g.sort_values("init")
        g = g[g.init <= init].tail(4)
        if len(g) < 2 or g.init.iloc[-1] != init:
            continue
        x = g.odds.to_numpy()
        name = f"{C.CFG['basins'][bn]}, {EV_LABEL[ev].lower()}"
        path = " → ".join(f"{v:.0%}" for v in x[-3:])
        if x[-1] >= lvl > x[-2]:
            out.append((3, f"<b>{name}</b> crossed the {lvl:.0%} alert level: {path}"))
        elif x[-2] >= lvl > x[-1]:
            out.append((2, f"<b>{name}</b> fell below the alert level: {path}"))
        elif len(x) >= 3 and np.all(np.diff(x[-3:]) >= STEP):
            out.append((1, f"<b>{name}</b> rising for two runs: {path}"))
        elif len(x) >= 3 and np.all(np.diff(x[-3:]) <= -STEP) and x[-3] >= lvl / 2:
            out.append((0, f"<b>{name}</b> falling for two runs: {path}"))
    return [t for _, t in sorted(out, key=lambda z: -z[0])]


def trend_section(o, h, basins=None):
    h = h if basins is None else h[h.basin.isin(basins)]
    inits = sorted(h.init.unique())[-TREND_RUNS:]
    if len(inits) < 2:
        return ("<h2>How the odds are changing</h2><p class=mut>The trend starts with the next run.</p>")
    hd = "".join(f"<th>{pd.Timestamp(i):%b %-d}</th>" for i in inits)
    rows = []
    for bn, b in o["basins"].items():
        if basins is not None and bn not in basins:
            continue
        for k, ev in enumerate(C.A["events"]):
            g = h[(h.basin == bn) & (h.event == ev)].set_index("init").odds
            vals = [g.get(i, np.nan) for i in inits]
            cells = "".join("<td class=na>·</td>" if not np.isfinite(v) else
                            f"<td class='{'hi' if v >= C.A['alert_odds'] else 'lo'}'>{v:.0%}</td>" for v in vals)
            d = vals[-1] - vals[-2] if len(vals) > 1 else np.nan
            cls, arr = _arrow(d)
            if np.isfinite(d):                                     # NaN when an event is newer than the history
                txt = f"{arr} {abs(d) * 100:.0f}" if cls != "steady" else (f"{d * 100:+.0f}" if round(d * 100) else "0")
                chg = f"<td class={cls}>{txt}</td>"
            else:
                chg = "<td class=na></td>"
            lead = f"<th rowspan={len(C.A['events'])}>{html.escape(b['name'])}</th>" if k == 0 else ""
            rows.append(f"<tr>{lead}<th>{EV_LABEL[ev]}</th>{cells}{chg}</tr>")
    mv = moves(h, o["init"])
    mvh = ("<ul class=moves>" + "".join(f"<li>{m}</li>" for m in mv) + "</ul>") if mv else \
        "<p>No alert-level crossings or steady rises in the latest runs.</p>"
    return (f"<h2>How the odds are changing</h2>{mvh}<p class=mut>Week-2 odds from the last {len(inits)} daily runs. "
            f"Each run's week 2 is a different week (the window slides a day per run), so this shows whether the "
            f"forecasts keep pointing at a tail event, not the odds for one fixed week. Change is from the previous "
            f"run, in percentage points.</p><div class=wrap><table class=trend><tr><th>Basin</th><th>Event</th>{hd}"
            f"<th>Change</th></tr>{''.join(rows)}</table></div>")


def write_archive(h):
    p = C.PRODUCTS
    rows = []
    for init in sorted(h.init.unique(), reverse=True):
        g = h[(h.init == init) & h.alert.astype(bool)]
        al = ", ".join(f"{C.CFG['basins'][r.basin]} {EV_LABEL[r.event].lower()} {r.odds:.0%}" for r in g.itertuples())
        d = init.replace("-", "")
        link = f"<a href='{d}/'>{init}</a>" if (p / d / "index.html").exists() else init
        rows.append(f"<tr><td>{link}</td><td style='text-align:left'>{html.escape(al) or 'none'}</td></tr>")
    (p / "archive.html").write_text(
        "<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
        "initial-scale=1'><title>Sawtooth Lookout archive</title><style>body{font:15px/1.45 system-ui,sans-serif;"
        "margin:0 auto;max-width:900px;padding:16px} table{border-collapse:collapse;width:100%} td,th{border:1px "
        "solid #e2e8f0;padding:6px 8px} @media (prefers-color-scheme:dark){body{background:#0b1220;color:#e2e8f0}"
        "a{color:#93c5fd} td,th{border-color:#1f2937}}</style></head><body><h1><a href='./'>Sawtooth Lookout</a>"
        " archive</h1><p><b>Experimental research product. Not an official forecast.</b></p><table><tr><th>Start"
        "</th><th>Alerts (week-2 odds)</th></tr>" + "".join(rows) + "</table></body></html>")


# ------------------------------------------------------------------------------------------------------------- map
MAP_CSS = """
#map{height:560px;border:1px solid var(--line);border-radius:6px;margin:8px 0 4px}
.legend span{display:inline-block;width:12px;height:12px;border-radius:2px;margin:0 4px 0 12px;vertical-align:-1px}
.leaflet-tooltip{font:13px/1.35 system-ui,sans-serif}
"""
LEVEL = {"hi": ("#dc2626", "at or above the alert level"), "mid": ("#f59e0b", "elevated (1.5x usual or more)"),
         "lo": ("#0f766e", "near normal")}


def basin_status(o, h):
    """Per active basin: map level, tooltip lines (odds and change from the previous run)."""
    prev = h[h.init < o["init"]].sort_values("init").groupby(["basin", "event"]).odds.last()
    out = {}
    for bn, b in o["basins"].items():
        lv = "lo"
        lines = []
        for ev in C.A["events"]:
            v = b["week2"][ev]
            if v["odds"] >= C.A["alert_odds"]:
                lv = "hi"
            elif v["odds"] >= 1.5 * v["base_rate"] and lv == "lo":
                lv = "mid"
            d = v["odds"] - prev.get((bn, ev), np.nan)
            arr = "" if not np.isfinite(d) else (" ▲" if d >= STEP else (" ▼" if d <= -STEP else ""))
            lines.append(f"{EV_LABEL[ev]}: {v['odds']:.0%}{arr}")
        out[bn] = dict(level=lv, color=LEVEL[lv][0], name=b["name"], lines=lines)
    return out


def map_section(o, h, up):
    st = json.dumps(basin_status(o, h))
    legend = "".join(f"<span style='background:{c}'></span>{t}" for c, t in LEVEL.values()) + \
        "<span style='background:#cbd5e1'></span>coming soon"
    return f"""<h2>Basins</h2>
<p class=mut>Shaded by the highest week-2 odds among the alerting events. Click a basin for its odds trend and
member-by-member table. Grey basins are not forecast yet: coming soon.</p>
<div id=map></div><p class="mut legend">{legend}</p>
<script>
(function(){{
  if (!window.L) return;
  var S = {st}, up = {json.dumps(up)};
  var dark = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches;
  var m = L.map('map', {{scrollWheelZoom: false, zoomSnap: 0.25}}).setView([45.0, -114.6], 6);
  // USGS National Map: public, no API key. The page works without it if the tiles fail to load.
  L.tileLayer('https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{maxZoom: 10, opacity: dark ? 0.75 : 1, attribution: 'Basemap: USGS The National Map'}}).addTo(m);
  function get(u) {{ return fetch(up + u).then(function(r) {{ return r.json(); }}); }}
  Promise.all([get('map/others.geojson'), get('map/idaho.geojson'), get('map/active.geojson')]).then(function(g) {{
    L.geoJSON(g[0], {{style: {{color: '#94a3b8', weight: 0.7, fillColor: '#cbd5e1', fillOpacity: 0.35, dashArray: '3'}},
      onEachFeature: function(f, l) {{ l.bindTooltip('<b>' + f.properties.name + '</b><br>Coming soon', {{sticky: true}}); }}
    }}).addTo(m);
    L.geoJSON(g[1], {{style: {{color: dark ? '#e2e8f0' : '#0f172a', weight: 2, fill: false}}, interactive: false}}).addTo(m);
    var act = L.geoJSON(g[2], {{
      style: function(f) {{ var s = S[f.properties.basin]; return {{color: '#0f172a', weight: 1.5, fillColor: s.color, fillOpacity: 0.55}}; }},
      onEachFeature: function(f, l) {{
        var s = S[f.properties.basin];
        l.bindTooltip('<b>' + s.name + '</b><br>' + s.lines.join('<br>') + '<br><i>Click for details</i>', {{sticky: true}});
        l.on('click', function() {{ location.href = 'basin/' + f.properties.basin + '.html'; }});
        l.on('mouseover', function() {{ l.setStyle({{weight: 3}}); }});
        l.on('mouseout', function() {{ l.setStyle({{weight: 1.5}}); }});
      }}
    }}).addTo(m);
    m.fitBounds(L.geoJSON(g[1]).getBounds(), {{padding: [4, 4]}});
  }});
}})();
</script>"""

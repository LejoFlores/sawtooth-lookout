"""index.html and figures for the products folder."""
import html

import numpy as np
import pandas as pd

from . import common as C

EV_LABEL = {"warm-dry": "Warm-dry (snow eater)", "dry": "Dry", "cold-wet": "Cold-wet", "wet": "Wet", "warm": "Warm",
            "cold": "Cold"}
COL = {"warm-dry": "#c2410c", "dry": "#b45309", "cold-wet": "#1d4ed8"}


def figure(o, h, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(2, 5, figsize=(16, 6.6), gridspec_kw=dict(height_ratios=[1.15, 1]))
    t = C.A["tail"]
    for k, (bn, b) in enumerate(o["basins"].items()):
        ax = axs[0, k]
        ax.axhspan(0, t, color="#fde68a", alpha=.5, lw=0)
        ax.axvspan(1 - t, 1, color="#fecaca", alpha=.5, lw=0)
        ax.axvspan(0, t, color="#bfdbfe", alpha=.5, lw=0)
        for s, mk, c in (("gefs", "o", "#334155"), ("ecmwf", "^", "#0f766e")):
            if s in b["members"]:
                m = b["members"][s]
                ax.scatter(m["T"], m["P"], s=16, marker=mk, color=c, alpha=.75, lw=0, label=s.upper())
        ax.set(xlim=(0, 1), ylim=(0, 1), title=b["name"], xlabel="temperature percentile")
        if k == 0:
            ax.set_ylabel("precipitation percentile")
            ax.legend(loc="upper left", fontsize=8, frameon=False)
        ax.text(.98, .02, "warm", ha="right", va="bottom", fontsize=8, color="#991b1b")
        ax.text(.02, .02, "dry", ha="left", va="bottom", fontsize=8, color="#92400e")
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


def write(o, h):
    p = C.PRODUCTS
    figure(o, h, p / f"{o['init'].replace('-', '')}" / "alarms.png")
    figure(o, h, p / "alarms.png")
    evs = C.A["events"] + C.A["watch_events"]
    head = "".join(f"<th>{EV_LABEL[e]}{'' if e in C.A['events'] else '<br><small>(watch only)</small>'}</th>" for e in evs)
    rows = "".join(f"<tr><th>{html.escape(b['name'])}</th>" +
                   "".join(cell(b["week2"][e], o["alerting"], e in C.A["events"]) for e in evs) + "</tr>"
                   for b in o["basins"].values())
    frows = "".join(f"<tr><th>{html.escape(b['name'])}</th>" +
                    "".join(f"<td>{b['fortnight_gefs'][e]['odds']:.0%}</td>" for e in C.A["events"]) + "</tr>"
                    for b in o["basins"].values())
    alerts = ("<ul>" + "".join(f"<li><b>{html.escape(C.CFG['basins'][a['basin']])}</b>: {EV_LABEL[a['event']]} "
                               f"week 2, odds {a['odds']:.0%}</li>" for a in o["alerts"]) + "</ul>") if o["alerts"] \
        else "<p>No alerts.</p>"
    sysline = ", ".join(f"{k.upper()} {v} members" for k, v in o["systems"].items())
    note = "" if o["alerting"] else (f"<p class=warn>{o['season']} is outside the alerting season "
                                     "(Nov-Feb); odds are shown for reference.</p>")
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Sawtooth Lookout</title>
<style>
:root{{--bg:#fff;--fg:#0f172a;--mut:#64748b;--hi:#fee2e2;--hib:#b91c1c;--mid:#fef3c7;--lo:#f8fafc;--line:#e2e8f0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--fg:#e2e8f0;--mut:#94a3b8;--hi:#4c1d1d;--hib:#fca5a5;--mid:#3f3413;--lo:#111827;--line:#1f2937}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}}
table{{border-collapse:collapse;margin:8px 0 16px;width:100%}} th,td{{border:1px solid var(--line);padding:6px 8px;text-align:center}}
th{{font-weight:600}} td b{{display:block;font-size:17px}} td span{{color:var(--mut);font-size:12px}}
td.hi{{background:var(--hi)}} td.hi b{{color:var(--hib)}} td.mid{{background:var(--mid)}} td.lo{{background:var(--lo)}}
td.muted{{opacity:.6}} .mut,small{{color:var(--mut)}} .warn{{color:var(--hib)}} img{{max-width:100%}}
.wrap{{overflow-x:auto}} .disc{{border:1px solid var(--hib);border-radius:6px;padding:8px 10px}} a{{color:inherit}}
{PLUME_CSS}
</style></head><body>
<h1>Sawtooth Lookout</h1>
<p class=mut>Week-2 snow-drought early warning for Idaho basins · Boise State University</p>
<p class=disc><b>Experimental research product. Not an official forecast.</b> For official forecasts and warnings, see the <a href="https://www.weather.gov/">National Weather Service</a>. Provided as is, without warranty.</p>
<p>Start <b>{o['init']}</b> 00 UTC ({sysline}). Week 2 = <b>{o['week2_dates'][0]} to {o['week2_dates'][1]}</b>.</p>
{note}<h2>Alerts</h2>{alerts}
<h2>Week-2 odds</h2>
<p class=mut>Calibrated odds that the week ends in the tail of basin climate (driest, warm-and-driest or cold-and-wettest
10%), against the usual rate. Red: at or above the {C.A['alert_odds']:.0%} alert level. Amber: at least 1.5 times the usual
rate. Hover for each model's raw member share.</p>
<div class=wrap><table><tr><th>Basin</th>{head}</tr>{rows}</table></div>
<img src="alarms.png" alt="Member percentiles and recent odds by basin">
{plume_section(o)}
<h2>Days 8-21 (GEFS only, heads-up)</h2>
<p class=mut>ECMWF open data stops at day 15, so the fortnight uses GEFS alone. Its hindcast skill is lower; it never alerts.</p>
<div class=wrap><table><tr><th>Basin</th>{''.join(f'<th>{EV_LABEL[e]}</th>' for e in C.A['events'])}</tr>{frows}</table></div>
<h2>How this works</h2>
<p class=mut>Each member's basin-mean week-2 temperature and precipitation is ranked within its own model's reforecast
climate (GEFSv12 2000-2019, ECMWF 2006-2025, starts within 21 days of the date). The share of members in the tail,
GEFS and ECMWF half each, is turned into odds with a logistic fit to the 2000-2025 hindcast for the season.
Nov-Feb hindcast at the 15% alert level: about 2.5-5 alerts a winter per basin, right 24-29% of the time against a
9-13% base rate, catching about half to two-thirds of events.
Truth: PRISM Climate Group, Oregon State University (basin means). Forecast data: NOAA GEFS via dynamical.org;
ECMWF open data, &copy; ECMWF, CC BY 4.0 (reduced here to basin statistics).</p>
<p class=mut>&copy; 2026 Lejo Flores and Boise State University. Products licensed
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; code (Apache 2.0) at
<a href="https://github.com/LejoFlores/sawtooth-lookout">github.com/LejoFlores/sawtooth-lookout</a>.</p>
<p class=mut><a href="history.csv">history.csv</a> · <a href="latest.json">latest.json</a></p>
</body></html>"""
    (p / "index.html").write_text(page)


# ------------------------------------------------------------------------------------- member plume tables (per basin)
# Running-total precipitation by member and day, in inches, coloured on a fixed scale; members in an alarm tail in
# week 2 carry a coloured flag and outline.
PSCALE = [(0.01, "T", "#d4d4d8", "#18181b"), (0.1, ".01", "#f7f7b5", "#18181b"), (0.3, ".1", "#d6ecaa", "#18181b"),
          (0.5, ".3", "#a6dcb4", "#18181b"), (1.0, ".5", "#73c6bd", "#18181b"), (1.5, "1", "#4ba9c6", "#fff"),
          (2.0, "1.5", "#3a86c8", "#fff"), (3.0, "2", "#3561c4", "#fff"), (4.0, "3", "#4f3fc6", "#fff"),
          (5.0, "4", "#6d2fb4", "#fff"), (6.0, "5", "#86218f", "#fff"), (8.0, "6", "#6d1659", "#fff"),
          (1e9, "8+", "#450a2c", "#fff")]
FLAG = {"warm-dry": ("WD", "#ea580c"), "dry": ("D", "#ca8a04"), "cold-wet": ("CW", "#2563eb")}


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
        return f"<tr class=sum><th colspan=4>{label}</th>{''.join(cells)}</tr>"
    body = [stat_row("Mean", np.mean), stat_row("Median", np.median),
            stat_row("% members with 0.1 in+", lambda v: 100 * np.mean(v >= 0.1))]
    for r in rows:
        alert_ev = [e for e in r["ev"] if e in FLAG]
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
        rows_html = (f"<tr><th{edge}>{r['sys'].upper()} {r['k'] + 1}</th>"
                     f"<td style='background:{bg};color:{fg}'><b>{_fmt(tot)}</b></td>"
                     f"<td style='background:{_tcol(r['T'])}'>{r['T']:.0%}</td>"
                     f"<td class=flags>{chips}</td>{''.join(cells)}</tr>")
        body.append(rows_html)
    nflag = {e: sum(e in r["ev"] for r in rows) for e in FLAG}
    summ = " · ".join(f"<span class=chip style='background:{FLAG[e][1]}'>{FLAG[e][0]}</span> {EV_LABEL[e]}: "
                      f"{n} of {len(rows)} members" for e, n in nflag.items())
    return (f"<section id='plume-{bn}'><h3>{html.escape(b['name'])}</h3><p class=mut>{summ}</p>"
            f"<div class=wrap><table class=plume><tr><th>Member</th><th>Total<br><small>in</small></th>"
            f"<th>Wk-2 T<br><small>pctile</small></th><th>Flags</th>{hdr}</tr>{''.join(body)}</table></div></section>")


PLUME_CSS = """
table.plume{width:auto;font:12px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace}
table.plume th,table.plume td{padding:2px 6px;min-width:34px;white-space:nowrap}
table.plume th.w2{background:var(--mid)} table.plume tr.sum th,table.plume td.stat{background:var(--lo);font-weight:600}
table.plume td.na{background:var(--bg)} .chip{display:inline-block;border-radius:3px;color:#fff;font-size:10px;
padding:0 4px;margin-right:2px;font-weight:700} .key span{display:inline-block;padding:1px 6px;font:11px ui-monospace,monospace}
.basins a{margin-right:12px}
"""


def plume_section(o):
    secs = "".join(plume_table(o, bn) for bn in o["basins"])
    if not secs:
        return ""
    key = "".join(f"<span style='background:{bg};color:{fg}'>{lab}</span>" for _, lab, bg, fg in PSCALE)
    nav = "".join(f"<a href='#plume-{bn}'>{html.escape(b['name'])}</a>" for bn, b in o["basins"].items())
    return (f"<h2>Members, day by day</h2><p class=mut>Running basin-mean precipitation total (inches) from the start, "
            f"one row per member, wettest first by the end of week 2. Week 2 is shaded in the header. Flags mark "
            f"members whose week 2 is in an alarm tail of their own model's climate, and their week-2 cells are "
            f"outlined: <b>WD</b> warm-dry, <b>D</b> dry, <b>CW</b> cold-wet. Wk-2 T is the member's week-2 temperature "
            f"percentile. ECMWF members stop at day 15.</p><p class=key>Colour key (in): {key}</p>"
            f"<p class=basins>{nav}</p>{secs}")

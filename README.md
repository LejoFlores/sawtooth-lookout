# Sawtooth Lookout

Week-2 snow-drought early warning for five Idaho river basins, from Boise State University.

> **Experimental research product. Not an official forecast.** For official forecasts and warnings, see the
> [National Weather Service](https://www.weather.gov/). Provided as is, without warranty of any kind.

**Live page:** https://lejoflores.github.io/sawtooth-lookout/ · **Alerts:** issues labeled
[`early-warning`](../../issues?q=label%3Aearly-warning)

Every day Sawtooth Lookout reads the newest GEFS and ECMWF ensemble forecasts. It asks whether **week 2** (days 8-14)
is likely to land in the basin's warmest-and-driest ("snow eater"), driest or coldest-and-wettest 10%. Basins: SF
Payette at Lowman, Weiser near Weiser, Boise above Lucky Peak, Big Wood at Hailey, and Snake above Heise.

## Method

1. Take the newest 00 UTC start that GEFS (31 members, via [dynamical.org](https://dynamical.org)) has through day
   21. Add ECMWF ENS (50 members, ECMWF open data on AWS) for the same start when it is available; it goes to day 15.
2. Compute basin-area-weighted week-2 mean 2 m temperature and total precipitation for each member.
3. Rank each member within its own model's reforecast climate (GEFSv12 2000-2019; ECMWF CY49R1 2006-2025), using
   starts within 21 days of the date. The warm-dry index is z(T) − z(√P) and the
   warm-wet (rain-on-snow) index is z(T) + z(√P).
4. Compute the share of members beyond the 10th/90th percentile, with GEFS and ECMWF weighted half each.
5. Turn the share into odds with a logistic calibration per event and season, fit to the hindcast
   (`static/calibration.csv`).
6. From November through February, when the odds of warm-dry, dry, warm-wet or cold-wet reach 15%, open an alert issue. While
   the alarm holds, the issue gets a daily comment; it closes when the alarm clears.

Days 8-21 from GEFS alone are shown as a heads-up and never alert.

The landing page has a map of Idaho with each forecast basin shaded by its alert level; click a basin for its own
page with the odds trend and the member-by-member table. Other Idaho basins are greyed out (coming soon).
The page also shows how the odds have moved over the last 7 runs, and it calls out alert-level crossings and steady
rises. Alert issue comments say how today's odds compare with the previous run. Every day's page is kept under
`YYYYMMDD/` and listed in `archive.html`. To backfill past starts, run the workflow with mode `backfill` and init
`YYYY-MM-DD..YYYY-MM-DD`.

## Skill

Hindcast, Nov-Feb, GEFS+ECMWF reforecasts, 15 winters, leave-one-winter-out calibration (`static/hindcast_scores.csv`):

| Event | ROC | Brier skill | Alerts / winter / basin | Alerts right | Events caught | Base rate |
|---|---|---|---|---|---|---|
| Warm-dry | 0.83 | +0.12 | 2.6 | 28% | 51% | 9% |
| Dry | 0.78 | +0.11 | 3.0 | 24% | 49% | 9% |
| Warm-wet | 0.69 | +0.08 | 3.7 | 22% | 48% | 11% |
| Cold-wet | 0.79 | +0.17 | 5.0 | 29% | 71% | 13% |

Warm-wet is weaker in winter but stronger in March-April (ROC 0.76, Brier skill +0.17, right 30% against a 16%
base rate), when rain-on-snow matters most. Alerts currently run November through February only.

Replay of the real-time forecasts against PRISM (`scripts/replay.py`):
- **GEFS alone, WY2021-2026:** ROC 0.85 for warm-dry, 0.80 for dry and 0.88 for cold-wet
  (warm-wet not yet replayed).
- **GEFS+ECMWF, WY2025-2026:** ROC 0.79, 0.75 and 0.88.

Read these as rough guides. Tail events are rare, so the samples are small.

## Repository

| Path | What |
|---|---|
| `ews/run_daily.py` | Daily run: `YYYYMMDD/` (alarms.json, page, figure), `latest.json`, `history.csv`, `index.html`, `archive.html` |
| `ews/notify.py` | Opens, comments on and closes alert issues |
| `ews/sources.py` | GEFS (Zarr) and ECMWF open data (GRIB byte ranges) readers |
| `ews/page.py` | The web pages: map landing page, basin pages with Swain-style member tables, archive |
| `scripts/build_map.py` | Builds the map layers in `static/map/` from USGS WBD and us-atlas |
| `vendor/leaflet/` | Leaflet 1.9.4 (BSD-2-Clause), served with the site |
| `static/` | Basin polygons, grid weights, reforecast climates, calibration, PRISM basin means |
| `scripts/replay.py` | Replays past real-time forecasts and scores them against PRISM |
| `scripts/build_static.py` | Rebuilds `static/` from reforecast basin extracts (not included) |
| `.github/workflows/lookout.yml` | Runs daily at 18:30 UTC; commits to the `products` branch and deploys the site |

To run locally: `pip install -r requirements.txt`, then `python -m ews.run_daily [--init YYYY-MM-DD] [--no-ecmwf]`.
Products go to `products/` or to `$EWS_PRODUCTS`.

## Caveats

- The live ensembles (31 and 50 members) are larger than the reforecasts (11 and 10), so the odds may be slightly
  cautious.
- The live ECMWF cycle is newer than the reforecast climate.
- Alerts are tuned for November through February. Odds in other months are shown for reference only.

## Data and credits

- NOAA Global Ensemble Forecast System (GEFS) and GEFSv12 reforecasts, via dynamical.org and NOAA Open Data
  Dissemination.
- ECMWF open data, © ECMWF, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), reduced here to basin
  statistics. ECMWF does not endorse this product.
- PRISM Climate Group, Oregon State University, https://prism.oregonstate.edu.
- Basin boundaries: USGS Watershed Boundary Dataset (HUC12s upstream of the USGS gauges; HUC8s on the map).
- State outline: US Census cartographic boundaries via us-atlas. Basemap: USGS The National Map (USGSTopo).

## License and citation

Code: [Apache License 2.0](LICENSE); see [NOTICE](NOTICE). Forecast products (pages, figures, data files):
[CC BY 4.0](LICENSE-products.md). Please cite with [CITATION.cff](CITATION.cff).
© 2026 Lejo Flores and Boise State University.

# Reforecast archive on Borah (for adding basins to Sawtooth Lookout)

Adding a basin to Sawtooth Lookout needs its reforecast climate: what the GEFS and ECMWF reforecast members said for
that basin on every past start, so live members can be ranked against it. Extracting reforecasts is the expensive part,
so these jobs do it once for the whole western US on each model's native grid. After that, any basin (an Idaho HUC8, a
West-wide HUC4) is a cheap area-weighted polygon mean.

| What | Source | Grid | Starts | Size |
| --- | --- | --- | --- | --- |
| GEFSv12 reforecast, daily T2m and precipitation, days 1-35, 11 members | `s3://noaa-gefs-retrospective` | 0.25 deg days 1-10, 0.5 deg days 11-35 | 1043 Wednesdays 2000-2019 | ~1.4 TB downloaded, ~10 GB kept |
| ECMWF reforecast (CY49R1), daily T2m and precipitation, leads 0-45, 10 members | `s3://planette-ifs-46-day` | 1.5 deg (native) | 2289 starts 2006-2025 | ~2 GB kept |

Domain: 29-57 N, 131.5-99.5 W. Day d of a start is the UTC calendar day start + d - 1, as in the hindcast and the live
job. Both scripts reproduce the five-basin hindcast extracts (`ext5/gefs`, `ext5/ecmwf`) to within float rounding.

The ECMWF part needs no Borah job (about 2 s per start from anywhere), and GEFS is about 15-20 s per start, so both
can also run in a cloud session. Borah is the home for the full archive and for reruns.

## Steps (run from this folder: `cd sawtooth-lookout/borah`)

1. **Environment, on the login node.** `bash make_env.sh` builds a conda-forge env in
   `/bsuscratch/$USER/sawtooth-reforecast/env`, solved for the compute nodes' glibc 2.17, and checks that no library
   needs a newer glibc. Set `REFC_ROOT` first to put everything somewhere else.
2. **Network probe.** `bash probe_network.sh` on the login node, then `sbatch probe_network.slurm`. The job's log
   (`logs/refc-probe-<jobid>.out`) ends with a VERDICT line saying which route to use. It also grids one test start
   if the compute node reaches AWS.
3. **GEFS archive, either route:**
   - **Route A, compute nodes reach AWS:** `sbatch gefs_grid.slurm`. This runs 50 small array tasks in the `short` partition (2 CPUs, 3 GB, ~5-15 min each), at most 5 at once, so it stays out of the way of other queued work.
   - **Route B, they don't:** `nohup bash run_offline.sh > logs/offline.log 2>&1 &` on the login node. The login
     node only downloads, in batches of 20 starts. Compute-node jobs (`grid_raw.slurm`) decode each batch and delete
     its raw GRIB, so at most about 50 GB of raw files sit in `$REFC_RAW` at once.

   Both routes are restartable: run the same command again and finished starts are skipped. To limit the run to some
   months, set `MONTHS=11,12,1,2,3,4`, e.g. `sbatch --export=ALL,MONTHS=11,12,1,2 gefs_grid.slurm`.
4. **Progress.** `bash status.sh` shows how many starts are written, any FAILED or MISSING lines from the logs, and
   disk use.
5. **Basin means.** For example, the Idaho HUC8s:
   `sbatch --export=ALL,POLYGONS=/path/huc8.gpkg,ID=huc8,NAME=idaho_huc8 polygon_means.slurm`.
   The output is one `.npz` per start in `$REFC_ROOT/basin-means/idaho_huc8/gefs/`, with `t2m` and `precip` shaped
   `[member, day, basin]`. That is the layout `scripts/build_static.py` reads.

## Files

| File | Runs on | Does |
| --- | --- | --- |
| `make_env.sh`, `env.sh` | login node / every job | builds and activates the env; sets `REFC_ROOT`, `REFC_ARCHIVE`, `REFC_RAW` |
| `probe_network.sh`, `probe_network.slurm` | login / compute | which hosts each node reaches, download speed, env imports, one test start |
| `gefs_grid.py` | anywhere | one start: fetch the needed GRIB messages (byte ranges), crop, daily means/sums -> NetCDF |
| `gefs_grid.slurm` | compute (route A) | array over the 1043 starts |
| `run_offline.sh`, `grid_raw.slurm` | login + compute (route B) | download on the login node, decode on compute nodes |
| `ecmwf_grid.py` | anywhere with `icechunk` | ECMWF reforecast crop (not in the Borah env; already done in the cloud) |
| `polygon_means.py`, `polygon_means.slurm` | compute | area-weighted basin means for any polygon file |
| `status.sh` | login | progress, failures, disk use |

The ECMWF reforecast is CC BY 4.0 (ECMWF), via Planette's copy. Products built on it must carry that attribution, as
the live site already does.

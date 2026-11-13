#!/bin/bash
# GEFSv12 reforecast archive, ROUTE B (compute nodes have no internet). On the LOGIN node:
#   nohup bash run_offline.sh > logs/offline.log 2>&1 &         (MONTHS=11,12,1,2 ... to limit the starts)
# Downloads BATCH starts at a time to $REFC_RAW (no decoding here, so the login node only moves bytes), then hands each
# batch to a compute-node job (grid_raw.slurm) that grids it and deletes the raw files. At most two batches of raw
# GRIB (~1.3 GB per start, so ~50 GB with BATCH=20) sit on disk at once. Restartable: finished starts are skipped.
set -euo pipefail
source "$(dirname "$0")/env.sh"
BATCH=${BATCH:-20}
mapfile -t ALL < <(python gefs_grid.py --list ${MONTHS:+--months $MONTHS} 2>/dev/null)
todo=()
for s in "${ALL[@]}"; do [ -f "$REFC_ARCHIVE/gefs/${s:0:4}/$s.nc" ] || todo+=("$s"); done
echo "$(date -u +%FT%TZ) ${#todo[@]} of ${#ALL[@]} starts to do, batches of $BATCH"
for ((i = 0; i < ${#todo[@]}; i += BATCH)); do
  list=$(IFS=,; echo "${todo[*]:i:BATCH}")
  while [ "$(squeue -h -u "$USER" -n refc-raw | wc -l)" -ge 2 ]; do sleep 60; done
  python gefs_grid.py --out "$REFC_ARCHIVE" --raw "$REFC_RAW" --fetch-only --only "$list" --workers 8
  sbatch --parsable --export=ALL,ONLY="$list" grid_raw.slurm
done
echo "$(date -u +%FT%TZ) all batches downloaded and submitted; check with: bash status.sh"

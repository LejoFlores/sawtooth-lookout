#!/bin/bash
# GEFSv12 reforecast archive, ROUTE A (compute nodes reach AWS; see probe_network.slurm). Each array task takes every
# Nth start of the 1043 Wednesdays 2000-2019 (N = array size), so the whole set is covered whatever --array says.
#   sbatch gefs_grid.slurm                          # all 1043 starts, 50 tasks, at most 10 running at once
#   sbatch --export=ALL,MONTHS=10,11,12,1,2,3,4 gefs_grid.slurm      # only starts in those months
# Restartable: rerun the same command and finished starts are skipped. Check with: bash status.sh
# Per start: ~1.3 GB downloaded, ~10 MB written, ~15-30 s. Whole archive: ~1.4 TB in, ~10 GB out.
#SBATCH -J refc-gefs
#SBATCH -p bsudfq
#SBATCH --array=0-49%10
#SBATCH -c 4
#SBATCH --mem=8G
#SBATCH -t 12:00:00
#SBATCH -o logs/%x-%A_%a.out
source ./env.sh
python gefs_grid.py --out "$REFC_ARCHIVE" --task "$SLURM_ARRAY_TASK_ID" --ntasks "$SLURM_ARRAY_TASK_COUNT" \
  --workers 8 ${MONTHS:+--months $MONTHS}

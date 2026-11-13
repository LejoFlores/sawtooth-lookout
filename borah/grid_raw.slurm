#!/bin/bash
# ROUTE B helper (submitted by run_offline.sh): grids starts already downloaded to $REFC_RAW, then deletes their raw GRIB.
#SBATCH -J refc-raw
#SBATCH -p bsudfq
#SBATCH -c 4
#SBATCH --mem=8G
#SBATCH -t 04:00:00
#SBATCH -o logs/%x-%j.out
source ./env.sh
python gefs_grid.py --out "$REFC_ARCHIVE" --raw "$REFC_RAW" --clean-raw --only "${ONLY:?set ONLY}" --workers 4

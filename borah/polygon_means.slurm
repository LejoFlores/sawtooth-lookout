#!/bin/bash
# Basin means of the archive for any set of polygons (minutes for ~100 polygons x 1043 starts).
#   sbatch --export=ALL,POLYGONS=../static/huc8_idaho.gpkg,ID=huc8,NAME=idaho_huc8 polygon_means.slurm
# Optional: LAYER (gpkg layer), KEEP (csv of ids to keep, in order), SYSTEMS (default "gefs", or "gefs ecmwf").
# Output: $REFC_ROOT/basin-means/$NAME/{gefs,ecmwf}/YYYYMMDD.npz  (copy that folder back to the project to use it)
#SBATCH -J refc-poly
#SBATCH -p bsudfq
#SBATCH -c 2
#SBATCH --mem=16G
#SBATCH -t 04:00:00
#SBATCH -o logs/%x-%j.out
source ./env.sh
for s in ${SYSTEMS:-gefs}; do
  python polygon_means.py --polygons "${POLYGONS:?set POLYGONS}" --id "${ID:?set ID}" ${LAYER:+--layer $LAYER} \
    ${KEEP:+--keep $KEEP} --system $s --archive "$REFC_ARCHIVE" --out "$REFC_ROOT/basin-means/${NAME:?set NAME}"
done

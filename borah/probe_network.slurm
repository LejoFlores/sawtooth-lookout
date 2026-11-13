#!/bin/bash
# Do Borah compute nodes reach AWS? Also checks the environment imports on a compute node (glibc 2.17).
#   sbatch probe_network.slurm        then paste logs/refc-probe-<jobid>.out into the thread
#SBATCH -J refc-probe
#SBATCH -p short
#SBATCH -c 1
#SBATCH -t 00:15:00
#SBATCH -o logs/%x-%j.out
source ./env.sh
bash probe_network.sh
python -c "import eccodes, xarray, netCDF4, geopandas; print('env imports ok on', __import__('socket').gethostname())"
if curl -s -o /dev/null -m 20 https://noaa-gefs-retrospective.s3.amazonaws.com/; then
  echo "== one real start end to end (about 20 s)"
  python gefs_grid.py --out "$REFC_ARCHIVE" --only 20100113 --workers 8
  echo "VERDICT: compute nodes reach AWS -> use: sbatch gefs_grid.slurm"
else
  echo "VERDICT: no internet on compute nodes -> use: nohup bash run_offline.sh > logs/offline.log 2>&1 &   (login node)"
fi

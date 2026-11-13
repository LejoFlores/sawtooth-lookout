# Sourced by every script here: paths and the Python environment made by make_env.sh.
#   REFC_ROOT     where the env lives                  (default /bsuscratch/$USER/sawtooth-reforecast)
#   REFC_ARCHIVE  the gridded archive (gefs/, ecmwf/)  (default $REFC_ROOT/archive)
#   REFC_RAW      raw GRIB, offline route only         (default $REFC_ROOT/raw)
export REFC_ROOT=${REFC_ROOT:-/bsuscratch/$USER/sawtooth-reforecast}
export REFC_ARCHIVE=${REFC_ARCHIVE:-$REFC_ROOT/archive}
export REFC_RAW=${REFC_RAW:-$REFC_ROOT/raw}
export PATH=$REFC_ROOT/env/bin:$PATH
export HDF5_USE_FILE_LOCKING=FALSE        # NetCDF on Borah's network file systems
export OMP_NUM_THREADS=1
cd "$(dirname "${BASH_SOURCE[0]}")"       # the borah/ folder, wherever the repo was cloned
mkdir -p logs
[ -x $REFC_ROOT/env/bin/python ] || { echo "No environment in $REFC_ROOT/env: run 'bash make_env.sh' on the login node"; return 1 2>/dev/null || exit 1; }

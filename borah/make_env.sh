#!/bin/bash
# Creates the Python environment in $REFC_ROOT/env (default /bsuscratch/$USER/sawtooth-reforecast/env).
# Run on the LOGIN node (it downloads ~400 MB):   bash make_env.sh
# Borah's compute nodes run glibc 2.17, older than the login node's, so the solver is told the compute nodes' limit and
# only picks conda-forge builds that run there. Everything is from conda-forge (no pip wheels, which often need 2.28).
set -euo pipefail
export REFC_ROOT=${REFC_ROOT:-/bsuscratch/$USER/sawtooth-reforecast}
ENV=$REFC_ROOT/env
mkdir -p $REFC_ROOT
export CONDA_OVERRIDE_GLIBC=2.17
SPEC=(python=3.11 numpy pandas xarray netcdf4 h5netcdf eccodes python-eccodes requests geopandas shapely pyogrio)

if [ -x $ENV/bin/python ]; then
  echo "$ENV exists; remove it to rebuild."
else
  CONDA=$(command -v mamba || command -v conda || true)
  if [ -z "$CONDA" ]; then                       # no conda on PATH: a standalone micromamba in $REFC_ROOT/bin
    mkdir -p $REFC_ROOT/bin
    curl -fsSL https://conda.anaconda.org/conda-forge/linux-64/micromamba-2.9.0-0.tar.bz2 | tar -xj -C $REFC_ROOT bin/micromamba
    CONDA=$REFC_ROOT/bin/micromamba
    export MAMBA_ROOT_PREFIX=$REFC_ROOT/mamba
  fi
  echo "Solving with $CONDA (glibc <= $CONDA_OVERRIDE_GLIBC)"
  $CONDA create -y -p $ENV -c conda-forge --override-channels "${SPEC[@]}"
fi

$ENV/bin/python -c "import eccodes, xarray, netCDF4, geopandas, requests; print('imports ok; eccodes', eccodes.codes_get_api_version())"

# Any library needing a newer glibc than the compute nodes' would fail there; list them if objdump is available.
if command -v objdump >/dev/null; then
  bad=$(find $ENV/lib $ENV/bin -type f \( -name '*.so*' -o -perm -u+x \) 2>/dev/null | while read f; do
          objdump -T "$f" 2>/dev/null | grep -o 'GLIBC_2\.[0-9]*' | sort -t. -k2 -n | tail -1 \
            | awk -v f="$f" -F. '$2 > 17 {print $0, f}'; done | head)
  [ -z "$bad" ] && echo "glibc check: nothing needs more than GLIBC_2.17" || { echo "glibc check FAILED:"; echo "$bad"; exit 1; }
fi
echo "Environment ready: $ENV. Next: bash probe_network.sh, then sbatch probe_network.slurm"

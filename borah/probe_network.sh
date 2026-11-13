#!/bin/bash
# Which data hosts does this node reach? Run it on the login node (bash probe_network.sh); probe_network.slurm runs the
# same checks on a compute node. Read-only, about a minute.
H=$(hostname)
echo "== $H  $(date -u +%FT%TZ)  glibc $(ldd --version 2>&1 | head -1 | awk '{print $NF}')"
for u in \
  "GEFS reforecast (AWS S3)|https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast/2010/2010011300/c00/Days:1-10/tmp_2m_2010011300_c00.grib2.idx" \
  "ECMWF reforecast (AWS S3)|https://planette-ifs-46-day.s3.us-east-2.amazonaws.com/reforecasts/repo" \
  "GitHub|https://github.com" \
  "conda-forge|https://conda.anaconda.org/conda-forge/noarch/repodata.json.zst"; do
  name=${u%%|*}; url=${u#*|}
  printf '%-28s ' "$name"; curl -s -o /dev/null -m 20 -w '%{http_code} in %{time_total}s\n' "$url" || echo "no route (curl exit $?)"
done
if [ -n "${PROBE_SPEED:-1}" ]; then        # one real 60 MB file, to estimate the archive's download time
  printf '%-28s ' "60 MB GEFS file"
  curl -s -o /dev/null -m 300 -w '%{size_download} bytes at %{speed_download} B/s\n' \
    "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast/2010/2010011300/c00/Days:1-10/tmp_2m_2010011300_c00.grib2" || echo failed
fi

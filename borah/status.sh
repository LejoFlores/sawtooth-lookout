#!/bin/bash
# How far along is the archive? bash status.sh  (prints counts, failures in the logs, and disk use)
source "$(dirname "$0")/env.sh"
n=$(python gefs_grid.py --list ${MONTHS:+--months $MONTHS} 2>/dev/null | wc -l)
have=$(find "$REFC_ARCHIVE/gefs" -name '[0-9]*[0-9].nc' 2>/dev/null | wc -l)
echo "GEFS starts written: $have of $n"
echo "ECMWF starts written: $(find "$REFC_ARCHIVE/ecmwf" -name '[0-9]*[0-9].nc' 2>/dev/null | wc -l)"
echo "Failures in logs:"; grep -h "FAILED\|MISSING" logs/refc-*.out 2>/dev/null | sort | uniq | tail -20
du -sh "$REFC_ARCHIVE" "$REFC_RAW" 2>/dev/null

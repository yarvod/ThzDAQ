#! /bin/bash

git log --pretty=tformat: --numstat | awk '{inserted+=$1; deleted+=$2; delta+=$1-$2; } END {printf "Commit stats:\n- Lines added (total)....  %s\n- Lines deleted (total)..  %s\n- Total lines (delta)....  %s\n", inserted, deleted, delta}'

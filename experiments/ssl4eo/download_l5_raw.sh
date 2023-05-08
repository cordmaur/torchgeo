#!/usr/bin/env bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

set -euo pipefail

# User-specific parameters
ROOT_DIR=data
SAVE_PATH="$ROOT_DIR/ssl4eo-l5-raw"
MATCH_FILE="$ROOT_DIR/ssl4eo-l-60/sampled_locations.csv"
NUM_WORKERS=40
START_INDEX=0
END_INDEX=10

# Satellite-specific parameters
COLLECTION=LANDSAT/LM05/C02/T1
QA_BAND=QA_PIXEL
QA_CLOUD_BIT=3
META_CLOUD_NAME=CLOUD_COVER
YEAR=1991  # MSS data acquisitions over the United States ceased in 1992
BANDS=(B1 B2 B3 B4)
ORIGINAL_RESOLUTIONS=(60 60 60 30)
NEW_RESOLUTIONS=60

# Generic parameters
SCRIPT_DIR=$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)
CLOUD_PCT=20
SIZE=264
DTYPE=float32
LOG_FREQ=1000

time python3 "$SCRIPT_DIR/download_ssl4eo.py" \
    --save-path "$SAVE_PATH" \
    --collection $COLLECTION \
    --qa-band $QA_BAND \
    --qa-cloud-bit $QA_CLOUD_BIT \
    --meta-cloud-name $META_CLOUD_NAME \
    --cloud-pct $CLOUD_PCT \
    --dates $YEAR-03-20 $YEAR-06-21 $YEAR-09-23 $YEAR-12-21 \
    --radius $(($NEW_RESOLUTIONS * $SIZE / 2)) \
    --bands ${BANDS[@]} \
    --original-resolutions ${ORIGINAL_RESOLUTIONS[@]} \
    --new-resolutions $NEW_RESOLUTIONS \
    --dtype $DTYPE \
    --num-workers $NUM_WORKERS \
    --log-freq $LOG_FREQ \
    --match-file "$MATCH_FILE" \
    --indices-range $START_INDEX $END_INDEX \
    --debug

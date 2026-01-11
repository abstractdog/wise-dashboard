#!/bin/bash
# Setup script to load WISE_TOKEN from credentials file
# Source this file in your shell: source setup_env.sh

# If WISE_TOKEN is already set, use it; otherwise load from file
if [ -n "${WISE_TOKEN:-}" ]; then
    echo "WISE_TOKEN already set in environment"
elif [ -f ~/creds/wise_personal_account_token ]; then
    export WISE_TOKEN=$(cat ~/creds/wise_personal_account_token)
    echo "WISE_TOKEN loaded from ~/creds/wise_personal_account_token"
else
    echo "Error: WISE_TOKEN not set and ~/creds/wise_personal_account_token not found" >&2
    return 1 2>/dev/null || exit 1
fi

# Optional: Set InfluxDB configuration
# Note: InfluxDB v3 uses port 8181 by default (not 8086)
export INFLUXDB_URL="${INFLUXDB_URL:-http://localhost:8181}"
export INFLUXDB_TOKEN="${INFLUXDB_TOKEN:-}"
export INFLUXDB_ORG="${INFLUXDB_ORG:-my-org}"
export INFLUXDB_BUCKET="${INFLUXDB_BUCKET:-wise_balances}"

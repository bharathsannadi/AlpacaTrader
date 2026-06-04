#!/bin/bash
# Polygon pull keep-alive loop
# ============================
# Long-running parent for the launchd agent com.alpacatrader.polygon. Runs the
# stall/restart watchdog every 5 min. Because this loop never exits, launchd
# never reaps the nohup-spawned pull's process group, so the pull survives.
# launchd KeepAlive restarts THIS loop if it ever dies (reboot / crash).
#
# The pull itself (polygon_options.py --scope full) is resumable — it skips
# underlyings already archived to parquet — so any restart only re-does the
# in-progress underlying. Deadline: Polygon subscription lapses 2026-06-16.
set -u
REPO="/Users/bsannadi/Desktop/bharath/AlpacaTrader"
while true; do
    bash "$REPO/scripts/poly_watchdog.sh"
    sleep 300
done

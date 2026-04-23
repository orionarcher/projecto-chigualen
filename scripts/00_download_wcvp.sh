#!/usr/bin/env bash
# Pulls the full Kew WCVP checklist (wcvp.zip) to Chigualen/data/raw/wcvp/
# and extracts wcvp_names.csv. Run from project root:
#     bash scripts/00_download_wcvp.sh
set -euo pipefail

DEST="Chigualen/data/raw/wcvp"
URL="http://sftp.kew.org/pub/data-repositories/WCVP/wcvp.zip"

mkdir -p "$DEST"
echo "downloading $URL"
curl -sSL -o "$DEST/wcvp.zip" "$URL"

echo "extracting wcvp_names.csv"
unzip -o "$DEST/wcvp.zip" wcvp_names.csv -d "$DEST"

echo "done:"
ls -la "$DEST"/

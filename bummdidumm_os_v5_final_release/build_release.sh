#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 bummdidumm_os_v5_final_release/release_audit.py
rm -f bummdidumm_os_v5_final_release.zip
zip -r bummdidumm_os_v5_final_release.zip bummdidumm_os_v5_final_release -x "*/__pycache__/*" -x "*.pyc" -x "archive/*"

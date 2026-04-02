#!/bin/bash
set -e

echo "=========================================="
echo " Starting Self-Audit for bummdidumm-OS V5"
echo "=========================================="

python3 release_audit.py
audit_result=$?

if [ $audit_result -eq 0 ]; then
    echo "=========================================="
    echo " Self-Audit PASSED ✅. Building ZIP..."
    echo "=========================================="

    # Remove any potential remaining cache files one last time before zip
    find v5_final -type d -name "__pycache__" -exec rm -rf {} +
    find v5_final -type f -name "*.pyc" -delete

    # Remove old zips to prevent confusion
    rm -f bummdidumm_os_v5_final_release_with_sorting_and_audit.zip

    # Create the final ZIP
    zip -r bummdidumm_os_v5_final_release_with_sorting_and_audit.zip v5_final/ release_audit.py SELF_AUDIT.md

    echo "=========================================="
    echo " ZIP successfully created:"
    echo " bummdidumm_os_v5_final_release_with_sorting_and_audit.zip"
    echo "=========================================="
else
    echo "=========================================="
    echo " Self-Audit FAILED ❌. ZIP NOT created."
    echo " Fix the reported issues and try again."
    echo "=========================================="
    exit 1
fi

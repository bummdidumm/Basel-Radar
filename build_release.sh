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
    find bummdidumm_os_v5_final_release -type d -name "__pycache__" -exec rm -rf {} +
    find bummdidumm_os_v5_final_release -type f -name "*.pyc" -delete

    # Move the audit script inside the folder so the zip only contains one root directory
    mv release_audit.py bummdidumm_os_v5_final_release/
    mv SELF_AUDIT.md bummdidumm_os_v5_final_release/

    # Remove old zips to prevent confusion
    rm -f bummdidumm_os_v5_final_release.zip

    # Create the final ZIP
    zip -r bummdidumm_os_v5_final_release.zip bummdidumm_os_v5_final_release/

    echo "=========================================="
    echo " ZIP successfully created:"
    echo " bummdidumm_os_v5_final_release.zip"
    echo "=========================================="
else
    echo "=========================================="
    echo " Self-Audit FAILED ❌. ZIP NOT created."
    echo " Fix the reported issues and try again."
    echo "=========================================="
    exit 1
fi

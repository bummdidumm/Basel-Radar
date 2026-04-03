#!/bin/bash
set -euo pipefail

: "${PROJECT_ID:?Bitte PROJECT_ID setzen}"
TARGET_FOLDER_ID="${TARGET_FOLDER_ID:-}"
: "${ARCHIVE_FOLDER_ID:?Bitte ARCHIVE_FOLDER_ID setzen}"
: "${INDEX_FOLDER_ID:?Bitte INDEX_FOLDER_ID setzen}"
: "${CONTROL_SHEET_ID:?Bitte CONTROL_SHEET_ID setzen}"
: "${GEMINI_API_KEY:?Bitte GEMINI_API_KEY setzen}"

REGION="${REGION:-us-central1}"
SKIP_OVER_MB="${SKIP_OVER_MB:-500}"
SA_EMAIL="${SA_EMAIL:-bummdidumm-runner@${PROJECT_ID}.iam.gserviceaccount.com}"

echo "Deploying bummdidumm-OS V5 to Cloud Run Jobs for Project: $PROJECT_ID"

gcloud run jobs deploy bummdidumm-pass1-delta-dedupe \
  --source . \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --set-env-vars="TARGET_FOLDER_ID=${TARGET_FOLDER_ID},ARCHIVE_FOLDER_ID=${ARCHIVE_FOLDER_ID},CONTROL_SHEET_ID=${CONTROL_SHEET_ID},SKIP_OVER_MB=${SKIP_OVER_MB}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=2Gi --task-timeout=3600s \
  --command="python","main_pass1.py"

gcloud run jobs deploy bummdidumm-pass2-ocr-index \
  --source . \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --set-env-vars="INDEX_FOLDER_ID=${INDEX_FOLDER_ID},CONTROL_SHEET_ID=${CONTROL_SHEET_ID},GEMINI_API_KEY=${GEMINI_API_KEY}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=2Gi --task-timeout=3600s \
  --command="python","main_pass2.py"

gcloud run jobs deploy bummdidumm-apply-renames \
  --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --set-env-vars="CONTROL_SHEET_ID=${CONTROL_SHEET_ID}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=1Gi --task-timeout=1800s \
  --command="python","main_apply_renames.py"

gcloud run jobs deploy bummdidumm-safe-sort \
  --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --set-env-vars="CONTROL_SHEET_ID=${CONTROL_SHEET_ID}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=1Gi --task-timeout=3600s \
  --command="python","main_safe_sort.py"

gcloud run jobs deploy bummdidumm-apply-sort \
  --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --set-env-vars="CONTROL_SHEET_ID=${CONTROL_SHEET_ID}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=1Gi --task-timeout=3600s \
  --command="python","main_apply_sort.py"

echo "Done!"

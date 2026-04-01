#!/bin/bash
set -e

PROJECT_ID="DEIN_PROJEKT_ID"
REGION="us-central1"
SA_EMAIL="bummdidumm-runner@${PROJECT_ID}.iam.gserviceaccount.com"

# Deploy Pass 1: Delta & Dedupe
gcloud run jobs deploy bummdidumm-pass1-delta-dedupe \
  --source . \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars="TARGET_FOLDER_ID=,ARCHIVE_FOLDER_ID=,CONTROL_SHEET_ID=,SKIP_OVER_MB=500" \
  --max-retries=0 \
  --tasks=1 \
  --cpu=1 \
  --memory=2Gi \
  --task-timeout=3600s \
  --command="python","main_pass1.py"

# Deploy Pass 2: OCR & Indexing
gcloud run jobs deploy bummdidumm-pass2-ocr-index \
  --source . \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars="INDEX_FOLDER_ID=,CONTROL_SHEET_ID=,GEMINI_API_KEY=" \
  --max-retries=0 \
  --tasks=1 \
  --cpu=1 \
  --memory=2Gi \
  --task-timeout=3600s \
  --command="python","main_pass2.py"

# Deploy Renames (Optional)
gcloud run jobs deploy bummdidumm-apply-renames \
  --source . \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars="CONTROL_SHEET_ID=" \
  --max-retries=0 \
  --tasks=1 \
  --cpu=1 \
  --memory=1Gi \
  --task-timeout=1800s \
  --command="python","main_apply_renames.py"

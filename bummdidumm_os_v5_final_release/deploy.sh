#!/bin/bash
set -euo pipefail

: "${PROJECT_ID:?Bitte PROJECT_ID setzen}"
# TARGET_FOLDER_ID is optional — leave empty to scan all monitored folders
TARGET_FOLDER_ID="${TARGET_FOLDER_ID:-}"
: "${ARCHIVE_FOLDER_ID:?Bitte ARCHIVE_FOLDER_ID setzen}"
: "${INDEX_FOLDER_ID:?Bitte INDEX_FOLDER_ID setzen}"
: "${CONTROL_SHEET_ID:?Bitte CONTROL_SHEET_ID setzen}"
: "${SA_EMAIL:?Bitte SA_EMAIL setzen (z.B. runner@PROJECT_ID.iam.gserviceaccount.com)}"

# BRAIN_INDEX_ROOT: der Pfad, unter dem Pass 2 und Safe Sort den Brain Index persistent speichern.
# Muss auf ein dauerhaftes Volume zeigen — Cloud Run Task-Storage ist ephemer und geht nach jedem Run verloren.
#
# Empfohlene Variante: GCS FUSE Mount
#   Voraussetzungen:
#     1. GCS Bucket existiert:  gsutil mb gs://DEIN_BRAIN_INDEX_BUCKET
#     2. SA hat Zugriff:        gsutil iam ch serviceAccount:SA_EMAIL:objectAdmin gs://DEIN_BRAIN_INDEX_BUCKET
#     3. BRAIN_INDEX_BUCKET ist gesetzt (s. unten)
#
# Alternativ: Cloud Filestore (NFS) oder ein anderes dauerhaftes Volume
: "${BRAIN_INDEX_BUCKET:?BRAIN_INDEX_BUCKET muss gesetzt sein (GCS Bucket fuer persistenten Brain Index, z.B. my-project-brain-index)}"

BRAIN_INDEX_MOUNT="/brain_index"
BRAIN_INDEX_ROOT="${BRAIN_INDEX_MOUNT}"
: "${BRAIN_INDEX_ROOT:?BRAIN_INDEX_ROOT konnte nicht gesetzt werden — BRAIN_INDEX_MOUNT fehlt}"

REGION="${REGION:-europe-west6}"
SKIP_OVER_MB="${SKIP_OVER_MB:-500}"
OCR_BUDGET_PER_RUN="${OCR_BUDGET_PER_RUN:-500}"

# OAuth user credentials are injected via Secret Manager into all jobs.
# Create secrets before first deploy: see QUICKSTART.md §1.4.
_OAUTH_SECRETS="GOOGLE_OAUTH_CLIENT_ID=projects/${PROJECT_ID}/secrets/google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=projects/${PROJECT_ID}/secrets/google-oauth-client-secret:latest,GOOGLE_OAUTH_REFRESH_TOKEN=projects/${PROJECT_ID}/secrets/google-oauth-refresh-token:latest"

echo "Deploying bummdidumm-OS V5 to Cloud Run Jobs for Project: $PROJECT_ID"

gcloud run jobs deploy bummdidumm-pass1-delta-dedupe \
  --source . \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --set-env-vars="TARGET_FOLDER_ID=${TARGET_FOLDER_ID},ARCHIVE_FOLDER_ID=${ARCHIVE_FOLDER_ID},CONTROL_SHEET_ID=${CONTROL_SHEET_ID},SKIP_OVER_MB=${SKIP_OVER_MB}" \
  --set-secrets="${_OAUTH_SECRETS}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=2Gi --task-timeout=3600s \
  --command=python,main_pass1.py

# Pass 2 benoetigt persistenten Brain-Index-Mount — ohne diesen gehen alle Index-Daten nach jedem Run verloren.
gcloud run jobs deploy bummdidumm-pass2-ocr-index \
  --source . \
  --region "$REGION" \
  --service-account "$SA_EMAIL" \
  --set-env-vars="INDEX_FOLDER_ID=${INDEX_FOLDER_ID},CONTROL_SHEET_ID=${CONTROL_SHEET_ID},OCR_BUDGET_PER_RUN=${OCR_BUDGET_PER_RUN},BRAIN_INDEX_ROOT=${BRAIN_INDEX_ROOT}" \
  --set-secrets="GEMINI_API_KEY=projects/${PROJECT_ID}/secrets/gemini-api-key:latest,${_OAUTH_SECRETS}" \
  --add-volume="name=brain-index,type=cloud-storage,bucket=${BRAIN_INDEX_BUCKET}" \
  --add-volume-mount="volume=brain-index,mount-path=${BRAIN_INDEX_MOUNT}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=2Gi --task-timeout=3600s \
  --command=python,main_pass2.py

gcloud run jobs deploy bummdidumm-apply-renames \
  --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --set-env-vars="CONTROL_SHEET_ID=${CONTROL_SHEET_ID}" \
  --set-secrets="${_OAUTH_SECRETS}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=1Gi --task-timeout=1800s \
  --command=python,main_apply_renames.py

# Safe Sort liest den Brain Index — braucht denselben persistenten Mount wie Pass 2.
gcloud run jobs deploy bummdidumm-safe-sort \
  --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --set-env-vars="CONTROL_SHEET_ID=${CONTROL_SHEET_ID},BRAIN_INDEX_ROOT=${BRAIN_INDEX_ROOT}" \
  --set-secrets="${_OAUTH_SECRETS}" \
  --add-volume="name=brain-index,type=cloud-storage,bucket=${BRAIN_INDEX_BUCKET}" \
  --add-volume-mount="volume=brain-index,mount-path=${BRAIN_INDEX_MOUNT}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=1Gi --task-timeout=3600s \
  --command=python,main_safe_sort.py

gcloud run jobs deploy bummdidumm-apply-sort \
  --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --set-env-vars="CONTROL_SHEET_ID=${CONTROL_SHEET_ID}" \
  --set-secrets="${_OAUTH_SECRETS}" \
  --max-retries=0 --tasks=1 --cpu=1 --memory=1Gi --task-timeout=3600s \
  --command=python,main_apply_sort.py

echo "Done!"

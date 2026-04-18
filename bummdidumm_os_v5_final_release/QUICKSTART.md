# bummdidumm-OS V5 — Quickstart

---

## 1. Prerequisites

Everything below must be in place before any deployment command will succeed.

### 1.1 GCP project with billing

Create or select a project and enable billing. All resources (Cloud Run Jobs,
Artifact Registry, Cloud Storage, Sheets API) bill against this project.

```bash
gcloud projects create PROJECT_ID
gcloud billing projects link PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
gcloud config set project PROJECT_ID
```

### 1.2 APIs to enable

```bash
gcloud services enable \
  run.googleapis.com \
  drive.googleapis.com \
  sheets.googleapis.com \
  iam.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com
```

Gemini is accessed via the `google-genai` SDK using a `GEMINI_API_KEY`
(AI Studio key), not a GCP API, so no separate GCP service enable is needed
for Gemini itself.

### 1.3 Service account and IAM roles

```bash
# Create the service account
gcloud iam service-accounts create bummdidumm-runner \
  --display-name="bummdidumm-OS runner"

SA_EMAIL="bummdidumm-runner@PROJECT_ID.iam.gserviceaccount.com"

# Cloud Run invoker (allows the job to run)
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"

# Cloud Storage object admin (for BRAIN_INDEX_ROOT bucket)
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# Logs writer
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/logging.logWriter"
```

The service account also needs delegated Google Workspace access (Drive +
Sheets) via domain-wide delegation or direct sharing. Grant the SA edit
access to the Control Sheet and read/write access to the Google Drive folders
it scans (`TARGET_FOLDER_ID`, `ARCHIVE_FOLDER_ID`, `INDEX_FOLDER_ID`).

### 1.4 GEMINI_API_KEY — Google Secret Manager setup

`deploy.sh` passes `GEMINI_API_KEY` to the Pass 2 Cloud Run Job via
`--set-secrets` (Google Secret Manager), not as a plaintext environment
variable. Create the secret once and grant the service account read access:

```bash
# Create the secret (replace YOUR_API_KEY with the actual AI Studio key)
echo -n "YOUR_API_KEY" | gcloud secrets create gemini-api-key --data-file=-

# Grant the SA Secret Manager accessor access
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"
```

The secret path used by `deploy.sh` is:
`projects/${PROJECT_ID}/secrets/gemini-api-key:latest`

Do **not** set `GEMINI_API_KEY` as a shell export before running `deploy.sh` —
it is not read as an env variable in Cloud Run. For local development see §2.4.

### 1.5 BRAIN_INDEX_ROOT — persistent volume setup

`BRAIN_INDEX_ROOT` must point to a directory that survives Cloud Run task
restarts. The recommended approach is a Cloud Storage bucket mounted via
Cloud Storage FUSE.

```bash
# Create the bucket
gcloud storage buckets create gs://PROJECT_ID-brain-index \
  --location=europe-west6 \
  --uniform-bucket-level-access

# Grant the SA access to the bucket
gcloud storage buckets add-iam-policy-binding gs://PROJECT_ID-brain-index \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# Mount the bucket in the Cloud Run Job (Pass 2 and Safe Sort)
gcloud run jobs update bummdidumm-pass2-ocr-index \
  --add-volume=name=brain-index,type=cloud-storage,bucket=PROJECT_ID-brain-index \
  --add-volume-mount=volume=brain-index,mount-path=/mnt/brain-index \
  --update-env-vars=BRAIN_INDEX_ROOT=/mnt/brain-index \
  --region=europe-west6

gcloud run jobs update bummdidumm-safe-sort \
  --add-volume=name=brain-index,type=cloud-storage,bucket=PROJECT_ID-brain-index \
  --add-volume-mount=volume=brain-index,mount-path=/mnt/brain-index \
  --update-env-vars=BRAIN_INDEX_ROOT=/mnt/brain-index \
  --region=europe-west6
```

Cloud Storage FUSE requires Cloud Run to be on a second-generation execution
environment. The `--source` deploy path used in `deploy.sh` selects gen2
automatically; if you deploy from a pre-built image, add
`--execution-environment=gen2`.

---

## 2. Local development setup (Windows 11 compatible)

All commands below work in PowerShell, Git Bash, or WSL2.

### 2.1 Python venv

Requires Python 3.11 (matches Dockerfile base image).

```bash
python3.11 -m venv .venv

# Linux / macOS / WSL2
source .venv/bin/activate

# PowerShell
.venv\Scripts\Activate.ps1
```

### 2.2 Install dependencies

```bash
pip install -r bummdidumm_os_v5_final_release/requirements.txt
```

For a reproducible install matching production:

```bash
pip install --no-deps -r bummdidumm_os_v5_final_release/requirements.lock
```

### 2.3 Run the test suite locally

From the repo root:

```bash
PYTHONPATH=bummdidumm_os_v5_final_release pytest bummdidumm_os_v5_final_release/tests/ -q
```

All tests are offline (no GCP or Drive credentials required).

### 2.4 Run a single pass locally without Cloud Run

Obtain a credentials file for a user account that has access to the Drive
folders and the Control Sheet.

```bash
export CONTROL_SHEET_ID="your-sheet-id"
export TARGET_FOLDER_ID="your-drive-folder-id"
export ARCHIVE_FOLDER_ID="your-archive-folder-id"
export INDEX_FOLDER_ID="your-index-folder-id"
export GEMINI_API_KEY="your-ai-studio-key"  # local dev only — in Cloud Run via Secret Manager (§1.4)
export BRAIN_INDEX_ROOT="/tmp/brain_index_local"

cd bummdidumm_os_v5_final_release
python main_pass1.py    # delta scan + dedupe
python main_pass2.py    # OCR + brain index build
```

On Windows, set environment variables in PowerShell using `$env:NAME = "value"`
before running the scripts.

---

## 3. First deployment checklist

Follow these steps in order. Each step has a success criterion.

| # | Action | Success criterion |
|---|--------|-------------------|
| 1 | Run `gcloud services enable` (section 1.2) | No errors; `gcloud services list` shows all APIs ENABLED |
| 2 | Create service account and grant IAM roles (section 1.3) | `gcloud iam service-accounts describe ${SA_EMAIL}` returns HTTP 200 |
| 3 | Create Secret Manager secret and grant SA access (section 1.4) | `gcloud secrets versions access latest --secret=gemini-api-key` returns the key |
| 4 | Share Drive folders and Control Sheet with the SA email | SA can list the target folder via Drive API |
| 5 | Create brain-index bucket and grant access (section 1.5) | `gcloud storage ls gs://PROJECT_ID-brain-index` succeeds from SA |
| 6 | Run `deploy.sh` with all env vars set (no `GEMINI_API_KEY` export needed) | All five `gcloud run jobs deploy` commands exit 0 |
| 7 | Add Cloud Storage FUSE volume mounts (section 1.5) | `gcloud run jobs describe bummdidumm-pass2-ocr-index` shows the volume |
| 8 | Execute Pass 1 manually: `gcloud run jobs execute bummdidumm-pass1-delta-dedupe --region europe-west6` | Job status becomes SUCCEEDED; Control Sheet rows appear in `Dedupe_Report` |
| 9 | Execute Pass 2 manually: `gcloud run jobs execute bummdidumm-pass2-ocr-index --region europe-west6` | Job status becomes SUCCEEDED; `CURRENT_personal_brain_stats.json` written to `BRAIN_INDEX_ROOT` |
| 10 | Run tests locally against the deployed index | `pytest bummdidumm_os_v5_final_release/tests/ -q` passes |

---

## 4. Common errors and fixes

### Missing `BRAIN_INDEX_ROOT`

**Symptom:** Pass 2 or Safe Sort fails immediately with:
```
RuntimeError: BRAIN_INDEX_ROOT must be set explicitly when running in Cloud Run
```

**Fix:** Set the `BRAIN_INDEX_ROOT` env var on the Cloud Run Job and attach a
persistent volume (see section 1.5). The error is intentional — omitting the
variable on Cloud Run means the index would be written to ephemeral container
storage and lost when the task exits.

Both `bummdidumm-pass2-ocr-index` and `bummdidumm-safe-sort` require the same
persistent Brain Index mount. `deploy.sh` handles this automatically; if you
deploy or update jobs manually, ensure both jobs have the FUSE volume attached
and `BRAIN_INDEX_ROOT` set to `/brain_index`.

---

### Missing IAM role

**Symptom:** Drive or Sheets API calls fail with HTTP 403:
```
googleapiclient.errors.HttpError: <HttpError 403 when requesting ...
returned "The caller does not have permission">
```

**Fix:** Verify the service account has been granted edit access to the target
Google Sheet and read/write access to all three Drive folders
(`TARGET_FOLDER_ID`, `ARCHIVE_FOLDER_ID`, `INDEX_FOLDER_ID`). These are
per-resource Drive ACL grants, not GCP IAM roles — add the SA email as an
Editor in the Drive sharing dialog or via the Drive API.

---

### 429 from Gemini (rate limit)

**Symptom:** Pass 2 logs show repeated warnings:
```
Gemini rate limit {"code": 429, "sleep_sec": ..., "attempt": ...}
```
or the job exhausts retries and logs:
```
Gemini OCR retries exhausted
```

**Fix (short-term):** Reduce `OCR_BUDGET_PER_RUN` to spread OCR calls across
multiple runs:
```bash
gcloud run jobs update bummdidumm-pass2-ocr-index \
  --update-env-vars=OCR_BUDGET_PER_RUN=50 \
  --region=europe-west6
```

**Fix (rate cap):** Lower `GEMINI_RPM_LIMIT` (default 9) to stay further
below the model's quota:
```bash
gcloud run jobs update bummdidumm-pass2-ocr-index \
  --update-env-vars=GEMINI_RPM_LIMIT=5 \
  --region=europe-west6
```

**Fix (quota):** If you are on the Free Tier (10 RPM limit), consider upgrading
to a paid tier for higher quotas, or switch to a different model by updating
the `model=` argument in `shared/gemini_helpers.py` and adjusting
`GEMINI_RPM_LIMIT` accordingly.

The built-in retry logic uses exponential backoff (3s × 2^attempt, capped at
120s) and will recover from transient 429s automatically. Persistent 429s
indicate sustained quota exhaustion requiring one of the fixes above.

---

### Control Sheet not found or wrong tab name

**Symptom:**
```
googleapiclient.errors.HttpError: <HttpError 400 ... "Unable to parse range">
```

**Fix:** Verify `CONTROL_SHEET_ID` is the correct spreadsheet ID (from the
Drive URL). The sheet must contain tabs named exactly: `Dedupe_Report`,
`Sorting_Suggestions`, `Knowledge_Exclusions`, `Run_Log`, `State`. Create
missing tabs manually or via the included Apps Script in the `appsscript/`
directory.

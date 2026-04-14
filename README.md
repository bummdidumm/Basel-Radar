# bummdidumm-OS V5 Final Release

This repository contains the "bummdidumm-OS V5" pipeline, a modular Python implementation for Google Drive deduplication, folder sorting, OCR processing, and a Personal Brain extraction system. It utilizes Google Cloud Run Jobs for asynchronous processing, Google Sheets for state management, and Google Apps Script as the control plane.

The core implementation is fully self-contained within the `bummdidumm_os_v5_final_release/` directory.

## Pipeline Overview
The system executes in distinct, modular passes:
- **Pass 1:** Initial scan, delta changes, hashing, and deduplication (`main_pass1.py`).
- **Pass 2:** OCR extraction and Personal Brain ingestion (`main_pass2.py` / `personal_brain/runtime.py`).
- **Pass 3 (planned):** Embedding prep for external vector DBs like Qdrant — not yet implemented (`main_pass3_embed_prep.py` does not exist in this release).
- **Safe Sort / Apply Sort:** Rules-based organization and folder management.

### Personal Brain Scope
The `personal_brain/` module handles dynamic knowledge parsing, classifying events/entities into specific tiers (permanent, slow_changing, ephemeral).

**Currently Implemented Outputs:**
- Raw JSONL files for Source Registry, Record Index, Entity Index, and Relation Index.
- A static Profile layer (`10_profile/`, `11_inventory/`) populated securely by distinct parsers.
- A high-level Markdown summary report (`CURRENT_personal_brain_summary.md`).
- A consolidated JSON Master Index (`CURRENT_personal_brain_master_index.json`).
- Daily memory shards (`04_daily_memory/`).
- An LLM Context Pack specifically scaled for Gemini (`gemini_daily_context.json`).

**Not Yet Implemented:**
- No full Obsidian Vault Markdown export (currently only outputs JSON/JSONL schemas and a high-level MD summary).
- Direct API integration with vector DBs (embeddings are prepped into JSONL, but not automatically pushed to Qdrant/Pinecone).

## Local Setup and Installation

### 1. Clone & Environment
```bash
git clone https://github.com/bummdidumm/Basel-Radar.git
cd Basel-Radar

python3 -m venv venv
source venv/bin/activate
```

### 2. Dependencies
For reproducible installs (matches CI and Docker images), use the lock file:
```bash
pip install --no-deps -r bummdidumm_os_v5_final_release/requirements.lock
```
For development with flexible dependency resolution:
```bash
pip install -r bummdidumm_os_v5_final_release/requirements.txt
```

### 3. Pre-Commit Hooks
This repository strictly enforces code quality through pre-commit.
```bash
pip install pre-commit
pre-commit install
```
*Note:* You can manually run the hooks against all files using `pre-commit run --all-files`.

### 4. Testing
Because the core code resides in a subfolder, you must prepend the `PYTHONPATH` when running tests locally.
```bash
PYTHONPATH=bummdidumm_os_v5_final_release pytest bummdidumm_os_v5_final_release/tests/
```

## Governance
Repository governance and finalization protocols are strictly defined to maintain consistency.
- Read [REPO_GOVERNANCE_SETUP.md](REPO_GOVERNANCE_SETUP.md) for GitHub branch protection and review requirements.
- Read [AGENT_FINALIZATION_PROTOCOL.md](AGENT_FINALIZATION_PROTOCOL.md) for automated agent task constraints.

## Cloud Run Environment Variables

The following environment variables **must** be set before running `deploy.sh`. Missing required variables cause the script to abort immediately (`set -euo pipefail`).

| Variable | Required | Description |
|----------|----------|-------------|
| `PROJECT_ID` | Yes | GCP project ID |
| `ARCHIVE_FOLDER_ID` | Yes | Google Drive folder ID for archived duplicates |
| `INDEX_FOLDER_ID` | Yes | Google Drive folder ID for index outputs |
| `CONTROL_SHEET_ID` | Yes | Google Sheets spreadsheet ID for state and reports |
| `GEMINI_API_KEY` | Yes | Gemini API key for OCR / Personal Brain |
| `SA_EMAIL` | Yes | Service account email for Cloud Run jobs |
| `BRAIN_INDEX_ROOT` | Yes (Pass 2 + Safe Sort) | Persistent path for the Personal Brain index |
| `TARGET_FOLDER_ID` | No | Optional Drive folder to scope Pass 1 scanning |
| `REGION` | No | Cloud Run region (default: `europe-west6`) |
| `SKIP_OVER_MB` | No | Skip files larger than this MB (default: 500) |
| `OCR_BUDGET_PER_RUN` | No | Max OCR calls per Pass 2 run (default: 500) |

### BRAIN_INDEX_ROOT

- **Mandatory for Pass 2 and Safe Sort in Cloud Run.**
- Must point to a persistent path — a mounted volume, a Cloud Storage FUSE mount, or a deliberately managed directory.
- `main_pass2.py` raises `RuntimeError` at startup if `BRAIN_INDEX_ROOT` is not set when `K_SERVICE` is detected (i.e. running in Cloud Run).
- Without a persistent mount, the brain index is lost on container restart.
- Example: a Cloud Storage FUSE-mounted path like `/mnt/brain_index`.

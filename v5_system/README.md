# bummdidumm-OS V5

Dies ist die produktionsfertige Implementierung des "bummdidumm-OS" V5 Masterplans.
Es ist eine Idempotente, robute Zwei-Pass-Pipeline zur Deduplizierung und KI-gestützten Textextraktion von Google Drive Dateien.

## Setup Google Sheet

Dein Control Sheet muss folgende Tabs (Namen) enthalten:

1. `State`: A1="Start Token", A2="In-Progress Token", A3="Phase". (Die B-Spalte bleibt leer für die Skript-Daten).
2. `Hash_Index`: A1="SHA256", B1="Original_File_ID"
3. `Dedupe_Report`
4. `Duplicate_Groups`
5. `Error_Report`
6. `Run_Log`

## Deployment auf Cloud Run Jobs

1. Projekt setzen:
```bash
gcloud config set project DEIN_PROJEKT_ID
```

2. Service Account für den Job erstellen:
```bash
gcloud iam service-accounts create bummdidumm-runner \
    --display-name="Bummdidumm Job Runner"
```

3. Dem Service Account Zugriff auf dein Google Sheet und deine Drive-Ordner geben (via Freigabe-Dialog in Google Drive/Sheets).

4. Deployen:
```bash
gcloud run jobs deploy bummdidumm-job \
  --source . \
  --region us-central1 \
  --service-account=bummdidumm-runner@DEIN_PROJEKT_ID.iam.gserviceaccount.com \
  --set-env-vars="TARGET_FOLDER_ID=DEIN_TARGET,ARCHIVE_FOLDER_ID=DEIN_ARCHIVE,INDEX_FOLDER_ID=DEIN_INDEX,CONTROL_SHEET_ID=DEIN_SHEET,PROJECT_SLUG=bummdidumm,GEMINI_API_KEY=DEIN_KEY" \
  --max-retries=0 \
  --tasks=1 \
  --cpu=1 \
  --memory=2Gi \
  --task-timeout=3600s
```

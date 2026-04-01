// Control Plane für Bummdidumm V5

const PROJECT_ID = "DEIN_PROJEKT_ID";
const REGION = "us-central1";

function triggerJob(jobName) {
  const url = `https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${jobName}:run`;

  const res = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: "Bearer " + ScriptApp.getOAuthToken()
    },
    muteHttpExceptions: true,
    payload: JSON.stringify({})
  });

  const code = res.getResponseCode();
  const body = res.getContentText();

  if (code >= 200 && code < 300) {
    SpreadsheetApp.getUi().alert(`✅ ${jobName} wurde erfolgreich gestartet.`);
  } else {
    SpreadsheetApp.getUi().alert(`❌ Fehler beim Starten von ${jobName}:\nCode: ${code}\nResponse: ${body}`);
  }
}

function startFastDeltaScan() {
  triggerJob("bummdidumm-pass1-delta-dedupe");
}

function startOcrIndexing() {
  triggerJob("bummdidumm-pass2-ocr-index");
}

function startApplyRenames() {
  triggerJob("bummdidumm-apply-renames");
}

function startFullRun() {
  // Option A: Pass 1 startet und Pass 2 wird nachgelagert extern aufgerufen.
  // Option B: Wir triggern beide, aber Cloud Run blockiert nicht.
  // Für eine saubere Pipeline sollte Pass 2 über ein Event (PubSub) von Pass 1 gestartet werden.
  // In dieser Sheet-UI lösen wir für "Kompletten Lauf" einen Warnhinweis aus.
  SpreadsheetApp.getUi().alert(
    "Der komplette Lauf muss aktuell zweistufig manuell geklickt werden, " +
    "um saubere Idempotenz zu garantieren. Bitte starte erst 'Delta-Scan', warte " +
    "bis er fertig ist (siehe Run_Log), und starte dann 'OCR & Indexing'."
  );
}

function clearErrorReports() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.alert('Warnung', 'Bist du sicher, dass du alle Error Reports leeren willst?', ui.ButtonSet.YES_NO);
  if (response == ui.Button.YES) {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Error_Report");
    if(sheet) {
      const lastRow = sheet.getLastRow();
      if(lastRow > 1) {
        sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).clearContent();
        ui.alert("Error Report wurde geleert.");
      } else {
         ui.alert("Error Report ist bereits leer.");
      }
    }
  }
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🚀 bummdidumm OS")
    .addItem("1. Fast Delta-Scan starten", "startFastDeltaScan")
    .addItem("2. OCR & Indexing starten", "startOcrIndexing")
    .addItem("3. Rename-Vorschläge anwenden", "startApplyRenames")
    .addSeparator()
    .addItem("🔄 Kompletten Lauf starten", "startFullRun")
    .addItem("🗑️ Error Reports leeren", "clearErrorReports")
    .addToUi();
}
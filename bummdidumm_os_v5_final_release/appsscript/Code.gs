// Control Plane für Bummdidumm V5

const REGION = "us-central1";

function getProjectId() {
  const props = PropertiesService.getScriptProperties();
  let projectId = props.getProperty("PROJECT_ID");
  if (!projectId) {
    const ui = SpreadsheetApp.getUi();
    const res = ui.prompt("Konfiguration fehlt", "Bitte gib deine Google Cloud PROJECT_ID ein:", ui.ButtonSet.OK_CANCEL);
    if (res.getSelectedButton() === ui.Button.OK) {
      projectId = res.getResponseText().trim();
      props.setProperty("PROJECT_ID", projectId);
    } else {
      throw new Error("Abbruch: PROJECT_ID wird für Cloud Run Aufrufe zwingend benötigt.");
    }
  }
  return projectId;
}

function triggerJob(jobName) {
  const projectId = getProjectId();
  const url = `https://run.googleapis.com/v2/projects/${projectId}/locations/${REGION}/jobs/${jobName}:run`;

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
    return {success: true, msg: `✅ ${jobName} wurde erfolgreich gestartet.`};
  } else {
    return {success: false, msg: `❌ Fehler beim Starten von ${jobName}:\nCode: ${code}\nResponse: ${body}`};
  }
}

function startFastDeltaScan() {
  const res = triggerJob("bummdidumm-pass1-delta-dedupe");
  SpreadsheetApp.getUi().alert(res.msg);
}

function startOcrIndexing() {
  const res = triggerJob("bummdidumm-pass2-ocr-index");
  SpreadsheetApp.getUi().alert(res.msg);
}

function startApplyRenames() {
  const res = triggerJob("bummdidumm-apply-renames");
  SpreadsheetApp.getUi().alert(res.msg);
}

function checkAndStartPass2() {
  const props = PropertiesService.getScriptProperties();
  let checks = parseInt(props.getProperty("POLL_ATTEMPTS") || "0");
  const runId = props.getProperty("FULL_RUN_RUN_ID") || "UNKNOWN_RUN";

  // Timeout-Schutz nach 12 Checks (60 Minuten bei 5-Min-Takt)
  if (checks >= 12) {
    deleteMyTriggers();
    console.error("Pass 1 Polling Timeout: 60 Minuten überschritten. Trigger gelöscht.");

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Error_Report");
    if(sheet) {
       sheet.appendRow([
         new Date().toISOString(),
         runId,
         "TRIGGER",
         "SYSTEM",
         "N/A",
         "Timeout",
         "Pass 1 hat nicht innerhalb von 60 Minuten erfolgreich gemeldet. Automatische Pass 2 Auslösung wurde abgebrochen."
       ]);
    }

    // Optional: Setze State auf Error, damit das UI nicht mehr auf Pass 2 wartet
    updateStateValue("current_phase", "POLLING_TIMEOUT");
    return;
  }

  props.setProperty("POLL_ATTEMPTS", (checks + 1).toString());

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("State");
  if (!sheet) return;

  const data = sheet.getRange("A:B").getValues();
  let phase = "";
  for (let i = 0; i < data.length; i++) {
    if (data[i][0] === "current_phase") {
      phase = data[i][1];
      break;
    }
  }

  if (phase === "PASS1_DONE") {
    triggerJob("bummdidumm-pass2-ocr-index");
    deleteMyTriggers();
    updateStateValue("current_phase", "PASS2_TRIGGERED");
  } else if (phase === "PASS1_FAILED" || phase === "PASS2_FAILED") {
    deleteMyTriggers();
  }
}

function updateStateValue(key, value) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("State");
  if (!sheet) return;
  const data = sheet.getRange("A:B").getValues();
  for (let i = 0; i < data.length; i++) {
    if (data[i][0] === key) {
      sheet.getRange(i + 1, 2).setValue(value);
      return;
    }
  }
  // Wenn Key nicht existiert
  sheet.appendRow([key, value]);
}

function deleteMyTriggers() {
  // Löscht gezielt nur die Workflow-Trigger dieses Projekts und bereinigt den State
  const triggers = ScriptApp.getProjectTriggers();
  let count = 0;
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "checkAndStartPass2") {
      ScriptApp.deleteTrigger(triggers[i]);
      count++;
    }
  }

  const props = PropertiesService.getScriptProperties();
  props.deleteProperty("POLL_ATTEMPTS");
  props.deleteProperty("FULL_RUN_STARTED_AT");
  props.deleteProperty("FULL_RUN_RUN_ID");
  props.deleteProperty("FULL_RUN_PHASE");

  return count;
}

function emergencyStopAllTriggers() {
  const count = deleteMyTriggers();
  updateStateValue("current_phase", "EMERGENCY_STOP");
  SpreadsheetApp.getActiveSpreadsheet().toast(
    `✅ ${count} Hintergrund-Trigger sowie State-Properties wurden gelöscht.`,
    "Notbremse ausgelöst",
    5
  );
}

function autoCleanupTransientFolder() {
  // Optionale Konfiguration: Die ID des Transient-Ordners
  const TRANSIENT_FOLDER_ID = PropertiesService.getScriptProperties().getProperty("TRANSIENT_FOLDER_ID");
  if (!TRANSIENT_FOLDER_ID) {
    console.warn("Auto-Cleanup übersprungen: TRANSIENT_FOLDER_ID nicht in den Script Properties gesetzt.");
    return;
  }

  const retentionDays = parseInt(PropertiesService.getScriptProperties().getProperty("TRANSIENT_RETENTION_DAYS") || "7", 10);
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - retentionDays);

  try {
    const folder = DriveApp.getFolderById(TRANSIENT_FOLDER_ID);
    const files = folder.getFiles();
    let trashedCount = 0;

    while (files.hasNext()) {
      const file = files.next();
      if (file.getLastUpdated() < cutoffDate) {
        file.setTrashed(true);
        trashedCount++;
      }
    }

    if(trashedCount > 0) {
      console.log(`Auto-Cleanup erfolgreich: ${trashedCount} Dateien aus dem Transient-Ordner in den Papierkorb verschoben (Älter als ${retentionDays} Tage).`);
    }
  } catch(e) {
    console.error(`Fehler beim Auto-Cleanup des Transient-Ordners: ${e.toString()}`);
  }
}

function initializeFolderStructure() {
  const ui = SpreadsheetApp.getUi();
  const folderIdStr = ui.prompt("Root Ordner ID eingeben", "Bitte kopiere die ID des obersten 'bummdidumm' Ordners hier rein:", ui.ButtonSet.OK_CANCEL).getResponseText();

  if(!folderIdStr) return;

  const folders = [
    "00_inbox",
    "01_inbox_trash",
    "10_decisions",
    "20_index",
    "30_scripts",
    "40_docs",
    "40_docs/40a_obsidian_sync",
    "40_docs/40b_referenzen",
    "40_docs/40c_projekte",
    "50_media",
    "50_media/50a_fotos",
    "50_media/50b_videos",
    "50_media/50c_audio",
    "60_software",
    "90_logs",
    "98_alte_projekte",
    "99_quarantine",
    "99_archive"
  ];

  let sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Folder_Registry");
  if (!sheet) {
    sheet = SpreadsheetApp.getActiveSpreadsheet().insertSheet("Folder_Registry");
    sheet.appendRow(["folder_key", "folder_name", "folder_id", "parent_folder_id", "full_path"]);
  } else if (sheet.getLastRow() === 0) {
    sheet.appendRow(["folder_key", "folder_name", "folder_id", "parent_folder_id", "full_path"]);
  }

  try {
    const root = DriveApp.getFolderById(folderIdStr);
    const registryRows = [];

    // Helfer für rekursives Erzeugen
    const createOrGet = (parent, name, fullPath) => {
      let folderId = "";
      const it = parent.getFoldersByName(name);
      if(it.hasNext()) {
        const existing = it.next();
        folderId = existing.getId();
      } else {
        const newFolder = parent.createFolder(name);
        folderId = newFolder.getId();
      }

      registryRows.push([name, name, folderId, parent.getId(), fullPath]);
      // Return a DriveApp Folder object wrapper for further recursion
      return { getId: () => folderId, getFoldersByName: (n) => DriveApp.getFolderById(folderId).getFoldersByName(n), createFolder: (n) => DriveApp.getFolderById(folderId).createFolder(n) };
    };

    registryRows.push(["root", root.getName(), folderIdStr, "N/A", "/"]);

    // Baue Baum
    for(let f of folders) {
      if(f.includes("/")) {
        const parts = f.split("/");
        const parent = createOrGet(root, parts[0], `/${parts[0]}`);
        createOrGet(parent, parts[1], `/${parts[0]}/${parts[1]}`);
      } else {
        createOrGet(root, f, `/${f}`);
      }
    }

    // Alte Map löschen
    if (sheet.getLastRow() > 1) {
      sheet.getRange(2, 1, sheet.getLastRow() - 1, 5).clearContent();
    }

    // Neue Map speichern
    sheet.getRange(2, 1, registryRows.length, 5).setValues(registryRows);

    ui.alert("✅ Ordnerstruktur erfolgreich initialisiert!\nDie Folder-IDs wurden im 'Folder_Registry' Tab gespeichert.");

  } catch(e) {
    ui.alert("❌ Fehler beim Initialisieren: " + e.toString());
  }
}

function startSafeSort() {
  const res = triggerJob("bummdidumm-safe-sort");
  SpreadsheetApp.getUi().alert(res.msg);
}

function startApplySort() {
  const ui = SpreadsheetApp.getUi();
  const confirmation = ui.alert("Bestätigen", "Bist du sicher, dass du die Vorschläge aus dem 'Sorting_Suggestions' Tab jetzt in Google Drive verschieben möchtest?", ui.ButtonSet.YES_NO);

  if (confirmation == ui.Button.YES) {
    const res = triggerJob("bummdidumm-apply-sort");
    ui.alert(res.msg);
  }
}

function startFullRun() {
  const ui = SpreadsheetApp.getUi();

  // Stelle sicher, dass keine Parallel-Poller existieren
  deleteMyTriggers();

  // 1. Trigger Pass 1
  const res = triggerJob("bummdidumm-pass1-delta-dedupe");
  if(res.success) {
      const props = PropertiesService.getScriptProperties();
      props.setProperty("POLL_ATTEMPTS", "0");
      props.setProperty("FULL_RUN_STARTED_AT", new Date().toISOString());
      props.setProperty("FULL_RUN_RUN_ID", "run_" + new Date().toISOString().replace(/[-:T]/g,"").slice(0,14));
      props.setProperty("FULL_RUN_PHASE", "WAITING_FOR_PASS1");

      // 2. Setze einen zeitgesteuerten Trigger, der alle 5 Minuten prüft, ob Pass 1 fertig ist.
      ScriptApp.newTrigger("checkAndStartPass2")
               .timeBased()
               .everyMinutes(5)
               .create();

      ui.alert(
        "✅ Kompletter Lauf gestartet.\n\n" +
        "Pass 1 (Delta & Dedupe) läuft jetzt. Ein Hintergrund-Trigger prüft alle 5 Minuten den Status im 'State'-Tab. " +
        "Sobald Pass 1 den Status 'PASS1_DONE' erreicht, wird Pass 2 (OCR & Index) automatisch gestartet. " +
        "(Maximales Polling: 60 Minuten, danach automatischer Abbruch)."
      );
  } else {
      ui.alert(res.msg);
  }
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
    } else {
      ui.alert("Tab 'Error_Report' nicht gefunden.");
    }
  }
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🚀 bummdidumm OS")
    .addItem("Ordnerstruktur initialisieren", "initializeFolderStructure")
    .addSeparator()
    .addItem("1. Fast Delta-Scan starten", "startFastDeltaScan")
    .addItem("2. OCR & Indexing starten", "startOcrIndexing")
    .addItem("3. Rename-Vorschläge anwenden", "startApplyRenames")
    .addSeparator()
    .addItem("4. Sortier-Vorschläge erzeugen (Safe Mode)", "startSafeSort")
    .addItem("5. Sortierung anwenden (Apply Mode)", "startApplySort")
    .addSeparator()
    .addItem("🔄 Kompletten Lauf starten", "startFullRun")
    .addItem("🗑️ Error Reports leeren", "clearErrorReports")
    .addSeparator()
    .addItem("🛑 NOTBREMSE: Alle Hintergrund-Trigger stoppen", "emergencyStopAllTriggers")
    .addToUi();
}
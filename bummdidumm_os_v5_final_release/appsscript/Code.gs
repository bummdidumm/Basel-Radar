// Control Plane für bummdidumm-OS V5

function getRegion() {
  const props = PropertiesService.getScriptProperties();
  return props.getProperty("REGION") || "europe-west6";
}

function getProjectId() {
  const props = PropertiesService.getScriptProperties();
  const projectId = props.getProperty("PROJECT_ID");
  if (!projectId) throw new Error("PROJECT_ID fehlt in Script Properties.");
  return projectId;
}

function triggerJob(jobName) {
  const projectId = getProjectId();
  const region = getRegion();
  const url = `https://run.googleapis.com/v2/projects/${projectId}/locations/${region}/jobs/${jobName}:run`;
  const res = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + ScriptApp.getOAuthToken() },
    muteHttpExceptions: true,
    payload: JSON.stringify({})
  });
  const code = res.getResponseCode();
  const body = res.getContentText();
  return (code >= 200 && code < 300)
    ? { success: true, msg: `✅ ${jobName} wurde erfolgreich gestartet.` }
    : { success: false, msg: `❌ Fehler beim Starten von ${jobName}:\nCode: ${code}\nResponse: ${body}` };
}

function ensureFolderRegistrySheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("Folder_Registry");
  if (!sheet) sheet = ss.insertSheet("Folder_Registry");
  if (sheet.getLastRow() === 0) sheet.appendRow(["folder_key", "folder_name", "folder_id", "parent_folder_id", "full_path"]);
  return sheet;
}

function createOrGetFolder(parent, name) {
  const it = parent.getFoldersByName(name);
  return it.hasNext() ? it.next() : parent.createFolder(name);
}

function initializeFolderStructure() {
  const props = PropertiesService.getScriptProperties();
  const rootName = props.getProperty("ROOT_FOLDER_NAME") || "bummdidumm";
  const root = createOrGetFolder(DriveApp.getRootFolder(), rootName);
  const definitions = [
    ["00_inbox", "00_inbox"], ["01_inbox_trash", "01_inbox_trash"], ["10_decisions", "10_decisions"],
    ["20_index", "20_index"], ["30_scripts", "30_scripts"], ["40_docs", "40_docs"],
    ["40a_obsidian_sync", "40_docs/40a_obsidian_sync"], ["40b_referenzen", "40_docs/40b_referenzen"],
    ["40c_projekte", "40_docs/40c_projekte"], ["50_media", "50_media"],
    ["50a_fotos", "50_media/50a_fotos"], ["50b_videos", "50_media/50b_videos"],
    ["50c_audio", "50_media/50c_audio"], ["60_software", "60_software"], ["90_logs", "90_logs"],
    ["98_alte_projekte", "98_alte_projekte"], ["99_quarantine", "99_quarantine"], ["99_archive", "99_archive"]
  ];

  const sheet = ensureFolderRegistrySheet();
  const rows = [["root", rootName, root.getId(), "N/A", "/"]];
  const cache = { "": root };

  definitions.forEach(([key, relPath]) => {
    const parts = relPath.split("/");
    let parentPath = "";
    let parent = root;
    parts.forEach((part, i) => {
      const currentPath = (parentPath ? parentPath + "/" : "") + part;
      if (!cache[currentPath]) cache[currentPath] = createOrGetFolder(parent, part);
      parent = cache[currentPath];
      parentPath = currentPath;
      if (i === parts.length - 1) {
        const parentFolderId = parts.length === 1 ? root.getId() : cache[parts.slice(0, -1).join("/")].getId();
        rows.push([key, part, parent.getId(), parentFolderId, `/${currentPath}`]);
      }
    });
  });

  if (sheet.getLastRow() > 1) sheet.getRange(2, 1, sheet.getLastRow() - 1, 5).clearContent();
  sheet.getRange(2, 1, rows.length, 5).setValues(rows);
  SpreadsheetApp.getActiveSpreadsheet().toast("Ordnerstruktur initialisiert.", "bummdidumm", 5);
}

function updateStateValue(key, value) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("State");
  if (!sheet) return;
  const data = sheet.getRange("A:B").getValues();
  for (let i = 0; i < data.length; i++) if (data[i][0] === key) return sheet.getRange(i + 1, 2).setValue(value);
  sheet.appendRow([key, value]);
}

function deleteMyTriggers() {
  const handlers = ["checkAndStartPass2"];
  let count = 0;
  ScriptApp.getProjectTriggers().forEach((t) => {
    if (handlers.indexOf(t.getHandlerFunction()) !== -1) { ScriptApp.deleteTrigger(t); count++; }
  });
  const props = PropertiesService.getScriptProperties();
  ["POLL_ATTEMPTS", "FULL_RUN_STARTED_AT", "FULL_RUN_RUN_ID", "FULL_RUN_PHASE"].forEach((k) => props.deleteProperty(k));
  return count;
}

function ensurePollingTrigger() {
  const existing = ScriptApp.getProjectTriggers().filter((t) => t.getHandlerFunction() === "checkAndStartPass2");
  if (existing.length > 0) return;
  ScriptApp.newTrigger("checkAndStartPass2").timeBased().everyMinutes(5).create();
}

function checkAndStartPass2() {
  const props = PropertiesService.getScriptProperties();
  const checks = parseInt(props.getProperty("POLL_ATTEMPTS") || "0", 10);
  if (checks >= 12) {
    deleteMyTriggers();
    updateStateValue("current_phase", "POLLING_TIMEOUT");
    return;
  }
  props.setProperty("POLL_ATTEMPTS", String(checks + 1));

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("State");
  if (!sheet) return;
  const data = sheet.getRange("A:B").getValues();
  const phaseRow = data.find((r) => r[0] === "current_phase");
  const phase = phaseRow ? phaseRow[1] : "";

  if (phase === "PASS1_DONE") {
    triggerJob("bummdidumm-pass2-ocr-index");
    deleteMyTriggers();
    updateStateValue("current_phase", "PASS2_TRIGGERED");
  } else if (phase === "PASS1_FAILED" || phase === "PASS2_FAILED") {
    deleteMyTriggers();
  }
}

function emergencyStopAllTriggers() {
  const count = deleteMyTriggers();
  updateStateValue("current_phase", "EMERGENCY_STOP");
  SpreadsheetApp.getActiveSpreadsheet().toast(`✅ ${count} Hintergrund-Trigger wurden entfernt.`, "Notbremse", 5);
}

function autoCleanupTransientFolder() {
  const props = PropertiesService.getScriptProperties();
  const transientFolderId = props.getProperty("TRANSIENT_FOLDER_ID");
  if (!transientFolderId) return;
  const retentionDays = parseInt(props.getProperty("TRANSIENT_RETENTION_DAYS") || "7", 10);
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - retentionDays);
  const files = DriveApp.getFolderById(transientFolderId).getFiles();
  while (files.hasNext()) {
    const file = files.next();
    if (file.getLastUpdated() < cutoffDate) file.setTrashed(true);
  }
}

function handleJobAlert(jobName) {
  const res = triggerJob(jobName);
  if (res.success) SpreadsheetApp.getActiveSpreadsheet().toast(res.msg, "bummdidumm", 5);
  else SpreadsheetApp.getUi().alert(res.msg);
}

function startFastDeltaScan() { handleJobAlert("bummdidumm-pass1-delta-dedupe"); }
function startOcrIndexing() { handleJobAlert("bummdidumm-pass2-ocr-index"); }

function startApplyRenames() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.alert('Bestätigung', 'Bist du sicher, dass du die Renames anwenden willst? (Destruktiv)', ui.ButtonSet.YES_NO);
  if (response === ui.Button.YES) {
    handleJobAlert("bummdidumm-apply-renames");
  }
}

function startSafeSort() { handleJobAlert("bummdidumm-safe-sort"); }

function startApplySort() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.alert('Bestätigung', 'Bist du sicher, dass du die Sortierung anwenden willst? (Destruktiv)', ui.ButtonSet.YES_NO);
  if (response === ui.Button.YES) {
    handleJobAlert("bummdidumm-apply-sort");
  }
}

function startFullRun() {
  const res = triggerJob("bummdidumm-pass1-delta-dedupe");
  if (!res.success) return SpreadsheetApp.getUi().alert(res.msg);
  const props = PropertiesService.getScriptProperties();
  deleteMyTriggers();
  props.setProperty("POLL_ATTEMPTS", "0");
  props.setProperty("FULL_RUN_STARTED_AT", new Date().toISOString());
  props.setProperty("FULL_RUN_RUN_ID", "run_" + new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14));
  props.setProperty("FULL_RUN_PHASE", "WAITING_FOR_PASS1");
  ensurePollingTrigger();
  SpreadsheetApp.getActiveSpreadsheet().toast("✅ Kompletter Lauf gestartet.", "bummdidumm", 5);
}

function clearErrorReports() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.alert('Bestätigung', 'Bist du sicher, dass du die Error Reports leeren willst? (Destruktiv)', ui.ButtonSet.YES_NO);
  if (response === ui.Button.YES) {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Error_Report");
    if (!sheet || sheet.getLastRow() <= 1) return;
    sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn()).clearContent();
    SpreadsheetApp.getActiveSpreadsheet().toast("✅ Error Reports geleert.", "bummdidumm", 5);
  }
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu("🚀 bummdidumm OS")
    .addItem("Ordnerstruktur initialisieren", "initializeFolderStructure")
    .addSeparator()
    .addItem("Fast Delta-Scan starten", "startFastDeltaScan")
    .addItem("OCR & Indexing starten", "startOcrIndexing")
    .addItem("Renames anwenden", "startApplyRenames")
    .addSeparator()
    .addItem("Sortier-Vorschläge erzeugen", "startSafeSort")
    .addItem("Sortierung anwenden", "startApplySort")
    .addSeparator()
    .addItem("Kompletten Lauf starten", "startFullRun")
    .addItem("Error Reports leeren", "clearErrorReports")
    .addSeparator()
    .addItem("NOTBREMSE: Alle Hintergrund-Trigger stoppen", "emergencyStopAllTriggers")
    .addToUi();
}

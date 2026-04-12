
## 2024-05-18 - Non-blocking UX notifications in Apps Script
**Learning:** Google Sheets Apps Script Add-ons can quickly become annoying if users have to click "OK" on standard UI alerts (`SpreadsheetApp.getUi().alert()`) for every successful background job trigger. Using `SpreadsheetApp.getActiveSpreadsheet().toast()` provides a smoother, non-blocking notification that automatically dismisses itself.
**Action:** Always prefer `.toast()` for routine success confirmations in Apps Script, while reserving `.alert()` for actual errors where user acknowledgement is critical.

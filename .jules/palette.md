## 2024-04-14 - Destructive Action Confirmation

**Learning:** Destructive Google Workspace actions triggered by custom menus (e.g., file renaming, applying sorts, clearing error reports) can lead to accidental data loss if invoked by a mistaken click.

**Action:** Always add YES/NO confirmations via `SpreadsheetApp.getUi().alert()` before executing destructive Google Workspace actions triggered by custom menus.
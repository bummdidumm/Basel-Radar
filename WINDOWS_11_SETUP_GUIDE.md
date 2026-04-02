# bummdidumm-OS V5 - Schritt-für-Schritt Anleitung für Windows 11

Herzlich willkommen! Diese Anleitung führt dich Schritt für Schritt durch die Installation und Einrichtung von **bummdidumm-OS V5** auf deinem Windows 11 PC. Du brauchst keine besonderen Programmierkenntnisse, folge einfach diesen Anweisungen genau.

---

## 🛠️ Schritt 1: Vorbereitungen auf deinem PC (Was du installieren musst)

Bevor wir starten, brauchen wir ein paar Programme auf deinem Computer.

### 1. Python installieren
Python ist die Sprache, in der dieses Programm geschrieben ist.
1. Öffne deinen Internetbrowser und gehe auf: [python.org/downloads](https://www.python.org/downloads/)
2. Klicke auf den gelben Button **"Download Python 3.1x.x"** (die aktuellste Version).
3. Öffne die heruntergeladene Datei (meist in deinem "Downloads" Ordner).
4. ⚠️ **Ganz wichtig!** Setze im allerersten Fenster ganz unten ein Häkchen bei **"Add python.exe to PATH"**!
5. Klicke dann auf **"Install Now"** und warte, bis die Installation fertig ist. Klicke danach auf "Close".

### 2. Git installieren (Optional, aber hilfreich)
Damit kannst du den Code einfach auf deinen PC laden.
1. Gehe auf: [git-scm.com/download/win](https://git-scm.com/download/win)
2. Klicke auf **"64-bit Git for Windows Setup"**.
3. Öffne die Datei und klicke dich durch die Installation (du kannst immer einfach auf "Next" bzw. "Weiter" klicken, die Standardeinstellungen sind perfekt).

---

## 📁 Schritt 2: Den Code auf deinen PC laden

Jetzt holen wir das Programm auf deinen Computer.

1. Öffne einen Ordner, in dem du das Programm speichern möchtest (z.B. in deinen "Dokumenten").
2. Mache in diesem Ordner einen **Rechtsklick** an eine freie Stelle und wähle **"In Terminal öffnen"** (bei Windows 11 oft direkt sichtbar oder unter "Weitere Optionen anzeigen").
3. Es öffnet sich ein schwarzes (oder blaues) Fenster. Tippe dort den folgenden Befehl ein (falls du den Code von GitHub hast):
   ```cmd
   git clone https://github.com/dein-benutzername/dein-repo-name.git
   ```
   *(Ersetze den Link durch den echten Link zu diesem Projekt, falls du ihn hast. Ansonsten kannst du das Projekt auch als ZIP-Datei herunterladen, entpacken und dann den entpackten Ordner im Terminal öffnen).*
4. Gehe in den Ordner des Projekts:
   ```cmd
   cd bummdidumm_os_v5_final_release
   ```

---

## 📦 Schritt 3: Das Programm vorbereiten

Jetzt sagen wir Python, dass es alle nötigen Hilfsprogramme für bummdidumm-OS laden soll.

1. Stelle sicher, dass du im schwarzen Fenster (Terminal) im Ordner `bummdidumm_os_v5_final_release` bist.
2. Tippe folgenden Befehl ein und drücke Enter:
   ```cmd
   pip install -r requirements.txt
   ```
3. Dein PC wird nun einige Dinge aus dem Internet herunterladen. Warte, bis der Vorgang komplett abgeschlossen ist (das dauert ein bis zwei Minuten).

---

## ☁️ Schritt 4: Google Cloud vorbereiten (Die Schaltzentrale)

Das Programm arbeitet mit Google Drive. Dafür müssen wir Google sagen, dass das okay ist.

1. Gehe auf die [Google Cloud Console](https://console.cloud.google.com/). Melde dich mit deinem Google-Konto an.
2. Klicke oben links (neben dem Google Cloud Logo) auf das Dropdown-Menü und dann auf **"Neues Projekt"**.
3. Gib dem Projekt einen Namen (z.B. "bummdidumm-v5") und klicke auf **"Erstellen"**.
4. Wähle das neue Projekt oben im Dropdown-Menü aus.
5. Gehe links im Menü auf **"APIs und Dienste"** > **"Bibliothek"**.
6. Suche nach den folgenden drei APIs, klicke sie an und drücke auf **"Aktivieren"**:
   - **Google Drive API**
   - **Google Sheets API**
   - **Cloud Run Admin API**

### Den Service-Account (den "Roboter-Benutzer") erstellen:
1. Gehe im Menü links auf **"IAM und Verwaltung"** > **"Dienstkonten"** (Service Accounts).
2. Klicke oben auf **"+ DIENSTKONTO ERSTELLEN"**.
3. Gib einen Namen ein (z.B. "bummdidumm-bot") und klicke auf "Erstellen und Fortfahren".
4. Jetzt braucht der Bot Rechte. Füge folgende Rollen hinzu (über das Suchfeld):
   - `Google Drive-Administrator` (oder Editor)
   - `Bearbeiter` (für Google Sheets)
   - `Cloud Run-Entwickler`
   - `Dienstkontonutzer` (Service Account User)
5. Klicke auf **"Fertig"**.
6. Klicke nun auf die E-Mail-Adresse des gerade erstellten Dienstkontos.
7. Gehe auf den Reiter **"Schlüssel"** > **"Schlüssel hinzufügen"** > **"Neuen Schlüssel erstellen"**.
8. Wähle **"JSON"** und klicke auf **"Erstellen"**.
9. **WICHTIG:** Es wird eine Datei auf deinen PC heruntergeladen. Behandle diese Datei wie ein Passwort! Verliere sie nicht und gib sie nicht weiter.

---

## 🚀 Schritt 5: Das Programm starten

Um das Programm nun auszuführen, müssen wir ihm sagen, wo es arbeiten soll (welche Ordner in deinem Google Drive) und wie sein "Ausweis" (der JSON-Schlüssel) heißt.

1. Erstelle eine leere Google Tabelle (Google Sheets) in deinem Drive. Diese wird unser "Control-Sheet". Kopiere die ID aus der URL. (Die ID ist der lange Buchstabensalat zwischen `/d/` und `/edit`).
2. Du benötigst auch die IDs von deinen Zielordnern in Google Drive (z.B. "Zielordner", "Archiv", "Index"). Auch hier: Die ID ist das am Ende der URL, wenn du den Ordner im Browser öffnest.

### Unter Windows alles zusammenfügen
Da wir unter Windows sind, nutzen wir am besten die sogenannten Umgebungsvariablen im Terminal (PowerShell), bevor wir das Script starten.

1. Öffne wieder dein Terminal (PowerShell) im Projektordner.
2. Setze die Variablen, indem du diese Befehle (mit deinen echten IDs und dem Pfad zu deiner JSON-Datei!) eintippst:
   ```powershell
   $env:PROJECT_ID="deine-google-cloud-projekt-id"
   $env:TARGET_FOLDER_ID="id-deines-zielordners"
   $env:ARCHIVE_FOLDER_ID="id-deines-archivordners"
   $env:INDEX_FOLDER_ID="id-deines-indexordners"
   $env:CONTROL_SHEET_ID="id-deiner-google-tabelle"
   $env:GEMINI_API_KEY="dein-gemini-schlüssel-falls-benötigt"
   $env:GOOGLE_APPLICATION_CREDENTIALS="C:\Pfad\zu\deiner\heruntergeladenen\schluessel.json"
   ```
3. Jetzt kannst du das Hauptprogramm (z.B. Pass 1) starten:
   ```powershell
   python bummdidumm_os_v5_final_release/main_pass1.py
   ```

🎉 **Herzlichen Glückwunsch!** Das System sollte jetzt starten. Du kannst in deiner Google Tabelle (Control-Sheet) sehen, wie sich die Daten füllen.

---

## 💡 Troubleshooting (Wenn etwas nicht klappt)

* **"python wurde nicht gefunden"**: Du hast bei Schritt 1 wahrscheinlich vergessen, das Häkchen bei "Add python.exe to PATH" zu setzen. Installiere Python noch einmal und achte auf das Häkchen.
* **"pip command not found"**: Gleiches Problem wie bei Python.
* **Das Programm hat keinen Zugriff auf Drive**: Hast du den Google Drive Ordnern erlaubt, dass der Service-Account (die E-Mail-Adresse aus Schritt 4) darauf zugreifen darf? Teile den Ordner in Google Drive mit dieser "Roboter-E-Mail-Adresse".

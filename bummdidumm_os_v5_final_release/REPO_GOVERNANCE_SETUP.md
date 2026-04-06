# Repository Governance Setup

Zur Sicherstellung der Stabilität und Konsistenz dieses Repositories müssen die folgenden GitHub Branch-Protection-Regeln für den `main` Branch manuell in den GitHub Repository Settings aktiviert werden.

## Required Branch Protection Rules

Bitte navigieren Sie zu **Settings > Branches > Add branch protection rule** und konfigurieren Sie Folgendes für das Muster `main`:

1. **Require pull request reviews before merging:**
   - Dies stellt sicher, dass kein Code ohne Vier-Augen-Prinzip in den Hauptbranch gelangt.
2. **Require status checks to pass before merging:**
   - Aktivieren Sie dies und wählen Sie die CI-Workflows aus (z.B. `lint-and-hooks`, `personal-brain-tests`).
   - Dies verhindert das Mergen von fehlerhaftem Code oder Code, der die Pre-Commit-Formatierung verletzt.
3. **Include administrators:**
   - Administratoren dürfen die Regeln nicht umgehen, um absolute Konsistenz zu gewährleisten.
4. **Require linear history:**
   - Merge-Commits sind zu vermeiden (Squash-and-Merge bevorzugen), um eine saubere und nachvollziehbare Git-Historie zu behalten.

Die Einhaltung des `AGENT_FINALIZATION_PROTOCOL.md` wird durch diese Regeln technisch erzwungen.

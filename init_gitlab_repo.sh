#!/usr/bin/env bash
# Richtet das Repository ein und schiebt den ersten Commit in ein leeres
# GitLab-Projekt.
#
#   ./init_gitlab_repo.sh git@gitlab.example.de:bs/fundpunkte-tiere.git
#
# Das Skript macht nichts Unumkehrbares: Es bricht ab, wenn bereits ein
# .git-Verzeichnis existiert oder wenn das Zielprojekt nicht leer ist.
set -euo pipefail

REMOTE="${1:-}"
if [[ -z "$REMOTE" ]]; then
    echo "Aufruf: $0 <git-remote-url>" >&2
    exit 1
fi

cd "$(dirname "$0")"

# ── 1. Vorbedingungen ───────────────────────────────────────────────────────
if [[ -d .git ]]; then
    echo "FEHLER: Hier existiert bereits ein .git-Verzeichnis." >&2
    echo "Dieses Skript ist nur für die Ersteinrichtung gedacht." >&2
    exit 1
fi
command -v git >/dev/null || { echo "git nicht gefunden." >&2; exit 1; }

echo "── Zielprojekt prüfen ──"
if git ls-remote --heads "$REMOTE" 2>/dev/null | grep -q .; then
    echo "FEHLER: Das Remote enthält bereits Branches." >&2
    echo "Bitte ein leeres Projekt verwenden oder manuell zusammenführen." >&2
    exit 1
fi
echo "   leer – in Ordnung"

# ── 2. Lizenztext holen ─────────────────────────────────────────────────────
if [[ ! -s LICENSE ]]; then
    echo "── GPL-3.0-Lizenztext laden ──"
    if curl -fsSL https://www.gnu.org/licenses/gpl-3.0.txt -o LICENSE; then
        echo "   LICENSE geschrieben"
    else
        echo "   WARNUNG: Download fehlgeschlagen." >&2
        echo "   Bitte https://www.gnu.org/licenses/gpl-3.0.txt" >&2
        echo "   manuell als LICENSE ablegen – die Leistungsbeschreibung" >&2
        echo "   verlangt GPL-3.0 (§10)." >&2
    fi
fi

# ── 3. Textquellen aus den GeoPackages erzeugen ─────────────────────────────
echo "── Stile, DDL und Referenzlisten exportieren ──"
python3 tools/export_from_gpkg.py --plugin qgis_plugin --out .

# ── 4. Repository anlegen ───────────────────────────────────────────────────
echo "── Git-Repository anlegen ──"
git init -q -b main
git add -A

echo
echo "── Das wird committet (Übersicht) ──"
git status --short | head -40
DATEIEN=$(git diff --cached --name-only | wc -l)
GROESSE=$(git diff --cached --name-only | xargs -r du -ch 2>/dev/null | tail -1 | cut -f1)
echo "   ... insgesamt $DATEIEN Dateien, $GROESSE"

echo
echo "── Kontrolle: versehentlich große Dateien? ──"
git diff --cached --name-only | xargs -r ls -l 2>/dev/null \
    | awk '$5 > 5000000 {printf "   %10.1f MB  %s\n", $5/1048576, $9}' \
    || true
echo "   (nichts aufgeführt = in Ordnung)"

echo
read -r -p "Ersten Commit anlegen und pushen? [j/N] " ANTWORT
if [[ ! "$ANTWORT" =~ ^[jJyY]$ ]]; then
    echo "Abgebrochen. Das lokale Repository bleibt bestehen (noch kein Commit)."
    exit 0
fi

git commit -q -m "Erstimport: QGIS-/QField-Plugin Fundpunkte Tiere

Enthält den Plugin-Quellcode sowie Stile, Tabellenstrukturen und
Referenzlisten als versionierbare Textfassung. Große Fachdaten
(Nutzung.gpkg, Grenzen1.gpkg) sind ausgenommen und werden extern
bereitgestellt."

git remote add origin "$REMOTE"
git push -u origin main

echo
echo "Fertig. Nächste Schritte in GitLab:"
echo "  • Einstellungen → Repository → Geschützte Branches: main schützen"
echo "  • Einstellungen → CI/CD → Pipelines aktiviert lassen (.gitlab-ci.yml)"
echo "  • Tag v2.7.8 setzen, sobald der erste Stand abgenommen ist"

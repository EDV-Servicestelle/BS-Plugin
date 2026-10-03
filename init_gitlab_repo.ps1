# Richtet das Repository ein und schiebt den ersten Commit in ein leeres
# GitLab-Projekt. Windows-Variante.
#
#   .\init_gitlab_repo.ps1 -Remote git@gitlab.example.de:bs/fundpunkte-tiere.git
#
# Falls Windows die Ausfuehrung blockiert, einmalig fuer diese Sitzung:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# Das Skript macht nichts Unumkehrbares: Es bricht ab, wenn bereits ein
# .git-Verzeichnis existiert oder wenn das Zielprojekt nicht leer ist, und
# fragt vor dem Push nach.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Remote,

    # Python-Aufruf erzwingen, z. B. den von OSGeo4W/QGIS:
    #   -Python "C:\OSGeo4W\bin\python-qgis.bat"
    [string]$Python = ""
)

$ErrorActionPreference = 'Stop'

function Abbruch([string]$Text) {
    # Klare Meldung statt PowerShell-Ausnahme mit Quelltextauszug
    Write-Host ""
    Write-Host "FEHLER: $Text" -ForegroundColor Red
    exit 1
}

function Schreibe-Abschnitt([string]$Text) {
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Finde-Python {
    if ($Python) {
        if (Get-Command $Python -ErrorAction SilentlyContinue) { return $Python }
        if (Test-Path $Python) { return $Python }
        Abbruch "Angegebener Python-Pfad nicht gefunden: $Python"
    }
    # Reihenfolge: Launcher, dann uebliche Namen
    foreach ($kandidat in @('py', 'python', 'python3')) {
        $befehl = Get-Command $kandidat -ErrorAction SilentlyContinue
        if ($befehl) {
            # 'py' braucht -3, sonst kann Python 2 erwischt werden
            if ($kandidat -eq 'py') { return 'py -3' }
            return $kandidat
        }
    }
    Abbruch ("Python wurde nicht gefunden. Bitte Python installieren oder " +
             "mit -Python den Pfad angeben (z. B. den aus OSGeo4W/QGIS).")
}

function Starte-Python([string]$PythonBefehl, [string[]]$Argumente) {
    $teile = $PythonBefehl.Split(' ')
    $datei = $teile[0]
    $vorab = @()
    if ($teile.Count -gt 1) { $vorab = $teile[1..($teile.Count - 1)] }
    & $datei @vorab @Argumente
    if ($LASTEXITCODE -ne 0) {
        Abbruch "Python-Aufruf fehlgeschlagen (Rueckgabewert $LASTEXITCODE)."
    }
}

# Immer im Skriptverzeichnis arbeiten
Set-Location -Path $PSScriptRoot

# -- 1. Vorbedingungen -------------------------------------------------------
Schreibe-Abschnitt "Vorbedingungen pruefen"

if (Test-Path -Path '.git') {
    Abbruch ("Hier existiert bereits ein .git-Verzeichnis. Dieses Skript " +
             "ist nur fuer die Ersteinrichtung gedacht.")
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Abbruch "git wurde nicht gefunden. Bitte Git fuer Windows installieren."
}

$PythonBefehl = Finde-Python
Write-Host "   Python: $PythonBefehl"
Write-Host "   Git:    $((git --version) -join '')"

Write-Host "   Zielprojekt pruefen ..."
$zweige = git ls-remote --heads $Remote 2>$null
if ($LASTEXITCODE -ne 0) {
    Abbruch ("Das Remote ist nicht erreichbar: $Remote`n" +
             "Bitte Zugang (SSH-Schluessel bzw. Zugangsdaten) pruefen.")
}
if ($zweige) {
    Abbruch ("Das Remote enthaelt bereits Branches. Bitte ein leeres " +
             "Projekt verwenden oder manuell zusammenfuehren.")
}
Write-Host "   leer - in Ordnung" -ForegroundColor Green

# -- 2. Lizenztext holen -----------------------------------------------------
if (-not (Test-Path 'LICENSE') -or (Get-Item 'LICENSE' -Force).Length -eq 0) {
    Schreibe-Abschnitt "GPL-3.0-Lizenztext laden"
    try {
        # Windows PowerShell 5.1 verhandelt je nach Konfiguration noch TLS 1.0;
        # gnu.org verlangt mindestens TLS 1.2.
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor
            [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri 'https://www.gnu.org/licenses/gpl-3.0.txt' `
                          -OutFile 'LICENSE' -UseBasicParsing
        Write-Host "   LICENSE geschrieben" -ForegroundColor Green
    } catch {
        Write-Warning ("Download fehlgeschlagen. Bitte " +
            "https://www.gnu.org/licenses/gpl-3.0.txt manuell als LICENSE " +
            "ablegen - die Leistungsbeschreibung verlangt GPL-3.0 (Abschnitt 10).")
    }
}

# -- 3. Textquellen aus den GeoPackages erzeugen -----------------------------
Schreibe-Abschnitt "Stile, DDL und Referenzlisten exportieren"
Starte-Python $PythonBefehl @(
    'tools/export_from_gpkg.py', '--plugin', 'qgis_plugin', '--out', '.')

# -- 4. Repository anlegen ---------------------------------------------------
Schreibe-Abschnitt "Git-Repository anlegen"
git init -q -b main
git add -A
if ($LASTEXITCODE -ne 0) { Abbruch "git add fehlgeschlagen." }

$dateien = @(git diff --cached --name-only)
$gesamt = 0
$gross = @()
foreach ($d in $dateien) {
    if (Test-Path -LiteralPath $d) {
        # -Force noetig: Punktdateien (.gitattributes, .gitlab-ci.yml) gelten
        # je nach Dateisystem als versteckt und werden sonst nicht gefunden.
        $groesse = (Get-Item -LiteralPath $d -Force).Length
        $gesamt += $groesse
        if ($groesse -gt 5MB) {
            $gross += [PSCustomObject]@{ MB = [math]::Round($groesse / 1MB, 1); Datei = $d }
        }
    }
}

Schreibe-Abschnitt "Das wird committet"
git status --short | Select-Object -First 40
Write-Host ("   ... insgesamt {0} Dateien, {1:N1} MB" -f `
            $dateien.Count, ($gesamt / 1MB))

Schreibe-Abschnitt "Kontrolle: versehentlich grosse Dateien?"
if ($gross) {
    $gross | Sort-Object MB -Descending |
        ForEach-Object { Write-Host ("   {0,8:N1} MB  {1}" -f $_.MB, $_.Datei) `
                                    -ForegroundColor Yellow }
    Write-Host "   Pruefen, ob diese Dateien wirklich ins Repository gehoeren."
} else {
    Write-Host "   nichts ueber 5 MB - in Ordnung" -ForegroundColor Green
}

Write-Host ""
$antwort = Read-Host "Ersten Commit anlegen und pushen? [j/N]"
if ($antwort -notmatch '^[jJyY]$') {
    Write-Host "Abgebrochen. Das lokale Repository bleibt bestehen (noch kein Commit)."
    exit 0
}

$meldung = @"
Erstimport: QGIS-/QField-Plugin Fundpunkte Tiere

Enthaelt den Plugin-Quellcode sowie Stile, Tabellenstrukturen und
Referenzlisten als versionierbare Textfassung. Grosse Fachdaten
(Nutzung.gpkg, Grenzen1.gpkg) sind ausgenommen und werden extern
bereitgestellt.
"@

git commit -q -m $meldung
if ($LASTEXITCODE -ne 0) { Abbruch "git commit fehlgeschlagen." }

git remote add origin $Remote
git push -u origin main
if ($LASTEXITCODE -ne 0) { Abbruch "git push fehlgeschlagen." }

Write-Host ""
Write-Host "Fertig. Naechste Schritte in GitLab:" -ForegroundColor Green
Write-Host "  - Einstellungen > Repository > Geschuetzte Branches: main schuetzen"
Write-Host "  - Einstellungen > CI/CD > Pipelines aktiviert lassen (.gitlab-ci.yml)"
Write-Host "  - Tag v2.7.8 setzen, sobald der erste Stand abgenommen ist"

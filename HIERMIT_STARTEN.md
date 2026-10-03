# Einrichtung in drei Schritten

Dieses Archiv enthält das Repository-Gerüst **ohne** den Plugin-Quellcode.
Der kommt aus deiner vorhandenen Arbeitskopie.

## 1. Entpacken und Plugin einhängen

```bash
unzip repo-geruest.zip -d fundpunkte-tiere
cd fundpunkte-tiere

# vorhandenes Plugin als qgis_plugin/ einhängen
cp -r /pfad/zu/qgis_new_project_plugin_v277 qgis_plugin
```

Der Ordner heißt im Repository bewusst `qgis_plugin` statt
`qgis_new_project_plugin_v277` — ein Versionskürzel im Ordnernamen müsste
sonst bei jeder Version geändert werden. Das Paketskript baut das ZIP
weiterhin mit passendem Namen, die Version kommt dann aus dem Git-Tag.

## 2. Vor dem ersten Push aufräumen

Zwei Dinge aus der Prüfung (Details im Abschnitt unten):

```bash
# a) Altlast entfernen – laut euren Konventionen ohnehin ausgemustert
rm qgis_plugin/data/Nutzung.gpkg          # 103 MB

# b) Testfundpunkte prüfen und ersetzen
#    qgis_plugin/data/fundpunkte_tiere/Fundpunkte.gpkg enthält 10 Datensätze
```

## 3. Einrichten und pushen

### Windows (PowerShell)

```powershell
# einmalig für diese Sitzung, falls Windows die Ausführung blockiert
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\init_gitlab_repo.ps1 -Remote git@euer-gitlab:bs/fundpunkte-tiere.git
```

Python wird automatisch gesucht (`py -3`, `python`, `python3`). Wenn auf dem
Rechner nur das Python aus QGIS liegt, lässt es sich angeben:

```powershell
.\init_gitlab_repo.ps1 -Remote git@euer-gitlab:bs/... `
                       -Python "C:\OSGeo4W\bin\python-qgis.bat"
```

Voraussetzung ist Git für Windows. Die mitgelieferte `.gitattributes` setzt
`eol=lf`, damit unter Windows keine CRLF-Zeilenenden ins Repository geraten.

### Linux / macOS

```bash
chmod +x init_gitlab_repo.sh
./init_gitlab_repo.sh git@euer-gitlab:bs/fundpunkte-tiere.git
```

Das Skript prüft zuerst, ob das Zielprojekt wirklich leer ist, lädt den
GPL-3.0-Lizenztext, erzeugt die Textfassungen aus den GeoPackages, zeigt dir
den geplanten Commit-Umfang samt großer Dateien — und **fragt dann nach**,
bevor etwas gepusht wird.

---

# Was vor dem ersten Push zu klären ist

## Testfundpunkte mit echten Koordinaten

`Fundpunkte.gpkg` enthält 10 Datensätze vom 22.01.2026 mit UTM-Koordinaten im
Kreis Wesel, teilweise mit deinem Namen im Feld `Kartierer`. Darunter:

| Art | Status |
| --- | --- |
| *Bufo viridis* (Wechselkröte) | FFH-Anhang IV, streng geschützt |
| *Bufo calamita* (Kreuzkröte) | FFH-Anhang IV, streng geschützt |
| *Lycaena hippothoe* (Lilagold-Feuerfalter) | Rote Liste NRW |

Falls das geklickte Testpunkte sind, ist es unkritisch — dann sollte es aber im
Repository dokumentiert sein. Falls es echte Beobachtungen sind, gehören sie
nicht in ein künftig öffentliches Repository: Einmal gepusht, bleiben sie über
die Git-Historie abrufbar, auch nach späterer Löschung, und Forks lassen sich
nicht zurückholen.

Empfehlung: Testdaten mit zufälligen Koordinaten innerhalb eines
Untersuchungsgebiets neu erzeugen und das Feld `Kartierer` leeren.

## Nutzung.gpkg (103 MB)

Liegt noch im Datenordner, obwohl es laut euren Arbeitskonventionen entfernt
wurde. Es enthält eine einzelne Tabelle mit Nutzungsflächen des Kreises Wesel —
vermutlich Fremddaten, deren Weitergabelizenz zu prüfen wäre. Es ist in
`.gitignore` ausgeschlossen; ich würde es aus der Arbeitskopie löschen.

## Zugangsdaten

Im Quellcode habe ich keine gefunden — Verbindungsparameter und
QFieldCloud-Logins liegen in der UI bzw. in QSettings. Gefährlich sind die
Nebenwege: Testkonfigurationen, Entwicklerskripte, Logdateien. Dagegen laufen
der `gitleaks`-Hook (lokal) und der CI-Job `geheimnisse`.

---

# Inhalt des Gerüsts

| Datei | Zweck |
| --- | --- |
| `init_gitlab_repo.ps1` | Ersteinrichtung unter **Windows** (PowerShell) |
| `init_gitlab_repo.sh` | Ersteinrichtung unter Linux/macOS |
| `.gitignore` | schließt große Fachdaten, Zugangsdaten, Build-Ergebnisse aus |
| `.gitattributes` | Zeilenenden, Text/Binär-Einstufung |
| `.gitlab-ci.yml` | Secret-Scan, PEP 8, Quellen-Abgleich, Paketbau |
| `.pre-commit-config.yaml` | dieselben Prüfungen lokal vor dem Commit |
| `README.md` | Projektbeschreibung, Arbeitsabläufe |
| `tools/export_from_gpkg.py` | Stile, DDL und Referenzlisten als Text herausziehen |
| `tools/build_plugin_zip.py` | Plugin-ZIP bauen, Version aus Git-Tag |
| `tools/build_reflisten_from_ods.py` | LANUK-Arbeitsmappe → Referenzlisten |

Alle Skripte sind hier gegen deine echten GeoPackages gelaufen; die
PowerShell-Fassung zusätzlich vollständig gegen ein lokales Testremote,
einschließlich der Abbruchfälle.

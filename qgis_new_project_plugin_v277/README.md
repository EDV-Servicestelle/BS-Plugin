# NRW Naturschutz-Toolbox – QGIS-Plugin (v1.87)

**Biologische Station Kreis Wesel e.V.** · [blinn@bskw.de](mailto:blinn@bskw.de)

Modulares QGIS-Plugin für den Naturschutz-Datentransfer in NRW. Acht integrierte Werkzeuge für Artdaten-Import, LiDAR-Analyse, Luftbild, Hydroanalyse, Schutzgebiete und QField-Felderfassung.

## Changelog

### v1.87 (Mai 2026)
- **PostGIS-Setup-Dialog**: Automatischer DB-Aufbau aus lokalen GPKGs inkl. Schemas, Styles und `public.fachschalen_config`; `_rename_cols_to_original` für CamelCase-Spaltennamen; QML-Feldnamen-Normalisierung mit Aliassen
- **Fachschalen-Wizard PostGIS**: Institution/Karterer aus `gemeinsam.*`; case-insensitiver `ref_layer_map`-Lookup; Style-Loading aus `public.layer_styles`
- **Ornitho.de Import**: Neuer Dialog für Basic+-JSON-Format (Beobachter, Atlas-Code, GPS-Filter, direkte URL)
- **LOD-2 Gebäudemodell**: Direktdownload CityGML-Kacheln statt OGC-API; `BuildingPart`-Support; Gebäudefunktions-Tabelle vollständig (4+5-stellige ALKIS-Codes)
- **ATKIS Gewässer**: `AX_Kanal` + `AX_Hafenbecken` als Breaklines; vollständige Felder laut Objektartenkatalog; `ax_gewaesserachse` (nicht `ax_gewaessermittelachse`)
- **ATKIS Landnutzung**: 13 neue Objektarten (Wohnbau, Industrie, Gemischt, Sport/Freizeit, Friedhof, Flugverkehr, Gartenland, Tagebau, Halde, Sumpf, Unland)
- **Grundlagenabruf Wizard**: Automatischer NSG/LSG/FFH-Abruf nach Wizard-Abschluss über `_GrundlagenWorker` (asynchron)
- **Gemeinsam-Schema**: `gemeinsam.institution`, `gemeinsam.karterer`, `gemeinsam.untersuchungsgebiet` für alle Fachschalen


---

## Menü: NRW Naturschutz-Toolbox

```
NRW Naturschutz-Toolbox
  Fachschalen-Wizard …
  QField-Export …
  ─────────────────────────────────────
  GBIF Artvorkommen …
  Ornitho.de Import …
  ─────────────────────────────────────
  NRW Luftbild → COG …
  NRW LiDAR-Analyse …
  Hydrologische Analyse …
  NRW Grundlagendaten abrufen …
  ─────────────────────────────────────
  PostGIS-Datenbank einrichten …
```

---

## Module

### 1 · Fachschalen-Wizard
Erstellt vollständige QGIS-Projekte aus mitgelieferten GeoPackages (Offline-Modus) oder aus PostGIS.

| Fachschale | Layer | Besonderheiten |
|---|---|---|
| Fundpunkte Tiere | Fund, Referenzlisten | ValueRelation, Artname-Lookup |
| Brutvogel | Beobachtungen, Ortsbewegungen, Simultanmarker | RelationEditor (Composition) |
| Biotopbaum | Bäume, Höhlen, Referenzlisten | ValueRelation |

---

### 2 · QField-Export
GPKG-Export + QFieldCloud-Upload für Felderfassung. Umpfadung der ValueRelation-Widget-Referenzen auf neue GPKG-Layer-IDs.

---

### 3 · Fundpunkte – Altdaten importieren
Importiert heterogene Altdaten (SHP, GPKG, CSV, XLS) in den NRW-Fundpunkte-Standard via 5-Tab-Dialog.

**Artname-Auflösung (3-stufig):**
1. Direktlookup + Synonymtabelle (`data/synonyme.json`)
2. TF-IDF + Levenshtein-Ensemble (sklearn, Bi-/Trigramme)
3. k-NN Spatial Index (BallTree, bis 50 km Radius, UTM32)

**Unterstützte Quell-CRS:** GK Streifen 2/3 (EPSG:31466/31467), UTM32 (25832/32632), WGS84 (4326), WebMercator (3857) – mit Auto-Detect bei fehlendem CRS.

**Ausgabe-Tabellen im GPKG:**
- `Fund` – importierte Features
- `Fund_Fehlend` – nicht aufgelöste Artnamen
- `Fund_Quellfelder` – nicht gemappte Quellfelder

---

### 4 · Fundpunkte – Zeitreihen-Diagramm
Fundhäufigkeit über die Zeit – Gruppierung nach Jahr/Monat/Jahrzehnt, Top-12-Automatik, öffnet im Browser.

---

### 5 · NRW Luftbild → COG
DOP (Digitale Orthophotos) vom NRW-WCS als COG GeoTIFF (EPSG:25832).

**Workflow:** GetCapabilities → Coverage-Autodiscovery → paralleler Download (1×1 km Blöcke) → GDAL Warp → COG

---

### 6 · NRW LiDAR-Analyse
Lädt NRW LiDAR-Kacheln (LAZ, 1×1 km) und erzeugt:

| Produkt | Format | Beschreibung |
|---|---|---|
| Höhenraster | GPKG (Polygon) | Statistik je Zelle (avg/min/max/range/n) |
| DTM | COG GeoTIFF | Digitales Geländemodell |
| Schummerung | COG GeoTIFF | Hillshade 315°/45° |
| Neigung | COG GeoTIFF | Hangneigung in Grad |
| Höhenlinien | GPKG (Linie) | variable Äquidistanz |

**LAZ-Lesen:** laspy (empfohlen) → PDAL-Python-Bindings → PDAL-CLI → Fehlermeldung mit Installationshinweis.

**Installation LAZ-Backend:**
```
pip install laspy[lazrs]
# Fallback:
pip install laspy laszip
```

**Aggregation:** 1 m Grid optional auf 2–10 m aggregierbar (mean/min/max/median/std/count).

---

### 7 · Hydrologische Analyse
D8-Fließrichtung, Akkumulation, Strahler-Ordnung, Abflusssenken aus DTM.

---

### 8 · NRW Grundlagendaten abrufen
Schutzgebiete (NSG, LSG, FFH, VSG, NTP …), FFH-Lebensraumtypen und Flurstücke via OGC-API / WFS NRW → GPKG.

---

## Installation

Plugin-Ordner in das QGIS-Plugin-Verzeichnis kopieren:

```
Windows:  %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
Linux:    ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
macOS:    ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/
```

Plugin aus **OSGeo4W-Kontext** starten (GDAL, PDAL, numpy verfügbar).

---

## Abhängigkeiten

| Bibliothek | Quelle | Pflicht |
|---|---|---|
| numpy | OSGeo4W | Ja |
| GDAL (osgeo) | OSGeo4W | Ja |
| requests | pip | Ja |
| scikit-learn | OSGeo4W-Setup | Empfohlen (TF-IDF/k-NN) |
| laspy[lazrs] | pip | Empfohlen (LAZ-Lesen) |
| PDAL | OSGeo4W | Fallback für LAZ |
| scipy | OSGeo4W / pip | Hydroanalyse |

---

## Dateistruktur

```
qgis_new_project_plugin_v152/
├── metadata.txt
├── README.md
├── ENTWICKLUNG.md
├── new_project_plugin.py          Menü, Lebenszyklus
├── new_project_wizard.py          Fachschalen-Wizard
├── wizard_pages.py                Wizard-Seiten
├── fachschalen_config.py          Konfiguration (3 Fachschalen)
├── fachschale_loader.py           DB-Loader
├── project_finalizer.py           GPKG-Export + Umpfadung
├── qfield_project_dialog.py       QFieldCloud-Export
├── fundpunkte_import_dialog.py    Altdaten-Importer (5 Tabs)
├── fundpunkte_trend_dialog.py     Zeitreihen-Diagramm
├── lidar_dialog.py                LiDAR-Dialog (UI)
├── luftbild_dialog.py             Luftbild-Dialog (UI)
├── hydro_dialog.py                Hydro-Dialog (UI)
├── grundlagen_dialog.py           Grundlagen-Dialog (UI)
├── core/                          Algorithmen (kein Qt)
│   ├── lidar.py
│   ├── luftbild.py
│   ├── hydro.py
│   ├── grundlagen.py
│   └── import_core.py
├── workers/                       QThread-Schicht
│   ├── lidar_worker.py
│   ├── luftbild_worker.py
│   ├── hydro_worker.py
│   ├── grundlagen_worker.py
│   └── import_worker.py
└── data/
    ├── synonyme.json
    ├── untersuchungsgebiet.gpkg
    ├── Nutzung.gpkg
    ├── fundpunkte_tiere/
    ├── biotopbaum/
    └── brutvogel/
```

---

## Versionsgeschichte

| Version | Datum | Änderungen |
|---|---|---|
| v1.87 | 04/2026 | LiDAR-Aggregation eingebaut, laspy Context-Manager Fix, PDAL writers.las |
| v1.80 | 04/2026 | Vollständiger Import-Audit, _PLUGIN_DIR Fix, WGS84/UTM32 in allen Core-Modulen |
| v1.74 | 04/2026 | k-NN in-place Mutation Fix (Dialog sieht Worker-Index) |
| v1.69 | 04/2026 | _PLUGIN_DIR in core/ auf Plugin-Root korrigiert (Referenz-DB gefunden) |
| v1.64 | 04/2026 | GPKG-Daten im FULL-ZIP, laspy Auto-Detect |
| v1.57 | 04/2026 | Canvas-Sync (extentsChanged), WGS84 Dialog-Fix |
| v1.55 | 04/2026 | Refactoring: FT-Präfix entfernt, 3-Schichten-Architektur |

---

*Biologische Station Kreis Wesel e.V. · blinn@bskw.de*


## PyCharm-Einrichtung

### Interpreter
1. `Settings → Project → Python Interpreter → Show All → ＋`
2. **Existing environment** → `C:/OSGeo4W/apps/Python312/python.exe`

### Pfade hinzufügen (damit QGIS-Importe erkannt werden)
Im Interpreter-Dialog das Dateisystem-Icon → Pfade hinzufügen:
```
C:/OSGeo4W/apps/qgis-ltr/python
C:/OSGeo4W/apps/qgis-ltr/python/plugins
C:/OSGeo4W/apps/Python312/Lib/site-packages
```

### Stubs
Das `stubs/`-Verzeichnis enthält minimale Typ-Definitionen für QGIS.
PyCharm erkennt diese automatisch als Teil des Projekts.

### Debug-Log
Jeder Plugin-Start schreibt nach:
```
C:/Users/<Name>/naturschutz_debug.log
```
Rotation bei 500 KB → naturschutz_debug.log.bak

### Meldungsprotokoll in QGIS
```
Ansicht → Meldungsprotokoll → NRW Naturschutz
```

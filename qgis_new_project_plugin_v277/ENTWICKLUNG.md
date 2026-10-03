# NRW Naturschutz-Toolbox – Entwicklerhandbuch (v1.83)

**Biologische Station Kreis Wesel e.V.** · blinn@bskw.de

---

## Architektur: 3-Schichten-Modell

```
Dialog (*_dialog.py)
  │  Nur Qt-Widgets, keine Algorithmen
  │  Liest Konfiguration → startet Worker
  │  Layer-Laden NUR im Hauptthread (_on_finished)
  ▼
Worker (workers/*_worker.py)
  │  QThread, sendet progress/finished Signale
  │  Importiert direkt aus qgis.core (kein try/except nötig)
  │  Globale Objekte IN-PLACE mutieren (nicht neu zuweisen!)
  ▼
Core (core/*.py)
  │  Reine Algorithmen, KEIN Qt
  │  try/except für alle optionalen Imports
  │  _PLUGIN_DIR = os.path.dirname(os.path.dirname(__file__))
  ▼
Externe Dienste / GDAL / numpy
```

---

## Kritische Regeln

### 1. _PLUGIN_DIR in core/
```python
# RICHTIG – core/ liegt eine Ebene unterhalb des Plugin-Roots:
_PLUGIN_DIR = os.path.dirname(os.path.dirname(__file__))

# FALSCH:
_PLUGIN_DIR = os.path.dirname(__file__)  # zeigt auf core/, nicht Plugin-Root
```

### 2. Globale Objekte in-place mutieren
```python
# FALSCH – Dialog sieht neue Instanz nicht:
global _KNN_INDEX
_KNN_INDEX = _KNNSpatialIndex()

# RICHTIG – gleiche Instanz, Dialog + Worker teilen sie:
_KNN_INDEX._tree    = None
_KNN_INDEX._entries = []
_KNN_INDEX.built    = False
_KNN_INDEX.build(records)
```

### 3. Layer NUR im Hauptthread laden
```python
# FALSCH (im Worker-Thread):
QgsProject.instance().addMapLayer(lyr)

# RICHTIG (in _on_finished im Dialog):
def _on_finished(self, ok, msg):
    if ok:
        lyr = QgsVectorLayer(...)
        QgsProject.instance().addMapLayer(lyr)
```

### 4. CRS-Konstanten in jedem Core-Modul
```python
try:
    from qgis.core import QgsCoordinateReferenceSystem as _CRS
    WGS84 = _CRS("EPSG:4326")
    UTM32 = _CRS("EPSG:25832")
except Exception:
    WGS84 = None
    UTM32 = None
```

### 5. Import-Vollständigkeit prüfen
Vor jedem Release: alle Symbole die ein Dialog/Worker aus Core nutzt müssen explizit importiert sein. Import-Audit-Skript:

```python
import re, os
dst = '/pfad/zum/plugin'

def audit(dialog_f, core_f):
    dc = open(f'{dst}/{dialog_f}').read()
    cc = open(f'{dst}/{core_f}').read()
    core_names = set(re.findall(r'^(?:def |class |)([A-Z_][A-Z_0-9]*|_[a-z]\w*)\s*[=(]', cc, re.MULTILINE))
    imported   = set(re.findall(r'[a-zA-Z_]\w*', re.search(r'from [\.\w]+import_core import \(([^)]+)\)', dc, re.DOTALL).group(1) if 'import_core' in dc else ''))
    body_used  = set(re.findall(r'\b([a-zA-Z_]\w*)\b', dc[dc.find('class '):]))
    missing    = (core_names & body_used) - imported
    if missing:
        print(f'{dialog_f}: FEHLT {sorted(missing)}')

audit('fundpunkte_import_dialog.py', 'core/import_core.py')
```

---

## Dateiübersicht

```
qgis_new_project_plugin_v152/
├── new_project_plugin.py          87 Z   Menü (lazy imports, Trenner)
├── new_project_wizard.py         552 Z   Fachschalen-Wizard (GPKG-Modus)
├── wizard_pages.py               706 Z
├── fachschalen_config.py         583 Z
├── fachschale_loader.py          184 Z
├── project_finalizer.py          340 Z
├── qfield_project_dialog.py      525 Z
├── fundpunkte_import_dialog.py  ~1100 Z  5-Tab-Dialog
├── fundpunkte_trend_dialog.py    293 Z
├── lidar_dialog.py               317 Z
├── luftbild_dialog.py            266 Z
├── hydro_dialog.py               246 Z
├── grundlagen_dialog.py          225 Z
│
├── core/
│   ├── import_core.py           1200 Z  TF-IDF, k-NN, Levenshtein, Import
│   ├── lidar.py                  620 Z  LAS/LAZ, Grid, IDW, COG
│   ├── luftbild.py               241 Z  WCS, Georef, COG
│   ├── hydro.py                  528 Z  D8, fill_sinks, Strahler
│   └── grundlagen.py             420 Z  OGC-API/WFS, GPKG-Writer
│
├── workers/
│   ├── import_worker.py          550 Z  _ScanWorker
│   ├── lidar_worker.py           249 Z  _LidarWorker
│   ├── luftbild_worker.py        177 Z  _WcsWorker
│   ├── hydro_worker.py           165 Z  _HydroWorker
│   └── grundlagen_worker.py       92 Z  _GrundlagenWorker
│
└── data/
    ├── synonyme.json
    ├── untersuchungsgebiet.gpkg
    ├── Nutzung.gpkg               ATKIS-Landnutzung Kreis Wesel
    ├── fundpunkte_tiere/
    │   ├── Fundpunkte.gpkg
    │   └── Referenzen.gpkg        13.291 Arten, Status, Geschlecht, Institution
    ├── biotopbaum/
    │   ├── Erfassung.gpkg
    │   ├── Referenzlisten.gpkg
    │   └── Grenzen1.gpkg
    └── brutvogel/
        ├── QFS_bv.gpkg
        └── Untersuchungsgebiet.gpkg
```

---

## LiDAR-Pipeline

```
AOI (WGS84) → _wgs84_to_utm32 → _las_tiles (1×1 km)
  ↓ Download (ThreadPoolExecutor)
LAZ-Dateien
  ↓ _read_las_points
    laspy.read() → Exception("LazBackend") → _read_pdal (PDAL-CLI)
  ↓ _points_to_grid (cell_m = 1.0 m default)
  ↓ _fill_gaps (IDW, Radius 5 m)
  ↓ _aggregate_grid (optional, 2–10 m, mean/min/max/median/std)
  ↓ _grid_to_features_numpy
  ↓ QgsVectorFileWriter → GPKG
  ↓ _derive_products → DTM.tif, Schummerung.tif, Neigung.tif, Höhenlinien.gpkg
```

**PDAL Writers:** `writers.numpy` fehlt in OSGeo4W → `writers.las` + `_read_las_raw` nutzen.

---

## k-NN Artname-Matching

```
Quelllayer (beliebiges CRS)
  ↓ Auto-CRS-Detect (Koordinatenbereiche) oder QGIS-CRS
  ↓ QgsCoordinateTransform → UTM32 (EPSG:25832)
  ↓ pos_cache {artname: [(x_utm, y_utm), ...]}
  ↓ _KNN_INDEX.build(records)   ← IN-PLACE (nicht neu zuweisen!)
    BallTree (euclidean, max_radius=50.000 m)
  ↓ _get_knn_vote_for(raw_name) im Dialog
    self._pos_cache.get(raw_name) → vote() → Prozentsatz
```

**Unterstützte CRS für Auto-Detect:**
- GK Str. 2 (EPSG:31466): E 2,4–2,8M
- GK Str. 3 (EPSG:31467): E 3,3–3,7M
- UTM32 WGS84 (EPSG:32632): E 200k–700k
- WGS84 (EPSG:4326): E 5,5–10°
- WebMercator (EPSG:3857): E 600k–1,1M

---

## Neue Funktion hinzufügen

### Einfach (kein Hintergrundthread)
1. Algorithmus → `core/mein_modul.py`
2. Dialog → `mein_dialog.py`
3. Slot in `new_project_plugin.py`: `def _mein(self): from .mein_dialog import MeinDialog; MeinDialog(...).exec()`
4. Menüeintrag in `initGui()`

### Mit Hintergrundthread
1. `core/mein_modul.py` – Algorithmen
2. `workers/mein_worker.py` – QThread, sendet `progress(int, str)` + `finished(bool, str)`
3. `mein_dialog.py` – startet Worker, empfängt Signale, lädt Layer in `_on_finished`
4. Menüeintrag registrieren

---

## Bekannte Einschränkungen

- Hydroanalyse: Strahler-Ordnung bei >500 km² langsam → richdem/pysheds installieren
- LiDAR: LAZ nur mit laspy[lazrs] oder PDAL (OSGeo4W-Shell starten für PDAL im PATH)
- WCS NRW: Coverage-Name kann sich ändern → „Coverages prüfen"-Button nutzen
- Brutvogel-Fachschale: noch ohne Testdaten im Plugin

---

*Biologische Station Kreis Wesel e.V. · blinn@bskw.de*

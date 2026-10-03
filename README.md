# Fundpunkte Tiere — QGIS- und QField-Plugin

Werkzeuge der EDV-Servicestelle der Biologischen Stationen in NRW für die
standardisierte Erfassung georeferenzierter Tierfundpunkte nach dem
LANUK-Datenmodell „Fundpunkte Tiere“.

Das Paket umfasst das QGIS-Plugin zur Projektanlage und -pflege
(Fachschalen-Wizard, Altdaten-Import, QFieldCloud-Export) sowie die
QField-Projekt-Plugins für die mobile Erfassung.

- **Lizenz:** GNU General Public License v3.0 (siehe `LICENSE`)
- **Zielplattform:** QGIS 4.2 LTR (Qt6), QField 4.x, GeoPackage, EPSG:25832

## Aufbau des Repositorys

| Pfad | Inhalt |
| --- | --- |
| `qgis_plugin/` | Quellcode des QGIS-Plugins samt QField-Projekt-Plugins |
| `styles/` | Layerstile als QML-Textdateien, aus `layer_styles` exportiert |
| `datamodel/` | Tabellenstrukturen als SQL-DDL |
| `reflists/` | Referenzlisten als CSV |
| `docs/` | Datenmodell (Anlage A), Leistungsbeschreibung, Änderungsprotokolle |
| `tools/` | Hilfsskripte für Export, Paketbau und Referenzlisten |

### Warum Stile und Referenzlisten doppelt vorliegen

Produktiv liegen die Layerstile in der Tabelle `layer_styles` **innerhalb** des
GeoPackages — dort sind sie weder lesbar noch vergleichbar. Genau daraus sind
wiederholt Abweichungen entstanden: ein Stil im GeoPackage geändert, die freie
QML-Datei nicht nachgezogen, und das Formular verhielt sich in QGIS anders als
in QField.

Deshalb werden Stile, Tabellenstrukturen und Referenzlisten zusätzlich als
Textdateien geführt. Sie sind die lesbare Fassung; Abweichungen werden zu
sichtbaren Diffs und von der CI geprüft.

Nach jeder Änderung an einem GeoPackage:

```bash
python3 tools/export_from_gpkg.py --plugin qgis_plugin --out .
```

Prüfen, ohne zu schreiben (wie in der CI):

```bash
python3 tools/export_from_gpkg.py --plugin qgis_plugin --out . --pruefen
```

### Große Fachdaten

`Nutzung.gpkg` (103 MB) und `Grenzen1.gpkg` (11 MB) sind von der
Versionsverwaltung ausgenommen und werden extern bereitgestellt. Git würde bei
jeder Änderung eine vollständige neue Kopie speichern.

## Paket bauen

```bash
python3 tools/build_plugin_zip.py --plugin qgis_plugin --out dist
```

Die Version kommt aus dem Git-Tag (z. B. `v2.7.8`) und wird in die
`metadata.txt` des Pakets geschrieben, damit Dateiname und Plugin-Metadaten
nicht auseinanderlaufen.

## Referenzlisten aus den LANUK-Vorgaben erzeugen

```bash
pip install odfpy
python3 tools/build_reflisten_from_ods.py \
    --ods     reflists/quellen/Refliste_FT_Entwicklung_2027.ods \
    --vorlage qgis_plugin/data/fundpunkte_tiere/Referenzen.gpkg \
    --out     Referenzen_neu.gpkg \
    --bericht migration_bericht.csv
```

## Mitarbeit

Vor dem ersten Commit einmalig einrichten:

```bash
pip install pre-commit
pre-commit install
```

Damit laufen Zugangsdaten-Prüfung und Formatkontrollen schon lokal, nicht erst
in der CI.

## Hinweis zu schützenswerten Inhalten

Dieses Repository ist für eine spätere öffentliche Bereitstellung vorgesehen.
Zwei Dinge dürfen deshalb nicht hineingeraten:

1. **Zugangsdaten** — Verbindungsparameter der Grundlagen-Datenbank,
   QFieldCloud-Logins, interne Hostnamen. Sie gehören in die lokale
   QGIS-Konfiguration, nicht in den Quellcode.
2. **Artenschutzrechtlich sensible Funddaten** — Testprojekte dürfen keine
   echten Fundorte streng geschützter Arten enthalten. Einmal gepusht, bleiben
   sie über die Git-Historie abrufbar, auch nach einer späteren Löschung.

# Grundlagendaten im Cloud-Paket & Öffnen des Cloud-Projekts

## 1. Prüfung: Werden geladene Grundlagen in die Cloud übernommen?

**Ergebnis: teilweise — und bisher mit einem Fehler.**

Der Sammler `collect_and_copy_geopackages()` berücksichtigt ausschließlich
**Vektorlayer, deren Quelle ein GeoPackage ist** (Erkennung über
`|layername=` in `layer.source()`). Daraus folgt:

| Grundlagen-Quelle | bisher im Cloud-Paket |
| --- | --- |
| Grundlagen-DB (PostGIS) → in GPKG geschrieben | ja, aber aus geteiltem Temp-Pfad (fehlerhaft) |
| Live-WFS → `Grundlagen.gpkg` im Projektordner | ja |
| WMS/WMTS-Hintergrundkarten (Raster) | **nein** — bleiben Online-Quellen |
| direkt eingebundene PostGIS-Layer | **nein** — fehlen auf dem Gerät |

### Gefundener Fehler: geteilte Temp-Datei
Die aus der Grundlagen-DB geladenen Dienste wurden nach
`<TEMP>/grundlagen_tmp.gpkg` geschrieben. `_write_to_gpkg()` hängt an bereits
vorhandene Layer **an** (`AppendToLayerNoNewFields`). Damit summierten sich die
Grundlagen aufeinanderfolgender Projektläufe in derselben Datei auf — das
Cloud-Paket eines Projekts konnte Schutzgebiete und ATKIS-Flächen **eines
anderen Projekts** enthalten. Zusätzlich ist die Datei flüchtig: räumt das
Betriebssystem das Temp-Verzeichnis auf, fehlen die Grundlagen ganz.

**Behoben:** Neuer Helfer `_grundlagen_gpkg_pfad()` schreibt nach
`<Projektordner>/Grundlagen.gpkg`. Die Datei wird einmal je Projektlauf
zurückgesetzt (Merker `_grundlagenGpkgFrisch`), sodass DB- und WFS-Zweig in
dieselbe Datei schreiben, ohne sich gegenseitig zu überschreiben.

**Folgefehler mitbehoben:** Liegt die Quelle bereits im Zielordner, kopierte
`collect_and_copy_geopackages()` die Datei auf sich selbst
(`shutil.SameFileError`). Der Fall wird jetzt abgefangen.

### Neue Rückmeldung vor dem Upload
`_pruefe_nicht_paketierbare_layer()` listet vor dem Upload alle Layer auf, die
nicht als Datei mitgehen können:
- WMS/WMTS/XYZ/WFS → bleiben Online-Quellen, im Gelände ohne Internet leer
- PostGIS → werden nicht paketiert und fehlen auf dem Gerät

Liegt alles als GeoPackage vor, wird das ausdrücklich bestätigt
(„Alle Layer liegen als GeoPackage vor (offline-fähig)“).

## 2. Projekt nach Abschluss in QField öffnen (synchronisierte Fassung)

Bisher wurde nach dem Upload lediglich eine Meldung mit der Cloud-URL in der
QGIS-Message-Bar angezeigt.

**Neu:** Gruppe „Nach Abschluss“ auf der Export-Seite mit der Option
„Projekt nach Abschluss in QField öffnen (bei Cloud-Projekt die
synchronisierte Fassung)“ (standardmäßig aktiv) und einem Pfadfeld für die
QField-Anwendung.

### Wichtig: es wird die synchronisierte Cloud-Kopie geöffnet
Bei einem Cloud-Projekt wird **nicht** der lokale Projektordner geöffnet,
sondern die von QField unter `cloud_projects/` abgelegte Fassung. Nur diese
Kopie wird von QField wieder mit QFieldCloud abgeglichen — ein direkt
geöffneter Projektordner wäre eine Sackgasse, deren Änderungen nie in der
Cloud ankämen.

Gesucht wird unter `<QField-App-Verzeichnis>/cloud_projects/<Konto>/<Projekt-ID>/`.
Die Projekt-ID wird aus der Upload-URL
(`https://app.qfield.cloud/projects/<id>`) abgeleitet; der Kontoname ist nicht
vorhersagbar und wird per Mustersuche übersprungen.

App-Verzeichnisse laut QField-Dokumentation:

| System | Pfad |
| --- | --- |
| Windows | `%APPDATA%\ch.opengis.qfield\QField` |
| macOS | `~/Library/Application Support/QField/QField` |
| Linux | `~/.local/share/OPENGIS.ch/QField` |

**Fallunterscheidung:**
- Projekt bereits synchronisiert → QField öffnet direkt die Cloud-Fassung.
- Noch nie synchronisiert (QField lädt Cloud-Projekte selbst herunter, das
  kann der Wizard nicht vorwegnehmen) → QField wird ohne Projektargument
  gestartet, mit Hinweis im Log, das Projekt unter „QFieldCloud projects“
  auszuwählen; die Projekt-ID wird mit ausgegeben.
- Kein Cloud-Upload gewählt → der lokale Projektordner wird geöffnet.

### QField-Pfad
- Wird beim Öffnen des Wizards automatisch gesucht: Windows
  (`%LOCALAPPDATA%\Programs\QField\qfield.exe`, Programme), macOS
  (`/Applications/QField.app/...`), Linux (`/usr/bin/qfield`,
  `/usr/local/bin/qfield`, AppImage im Home, `qfield` im PATH, sonst Flatpak
  `org.qfield.QField`).
- Über „…“ manuell wählbar, gemerkt in den QGIS-Einstellungen
  (`naturschutz/qfield_pfad`).
- Start über `QProcess.startDetached()`; für Flatpak wird
  `flatpak run org.qfield.QField <projekt>` zusammengesetzt.
- Wird QField nicht gefunden oder startet nicht, erscheint ein Hinweis im Log;
  der Lauf gilt weiterhin als erfolgreich.

Die Cloud-URL der vorherigen Ausführung wird zu Beginn jedes Laufs verworfen,
damit nie ein altes Projekt geöffnet wird.

## Offener Punkt
Für echten Offline-Betrieb der Hintergrundkarten wäre ein Rasterexport
(WMS → lokales GeoPackage/MBTiles für das Untersuchungsgebiet) nötig. Das ist
bewusst nicht umgesetzt, da es Datenmenge und Lizenzfragen berührt —
QFieldSync bietet hierfür einen eigenen Weg an.

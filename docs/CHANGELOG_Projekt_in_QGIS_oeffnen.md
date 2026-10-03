# Cloud-Projekt nach dem Erstellen in QGIS öffnen

## Befund
Der Wizard baut das Projekt in `QgsProject.instance()` auf, hängt die
Layerquellen aber erst beim Speichern auf die kopierten GeoPackages und auf
relative Pfade um (`relink_project_to_local_geopackages()` → `project.write()`).

Nach dem Lauf arbeitete QGIS damit weiter auf dem **Zwischenstand im
Arbeitsspeicher**, nicht auf der gespeicherten Fassung. Sichtbar wird der
Unterschied bei den Pfaden: Die hochgeladene Fassung referenziert
`./Fundpunkte.gpkg`, der Speicherstand im RAM dagegen noch die absoluten
Quellpfade. Ein Test im Gelände-Zustand war so nur eingeschränkt möglich.

## Änderung
Neue Option **„Projekt in QGIS öffnen (gespeicherte Fassung neu laden)“** in
der Gruppe „Nach Abschluss“ der Export-Seite — standardmäßig **aktiv**.

- Nach erfolgreichem Cloud-Upload (und ebenso, wenn kein Upload gewählt wurde)
  lädt `_oeffne_in_qgis()` das Projekt mit `iface.addProject()` aus dem
  Projektordner neu.
- QGIS arbeitet danach auf genau der Fassung, die zu QFieldCloud hochgeladen
  wurde — inklusive relativer Pfade und der umgehängten ValueRelation-Quellen.
- Der Aufruf läuft verzögert über `QTimer.singleShot(0, …)`. Ein
  Projektwechsel mitten im laufenden Signalaufruf des Upload-Threads kann QGIS
  sonst zum Absturz bringen.
- Fehlt die Projektdatei oder schlägt das Laden fehl, erscheint ein Hinweis im
  Log; der Lauf gilt weiterhin als erfolgreich.

## QField-Option entfernt
Die zwischenzeitlich ergänzte Option „Projekt in QField öffnen“ ist wieder
entfernt. An dieser Stelle im Ablauf ergibt sie fachlich keinen Sinn: Das
Cloud-Projekt ist gerade erst hochgeladen, QField hat es noch nicht
synchronisiert, und der Arbeitsablauf setzt sich am Desktop in QGIS fort.

Entfernt wurden die Checkbox samt Pfadfeld und die Hilfsmethoden
`_toggle_qfield()`, `_browse_qfield()`, `_finde_qfield_pfad()`,
`_qfield_app_verzeichnis()`, `_finde_sync_projekt()`, `_starte_qfield()` und
`_oeffne_in_qfield()`. Die Gruppe „Nach Abschluss“ enthält jetzt nur noch die
QGIS-Option. Die Einstellung `naturschutz/qfield_pfad` wird nicht mehr
geschrieben.

## Nicht geändert
`qfield_project_dialog.py` baut sein Projekt ebenfalls in
`QgsProject.instance()` und speichert es dort; ein erneutes Laden ist dort
nicht ergänzt, da dieser Dialog keinen Cloud-Upload durchführt.

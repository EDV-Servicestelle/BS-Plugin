# BioSt-GIS

QGIS-Plugin der Biologischen Stationen in NRW. Es legt fertige Erfassungsprojekte
an, bringt sie nach QField und übernimmt Altdaten sowie GISPAD-Exporte.
Entwickelt und gepflegt wird es von der EDV-Servicestelle der Biologischen Stationen.

> **Früherer Name:** Bis Version 3.3.0 hieß das Plugin **NRW Naturschutz-Toolbox**.
> Ältere Installationen zeigen diesen Namen, bis Sie aktualisieren.

**[Aktuelle Version herunterladen](https://github.com/EDV-Servicestelle/BS-Plugin/releases/latest)**

## Installation

Sie brauchen die aktuelle QGIS-LTR-Version 3.x. Das Plugin läuft ab QGIS 3.28 und
ist für QGIS 4 vorbereitet.

1. Öffnen Sie die [aktuelle Version](https://github.com/EDV-Servicestelle/BS-Plugin/releases/latest)
   und laden Sie unter **Assets** die Datei `qgis_new_project_plugin_v….zip` herunter.
   Die Archive „Source code“ lassen sich nicht installieren.
2. Wählen Sie in QGIS **Erweiterungen → Erweiterungen verwalten und installieren
   → Aus ZIP installieren** und dann die heruntergeladene Datei.
3. Starten Sie QGIS neu.

Danach steht das Plugin unter **Erweiterungen → BioSt-GIS**.

**Beim Öffnen eines Projekts fragt QGIS nach Makros.** Das Erfassungsformular
enthält eingebetteten Python-Code, deshalb ist die Nachfrage normal. Lassen Sie
die Makros zu, sonst fehlen Funktionen im Formular. Die Vorgabe ändern Sie unter
**Einstellungen → Optionen → Allgemein → Makros aktivieren**.

### Auf eine neue Version aktualisieren

Installieren Sie die neue ZIP-Datei wie oben beschrieben über die alte Version und
**schließen Sie QGIS danach einmal vollständig**. Sonst kann noch der alte
Formularcode aktiv sein, und das Formular verhält sich unerwartet.

Bestehende Projekte bleiben unverändert. Neue Werte in den Referenzlisten kommen
deshalb nur in neu angelegte Projekte. Für bestehende Projekte wenden Sie sich an
die EDV-Servicestelle.

## Erste Schritte: ein Projekt anlegen

Wählen Sie **Fachschalen-Wizard …**. Zur Auswahl stehen die Fachschalen
**Fundpunkte Tiere** und **Biotopbaum**. Der Assistent führt durch
diese Schritte:

1. **Projektinformationen:** Name und Speicherort eingeben, dann auf
   **Offline laden (ohne DB)** klicken und die Fachschale wählen. Die Felder für die
   Datenbankverbindung lassen Sie dabei unbeachtet. Tragen Sie auch die
   Projektvariablen ein.
2. **Koordinatenreferenzsystem**
3. **Untersuchungsgebiet:** kann übersprungen werden
4. **Layer der Fachschale**
5. **Grundlagendaten:** Quellen und Dienste für das Projekt
6. **Zusammenfassung**
7. **Export & QFieldCloud-Upload:** Layer als GeoPackage sichern, Projekt speichern
   und auf Wunsch zu QFieldCloud übertragen

Neue Projekte starten ohne Datensätze. Das Projekt arbeitet mit GeoPackages im Projektordner und braucht dafür keinen Server.
Für den Upload brauchen Sie ein QFieldCloud-Konto. Bei der Fachschale Fundpunkte Tiere
wird die Synonymsuche für das Feld Artname in QField mitgeliefert. Sie findet Arten
auch über andere Schreibweisen und alte Namen.

Beim ersten Öffnen des Projekts fragt QField, ob das Plugin ausgeführt werden darf.
Stimmen Sie zu, sonst bleibt die Suche aus. Die Synonymsuche ist ein Zwischenstand.
Bestehende Projekte erhalten sie erst, wenn Sie **QField-Export …** erneut ausführen.

> **Brutvogel:** Die Fachschale Brutvogel steht vorerst nicht zur Auswahl, weil sie
> noch nicht sauber arbeitet. Der Menüpunkt zu den Papierrevieren gehört dazu.

## Was Sie womit erledigen

Alle Punkte liegen im Menü **Erweiterungen → BioSt-GIS**.

| Aufgabe | Menüpunkt |
| --- | --- |
| Neues Erfassungsprojekt anlegen | Fachschalen-Wizard … |
| Projekt für die Feldarbeit vorbereiten | QField-Export … |
| Alte Funddaten übernehmen (SHP, GeoPackage, GeoJSON, CSV, Excel, ODS, KML) | Fundpunkte – Altdaten importieren … |
| Eigene Schreibweisen und Artnamen ergänzen | Fundpunkte – Synonyme verwalten … |
| Fundhäufigkeit über die Zeit darstellen | Fundpunkte – Zeitreihen-Diagramm … |
| Fundpunkte ausgeben (CSV, XLSX, GeoPackage) | Fundpunkte – Export (CSV/XLSX/GPKG) … |
| GISPAD-Daten sichern und übernehmen | GISPAD-Export übernehmen … |
| Maßnahmentabelle und -karte aus GISPAD-Daten erzeugen | MAKO-Produkte aus GISPAD-Export (Notlösung) … |
| Schutzgebiete, FFH-Lebensraumtypen, ATKIS und Flurstücke abrufen | NRW Grundlagendaten abrufen … |
| Luftbilder als GeoTIFF laden | NRW Luftbild → COG … |
| Geländemodell und Höhenlinien aus LiDAR erzeugen | NRW LiDAR-Analyse … |
| Fließwege und Abflusssenken berechnen | Hydrologische Analyse … |
| Artvorkommen aus GBIF oder Ornitho.de laden | GBIF Artvorkommen … / Ornitho.de Import … |
| Personen der eigenen Station verwalten (nur Cloud-Admins) | Personen meiner Station … |

Die Punkte **PostGIS-Datenbank einrichten …** und **Grundlagen-DB verwalten …** sind
für die Datenbankverwaltung gedacht und im normalen Stationsbetrieb nicht nötig.

## Fundpunkte erfassen

**Werte festsetzen:** Mit der Stecknadel neben einem Feld im Formular übernehmen Sie
dessen Wert in jeden neuen Fundpunkt, etwa Datum oder Kartierer. Ein festgesetzter
Artname wird nur übernommen, wenn auch die Artengruppe passt.

**Zähleinheit:** Wer eine Anzahl einträgt, muss auch die Zähleinheit angeben. Die
Einheit „Brutpaare“ steht in Projekten bereit, die mit Version 3.3.0 oder neuer
angelegt wurden.

**Sensible Funde:** Fundpunkte mit gesetztem Feld `Sensibel` lässt der Menüpunkt
**Fundpunkte – Export** aus. Prüfen Sie das Ergebnis trotzdem, bevor Sie Daten
weitergeben.

## GISPAD-Daten übernehmen

GISPAD lässt sich nicht mehr dauerhaft sicher betreiben. Für die Übernahme brauchen
Sie weder GISPAD noch ODBC-Treiber, sondern nur den Export als File-Geodatabase
(Ordner oder ZIP).

1. Wählen Sie **GISPAD-Export übernehmen …** und dann den Export.
2. Lassen Sie **Alles sichern** ausgewählt. Was jetzt nicht übernommen wird, kommt
   später womöglich nicht mehr heraus.
3. Prüfen Sie die Zieldatei und starten Sie die Übernahme. QGIS bleibt währenddessen
   bedienbar.

Die Geometrien werden dabei repariert und einheitlich ausgerichtet. Die Anzahl der
Reparaturen steht in den Hinweisen. Verwenden Sie für BK und MAS vorerst nur
**Alles sichern**, die fachliche Auswahl ist für diese Klassen noch nicht an echten
Exporten geprüft.

Details stehen in der [Beschreibung der GISPAD-Übernahme](docs/GISPAD_Uebernahme.md).

## MAKO-Produkte: nur für dringende Fälle

Der MAKO-Konverter des LANUK ist außer Betrieb. Dieser Menüpunkt ist eine
**Notlösung** dafür und ersetzt ihn nicht.

- **Eingabe:** GISPAD-Export mit Maßnahmenflächen (MAS) und Biotoptypen (BT), für die
  Biotopbaum-Anzahl auch BAUM. Die FFH-Gebietsgrenze kommt aus einem Layer im Projekt,
  zum Beispiel über **NRW Grundlagendaten abrufen …**.
- **Ergebnis:** Maßnahmentabelle (ODT und PDF), Ziel- und Maßnahmenkarte (PDF und
  Drucklayout im Projekt) sowie ein GeoPackage mit den Kartenlayern.
- **Korrekturen** gehören in die Daten, nicht in die fertige Tabelle.

**Wald ist ein Sonderfall.** Für Wald gelten Vorgaben von Wald und Holz NRW, die das
Plugin nicht abbildet. Enthält der Export Wald-Ziele oder Wald-Maßnahmen, nennt der
Dialog die betroffenen Flächen. Tabelle und Karte müssen Sie dafür gesondert abstimmen.

## Zusatzmodule

Die meisten Funktionen laufen mit einer normalen QGIS-Installation. Fehlt ein Modul,
installieren Sie es in der Python-Umgebung von QGIS (unter Windows in der
**OSGeo4W Shell**):

| Funktion | Modul | Befehl |
| --- | --- | --- |
| LiDAR-Analyse | laspy | `python -m pip install "laspy[lazrs]"` |
| Treffsichere Artnamen beim Altdaten-Import | scikit-learn | `python -m pip install scikit-learn` |
| Hydrologische Analyse, Gewässermittellinien der Grundlagendaten | scipy | `python -m pip install scipy` |

## Hilfe und Fehler melden

Schreiben Sie an die EDV-Servicestelle: [blinn@bskw.de](mailto:blinn@bskw.de).
Technische Fehler können Sie auch als
[Issue auf GitHub](https://github.com/EDV-Servicestelle/BS-Plugin/issues) melden.

Hilfreich sind diese Angaben:

- Plugin-Version und QGIS-Version
- der Menüpunkt und was Sie zuletzt getan haben
- die Meldung aus dem Protokoll von QGIS (Sprechblasen-Symbol unten rechts), Reiter
  „BioSt-GIS“
- die Datei `naturschutz_debug.log` in Ihrem Benutzerordner

> **GitHub ist öffentlich.** Stellen Sie dort keine Fundorte geschützter Arten,
> personenbezogenen Daten, Projektdateien, Zugangsdaten oder Logdateien ein. Solche
> Unterlagen schicken Sie direkt an die EDV-Servicestelle, Zugangsdaten aber nicht
> per normaler E-Mail.

## Mitentwickeln und Lizenz

Aufbau des Repositorys, Paketbau und Abläufe stehen unter
[Entwicklung und Repository](docs/ENTWICKLUNG_Repository.md).

Das Plugin steht unter der [GNU General Public License v3.0](LICENSE).

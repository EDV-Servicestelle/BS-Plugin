# Trennung Stadium / Geschlecht — Änderungsprotokoll

Hintergrund: Nach der LANUK-Abstimmung wird das bisherige Kombi-Feld **Stadium**
(das die als „Geschlecht“ benannte Kombiliste nutzte) in **zwei getrennte Felder**
mit **je eigener Referenzliste** aufgeteilt: `Stadium` und `Geschlecht`.

Übergangslösung bis zur Lieferung der endgültigen LANUK-Listen:
- **Stadium**: 19 Werte (unbestimmt, adult, Eier, Exuvien, juvenil, Köcher, Königin,
  Laich, Larve, Puppe, Imago, subadult, Pullus, 1.–5. KJ, immatur …)
- **Geschlecht**: 4 Werte (unbestimmt, Männchen, Weibchen, weibchenfarbig)

Beide Listen sind flach (parentid = 0), Schema wie die übrigen Listen
(`entityid · term · parentid · listitemid`, Key = entityid).

## 1. Offline-GeoPackages
- `data/fundpunkte_tiere/Referenzen.gpkg`
  - Liste `Geschlecht` auf 4 Werte reduziert.
  - Neue Liste `Stadium` (19 Werte) angelegt (inkl. gpkg_contents-/ogr_contents-
    Registrierung und Feature-Count-Trigger).
- `data/fundpunkte_tiere/Fundpunkte.gpkg`
  - Feld `Geschlecht` (TEXT, optional) in Tabelle `Fund` ergänzt; `Stadium` bleibt.
- Reproduzierbar über `split_gpkg.py`.

## 2. Benutzeroberfläche (QGIS/QField-Formular)
- `data/fundpunkte_tiere/fund.qml`
  - Feld `stadium` → ValueRelation auf Liste **Stadium** (bisher: Geschlecht).
  - Neues Feld `geschlecht` → ValueRelation auf Liste **Geschlecht**.
  - Alias „Stadium/Geschlecht“ → getrennte Aliase „Stadium“ und „Geschlecht“;
    Formularlayout, Spalten- und Constraint-Einträge ergänzt.

## 3. Fachschalen-Wizard
- `fachschalen_config.py`
  - `value_relations`: Eintrag `Stadium` → ref_table `stadium`; neuer Eintrag
    `Geschlecht` → ref_table `geschlecht`.
  - `ref_tables` und `gpkg_data.ref_layers` um **Stadium** und **Geschlecht** ergänzt.
- `qfield_project_dialog.py`
  - Fundpunkte-Formular („Optionale Angaben“) um Feld **Geschlecht** ergänzt.
- `fundpunkte_import_dialog.py`
  - Auto-Feldmapping getrennt: `stadium` → ("stadium"),
    neu `geschlecht` → ("geschlecht", "sex", "gender").
    (Bisher wurden sex/geschlecht fälschlich auf Stadium gemappt.)
- `postgis_setup_dialog.py`
  - Referenzlisten-Klassifikation um `stadium` (und `bewertung_erhaltungszustand`)
    ergänzt, damit die neue Liste beim PostGIS-Upload im Ref-Schema landet.

Die ValueRelations werden zur Projekt-Bauzeit programmatisch aus
`fachschalen_config.py` gesetzt (`_apply_value_relations`, Auflösung per LayerName /
`layer.id()`); die hartcodierten Layer-IDs in `fund.qml` werden dabei überschrieben.

## 4. Datenmodell (Anlage A)
- A.1: Feld `Stadium` verweist jetzt auf Liste **Stadium**; neues optionales Feld
  `Geschlecht` (Liste **Geschlecht**).
- A.2: Zeile „Geschlecht (61, Stadium)“ ersetzt durch **Stadium (19)** und
  **Geschlecht (4)**; Übergangshinweis ergänzt.
- A.4: „sieben Referenzlisten“ → „acht Referenzlisten“.

## 5. Leistungsbeschreibung
- §5.3: Attributliste um **Geschlecht** ergänzt
  (Artname, Status, Stadium, Geschlecht, Zähleinheit, vier Bewertungsfelder).

## Nicht angefasst (bewusst)
- Fachschale **brutvogel** (eigenes Feld `Stadium_Geschlecht`, separates Datenmodell).
- `kein_Export` (Umbenennung in `sensibel` ist eine separate Entscheidung).
- Altdaten-Migration bestehender Fund-Datensätze (bei Bedarf separater Schritt).

---

# Nachtrag: Kennung beim Altdaten-Import (Auto-UUID, nicht mappbar)

Anforderung: Beim Altdaten-Import muss `Kennung` automatisch mit einer UUID
befüllt werden und darf nicht gemappt werden.

Befund: Die automatische UUID-Befüllung existierte bereits in
`core/import_core.py`, `Kennung` stand in der Mapping-Tabelle aber als normales
Zielfeld zur Auswahl. Da das manuelle Mapping **nach** der UUID-Zuweisung
ausgeführt wird, konnte eine (auch versehentliche) Zuordnung die erzeugte UUID
still überschreiben — insbesondere weil das Auto-Mapping eine gleichnamige
Quellspalte „kennung“ per exaktem Namenstreffer selbst vorbelegt hätte.

## Änderungen
- `core/import_core.py`
  - Neue Kategorie `UUID_FIELDS = {"Kennung"}` (analog zu AUTO_/GEO_/DATE_FIELDS).
  - Neue Farbe `COLOR_UUID` für die Mapping-Tabelle.
  - `uuid` wird am Modulkopf importiert (`import uuid as _uuid_mod`) statt je
    Feature; Befüllung läuft über `UUID_FIELDS`.
  - **Schutz im Mapping-Loop**: Zielfelder aus `UUID_FIELDS` werden übersprungen,
    sodass eine UUID auch durch eine ältere gespeicherte Konfiguration nicht
    überschrieben werden kann.
- `fundpunkte_import_dialog.py`
  - `Kennung` bleibt in der Mapping-Tabelle sichtbar (Transparenz), erhält aber
    ausschließlich den Modus „Auto (uuid) – nicht mappbar“; die ComboBox ist
    deaktiviert und mit erklärendem Tooltip versehen.
  - Wertespalte zeigt `uuid()` statt „—“.
  - Auto-Mapping belegt `UUID_FIELDS` nicht mehr mit Quellfeldern vor.
  - `_read_mapping()` schließt `UUID_FIELDS` zusätzlich hart aus.

## Verhalten
- Format wie der QGIS-Ausdruck `uuid()`: `{GROSSBUCHSTABEN-MIT-BINDESTRICHEN}`.
- Jeder importierte Datensatz erhält eine eigene, neue Kennung.
- Eine in den Altdaten vorhandene Quell-ID (z. B. Spalte „kennung“) wird **nicht**
  verworfen: Da sie nicht gemappt ist, landet sie automatisch in der Tabelle
  `Fund_Quellfelder` und bleibt über die neue Kennung verknüpft nachvollziehbar.

---

# Nachtrag: Eingabedatum beim Altdaten-Import (Auto = aktuelles Datum, nicht mappbar)

Anforderung: `Eingabedatum` muss beim Altdaten-Import automatisch mit dem
aktuellen Datum belegt werden.

Befund: `Eingabedatum` kam im Import-Code bisher **überhaupt nicht** vor. Es wurde
weder automatisch gesetzt noch als Systemfeld behandelt, sondern erschien in der
Mapping-Tabelle als gewöhnliches Zielfeld — bei einer gleichnamigen Quellspalte
hätte das Auto-Mapping es sogar selbst vorbelegt. Laut Anlage A ist es jedoch ein
Systemfeld (Pflicht: ja, Editierbar: nein, Standardwert `now()`).

## Änderungen
- `core/import_core.py`
  - Neue Kategorie `NOW_FIELDS = {"Eingabedatum"}`.
  - Neue Sammelmenge `PROTECTED_FIELDS = UUID_FIELDS | NOW_FIELDS` für alle
    automatisch gesetzten, gegen Mapping geschützten Felder.
  - `Eingabedatum` wird beim Feature-Bau auf den Tag des Imports gesetzt
    (ISO-Format `YYYY-MM-DD`, passend zum Datentyp DATE).
  - Der Schutz im Mapping-Loop greift jetzt für `PROTECTED_FIELDS`.
- `fundpunkte_import_dialog.py`
  - Kategorie `auto_uuid` zu `auto_fix` verallgemeinert; beide geschützten Felder
    nutzen denselben Pfad.
  - `Eingabedatum` bleibt sichtbar, aber nur mit dem Modus
    „Auto (aktuelles Datum) – nicht mappbar“ (ComboBox deaktiviert, Tooltip).
  - Wertespalte zeigt `now()` bzw. `uuid()`.
  - Auto-Mapping und `_read_mapping()` schließen `PROTECTED_FIELDS` aus.

## Abgrenzung
- `Beobachtungsdatum` bleibt bewusst **normal mappbar** — dort gehört ein Datum
  aus den Altdaten fachlich hin.
- `Aenderungsdatum` bleibt unverändert in `DATE_FIELDS`: automatisch gesetzt,
  aber weiterhin auf „Quellfeld“/„Fixwert“ umstellbar. Eine Angleichung an
  `PROTECTED_FIELDS` wäre konsequent (Anlage A: Editierbar = nein), ist aber
  bisher nicht beauftragt.

---

# Fehlerbehebung: NOT NULL constraint failed: Fund.Aenderungsdatum

Symptom: `Layer Fund: OGR-Fehler beim Erzeugen des Objekts -21998:
failed to execute insert : NOT NULL constraint failed: Fund.Aenderungsdatum`

## Ursachenanalyse
`Fund.Aenderungsdatum` ist in der DB `DATETIME NOT NULL` ohne DB-Default. Der
Wert kam beim Import auf zwei Wegen als NULL in den INSERT:

1. **Überschreibbares Systemfeld.** `Aenderungsdatum` lag in `DATE_FIELDS` und
   war im Mapping-Dialog auf „Quellfeld“ bzw. „Fixwert“ umstellbar. Ein leerer
   Fixwert oder eine leere/unlesbare Quellspalte wurde geschrieben, vom
   OGR-Provider nicht als Datum interpretiert und als NULL gespeichert.
2. **Typ des Werts.** Die automatische Belegung übergab einen Python-String
   (`date.today().isoformat()`) an ein DATETIME-Feld. Kann der OGR-Provider den
   String nicht in ein Datum konvertieren, setzt er das Feld still auf NULL.

Ausgeschlossen wurden: fehlende Default-Ausdrücke (die `layer_styles`-Tabelle
im GeoPackage enthält korrekt `now()` für `Aenderungsdatum`) sowie die
Kleinschreibung der Feldnamen in `fund.qml` — diese ist beabsichtigt, da
`fund.qml` den PostGIS-Pfad bedient, wo ogr2ogr die Spalten kleinschreibt.

## Änderungen (`core/import_core.py`)
- `NOW_FIELDS = {"Eingabedatum", "Aenderungsdatum"}` — `Aenderungsdatum` ist
  jetzt ebenfalls ein geschütztes Systemfeld und nicht mehr mappbar
  (entspricht Anlage A: Editierbar = nein). `DATE_FIELDS` ist damit leer.
- Neue Helfer `_field_typename()`, `_now_for_field()` und `_coerce_for_field()`:
  - Automatische Werte werden **typgerecht** gesetzt: `QDateTime` für DATETIME,
    `QDate` für DATE statt ISO-Strings.
  - Gemappte Werte für Datumsfelder werden konvertiert; erkannt werden ISO
    sowie `dd.MM.yyyy`, `yyyy/MM/dd`, `dd/MM/yyyy`, `yyyyMMdd`.
  - Nicht interpretierbare oder leere Werte werden **nicht** geschrieben,
    statt still eine NULL in eine NOT-NULL-Spalte zu setzen.
- Die Typermittlung nutzt `typeName()` und ist damit Qt5/Qt6-unabhängig
  (relevant für das Ziel QGIS 4.2 LTR).

## Änderungen (`fundpunkte_import_dialog.py`)
- `Aenderungsdatum` erscheint wie `Kennung`/`Eingabedatum` als geschütztes
  Auto-Feld („Auto (aktuelles Datum) – nicht mappbar“); Tooltip verallgemeinert.

## Hinweis
`Beobachtungsdatum` bleibt `DATE NOT NULL` **und** mappbar — fachlich richtig.
Enthält die Quelle dort kein lesbares Datum, schlägt der Datensatz weiterhin
bewusst fehl, statt ein falsches Datum zu erfinden.

---

# Gründliche Prüfung der Datumsfelder im Altdaten-Import

Die Datumslogik wurde gegen echtes Qt (PyQt5) mit realistischen Altdaten-Formaten
getestet. Dabei kamen drei weitere Fehler zutage.

## Gefundene Fehler
1. **Falsche Uhrzeit bei historischen Datensätzen.** Wurde ein nicht-ISO-Datum
   (z. B. `19.07.2001`) in ein DATETIME-Feld geschrieben, hängte der Code die
   *aktuelle* Uhrzeit an. Ein Fund von 2001 bekam so die Zeit des Imports.
   Jetzt: Mitternacht, sofern die Quelle keine Zeit liefert.
2. **Fragile Truncation.** Die Konvertierung schnitt den Text auf
   `len(pattern)+2` Zeichen zu, um Zeitanteile zu entfernen. Qt lehnt Anhänge
   strikt ab, sodass das Verhalten von der Musterlänge abhing. Ersetzt durch
   echte Datum/Zeit-Muster plus sauberes Abtrennen des Zeitanteils.
3. **`Fund_Fehlend` blieb leer.** Datum, Kartierer und Fundort wurden über die
   *Ziel*feldnamen aus der Quelle gelesen; Altdaten benennen die Spalten aber
   anders (`k_datum`, `datum` …). Jetzt wird das Mapping ausgewertet.

## Bewusst nicht geraten wird
Qt liest `19.07.01` als **1901**-07-19. Muster mit zweistelligem Jahr sind daher
ausgeschlossen — sie würden still um 100 Jahre falsche Funddaten erzeugen.
Ebenfalls abgelehnt: reine Jahreszahlen (`2001`), Jahr-Monat (`2001-07`),
Excel-Datumsserien (`37091`) und US-Format (`07/19/2001`, mehrdeutig zu
`dd/MM/yyyy`). Diese Werte werden gemeldet, nicht interpretiert.

## Unterstützte Formate (getestet)
ISO (`2001-07-19`, auch einstellig `2001-7-9`), ISO mit Zeit (`T` und
Leerzeichen), deutsch (`19.07.2001`, `5.7.2001`), deutsch mit Zeit
(`19.07.2001 14:30[:05]`), kompakt (`20010719`), Schrägstrich (`19/07/2001`,
`2001/07/19`), Bindestrich (`19-07-2001`), Punkt-ISO (`2001.07.19`), führender
und nachgestellter Leerraum. Ungültige Kalenderdaten (`31.02.2001`) werden
korrekt abgewiesen, Schaltjahre (`29.02.2000`) akzeptiert.

## Neue Rückmeldung statt kryptischer Fehler
- Nicht lesbare Datumswerte werden je Zielfeld gezählt und mit Beispielwerten
  im Import-Log ausgegeben, samt Hinweis auf das erwartete Format.
- Datensätze ohne gültiges **Pflicht**-Datum (NOT NULL, z. B.
  `Beobachtungsdatum`) werden mit klarer Meldung übersprungen, statt am
  OGR-NOT-NULL-Constraint aufzulaufen. Die Pflichtfelder werden dynamisch aus
  den Feld-Constraints des Ziel-Layers ermittelt.

## Testergebnis
Durchlauf mit 10 typischen Altdaten-Werten gegen die echte `Fund`-DDL:
5 importiert, 5 mit benannter Begründung übersprungen, kein einziger
kryptischer NOT-NULL-Abbruch.

---

# Aenderungsdatum: now() bei jedem Speichern (applyOnUpdate)

Anforderung: `Aenderungsdatum` wird mit `now()` gesetzt und muss bei **jedem
Speichern** des Layers aktualisiert werden.

## Befund
Die Fachschalen-Konfiguration (`fachschalen_config.py`) und `fund.qml`
(PostGIS-Pfad) hatten bereits `apply_on_update = True` bzw. `applyOnUpdate="1"`.
Die für das GeoPackage **maßgebliche** `layer_styles`-Tabelle in
`Fundpunkte.gpkg` stand jedoch auf `applyOnUpdate="0"` — das Änderungsdatum
wäre dort auf dem Anlagedatum stehen geblieben.

Beim Abgleich fiel dieselbe Abweichung bei den Koordinatenfeldern auf:
`Utm_east` und `Utm_north` standen in `layer_styles` ebenfalls auf `0`, obwohl
die Konfiguration `True` vorsieht. Die UTM-Werte hätten sich beim Verschieben
eines Fundpunktes nicht mitaktualisiert.

## Änderungen
- `data/fundpunkte_tiere/Fundpunkte.gpkg`, Tabelle `layer_styles`:
  - `Aenderungsdatum` → `applyOnUpdate="1"`
  - `Utm_east`, `Utm_north` → `applyOnUpdate="1"`
- Unverändert (bewusst einmalig beim Anlegen):
  `Kennung`, `Eingabedatum`, `Beobachtungsdatum` → `applyOnUpdate="0"`.
- Anlage A: Fußnote zu A.1 erläutert jetzt den Unterschied zwischen einmaliger
  und fortlaufender Auswertung der Standardwerte.

## Geprüft
- Alle mitgelieferten GeoPackages auf dieselbe Inkonsistenz durchsucht; nur
  `Fundpunkte.gpkg` war betroffen.
- `Aenderungsdatum` ist im Formular `editable="0"` und `reuseLastValue="0"`,
  kann also weder manuell überschrieben noch aus dem Vorgänger übernommen
  werden.
- Beim Altdaten-Import wird `Aenderungsdatum` weiterhin explizit auf den
  Importzeitpunkt gesetzt (geschütztes Systemfeld, nicht mappbar).

## Hinweis
`applyOnUpdate` greift beim Bearbeiten über QGIS bzw. QField (Formular/
Bearbeitungspuffer). Schreibt ein Fremdwerkzeug direkt über den Provider oder
per SQL in die Tabelle, wird der Ausdruck nicht ausgewertet.

# fid-Schutz und Reihenfolge der Formularreiter

## 1. Primärschlüssel `fid` gegen versehentliches Bearbeiten schützen

### Befund
`fid` war in beiden Stilquellen als `editable="1"` konfiguriert und im
GeoPackage-Formular mit dem Widget `TextEdit` sichtbar. Im QField-Dialog stand
`fid` zwar in der `hidden`-Liste — das entfernt das Feld aber nur aus dem
Formular, in der **Attributtabelle** blieb es editierbar. Eine versehentliche
Änderung des Primärschlüssels zerreißt die Verknüpfung zu Anhängen,
Relationen und Altdatenbezügen.

### Änderungen
- `data/fundpunkte_tiere/Fundpunkte.gpkg`, Tabelle `layer_styles`:
  `fid` → `editable="0"`, Widget `TextEdit` → `Hidden`.
- `data/fundpunkte_tiere/fund.qml` (PostGIS-Pfad): dieselben Änderungen.
- `qfield_project_dialog.py`: `fid` wird **zentral** in
  `build_form_layout()` schreibgeschützt gesetzt — nicht je Fachschale,
  sondern für alle (biotopbaum, brutvogel usw. profitieren automatisch).
- `new_project_wizard.py`: neuer Helfer `_schuetze_fid()`, aufgerufen aus
  `_apply_default_values()`. Damit greift der Schutz auch dann, wenn ein Layer
  keine Stildatei mitbringt. Der Helfer ist fehlertolerant und kann den
  Projektbau nie abbrechen.

### Nebenbefund mitbehoben
`Geschlecht` fehlte seit der Stadium/Geschlecht-Trennung im `<editable>`-Block
der `layer_styles`-QML; jetzt mit `editable="1"` ergänzt.
Im QField-Formular fehlte `Eingabedatum` im Reiter „Systemdaten“ — es wäre in
einem automatischen Reiter „Weitere“ gelandet. Jetzt in den Systemdaten und in
der readonly-Liste.

## 2. Reihenfolge Stammdaten / Systemdaten getauscht

### Befund
Code und Stildateien waren uneinheitlich:
`qfield_project_dialog.py` führte bereits **Stammdaten vor Systemdaten**,
beide Stilquellen (`layer_styles` im GeoPackage und `fund.qml`) dagegen
**Systemdaten vor Stammdaten**.

### Änderung
In beiden Stilquellen sind die Reiter jetzt einheitlich angeordnet:

`Pflichtangaben → Optionalen Angaben → Stammdaten → Systemdaten`

Die Umstellung erfolgte über einen XML-Parser (nicht per Textersetzung), damit
die Container samt aller enthaltenen Felder und Attribute unverändert
umgehängt werden.

## 3. Dokumentation
Anlage A: `fid` ist jetzt als **nicht editierbar** ausgewiesen; ergänzt wurde
ein Hinweis auf den Schreibschutz des Primärschlüssels und auf die verbindliche
Reihenfolge der Formularreiter.

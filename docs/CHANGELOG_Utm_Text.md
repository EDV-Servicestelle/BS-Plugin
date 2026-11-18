# Utm_east als Text

Stand: 16.11.2026

## Anlass

Laut Datenmodell sind beide Koordinatenfelder der Tabelle `Fund` Text; Zahlen
(REAL) führen in den FME-Prozessen des LANUK zu Problemen. In der Vorlage
`Fundpunkte.gpkg` war `Utm_east` jedoch als REAL angelegt, `Utm_north` als TEXT.
Alles, was aus der Vorlage entsteht, hat den Fehler geerbt: die GeoPackages der
Projekte und – über das PostGIS-Setup – die Tabelle in der Datenbank
(`double precision`).

## Änderungen

| Stelle | vorher | jetzt |
|---|---|---|
| `qgis_plugin/data/fundpunkte_tiere/Fundpunkte.gpkg` | `Utm_east` REAL | TEXT |
| `datamodel/fundpunkte_tiere/Fundpunkte.sql` | aus der Vorlage erzeugt | neu erzeugt |
| `qgis_plugin/core/import_core.py` | `Utm_east` als Zahl geschrieben | als Text, wie `Utm_north` |
| `qgis_plugin/papierreviere_export_dialog.py` | beide Felder als Zahl geschrieben | als Text |
| `docs/Anlage_A_Datenmodell.md` | `Utm_east` REAL | TEXT |

Formular, Vorgabeausdrücke (`x(@geometry)`, `y(@geometry)`) und Layerstil
bleiben unverändert – beide Felder waren dort schon Textfelder.

## Bestehende Daten

**GeoPackages** aus älteren Plugin-Versionen (Datei darf nicht geöffnet sein):

```
python tools/gpkg_utm_text.py --pruefen <datei.gpkg>
python tools/gpkg_utm_text.py <datei.gpkg>
```

Das Skript legt eine Sicherung `<datei>.vor_utm_text` an, ändert den Spaltentyp
ohne die Spaltenreihenfolge zu verändern und wandelt vorhandene Zahlen in Text
um. Es ist wiederholbar.

**Datenbank** (als `postgres`, je Datenbank mit der Tabelle):

```sql
ALTER TABLE fundpunkte_tiere.fund
  ALTER COLUMN "Utm_east" TYPE character varying USING "Utm_east"::text;
```

## Offen

- `docs/Anlage_A_Datenmodell.docx` aus der Markdown-Fassung neu erzeugen.
- Die Schreibweise der Koordinaten ist noch uneinheitlich: Das Formular schreibt
  die volle Genauigkeit, der Import zwei, der Papierreviere-Export eine
  Nachkommastelle. Festlegen, was das LANUK erwartet, und angleichen.

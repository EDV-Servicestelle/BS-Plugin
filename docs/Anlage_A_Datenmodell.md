Anlage A – Datenmodell „Fundpunkte Tiere“

**Tabellenstruktur, Felder und Referenzlisten**

**Datentabelle: **Fund – Punktgeometrie (POINT), Koordinatenreferenzsystem ETRS89 / UTM Zone 32N (EPSG:25832), Primärschlüssel fid. Speicherformat: OGC GeoPackage. Die Werte der Auswahlfelder werden als stabile IDs der Referenzlisteneinträge gespeichert (nicht als Anzeigetext).

# A.1 Felder der Tabelle Fund

| **Kategorie** | **Feld** | **Datentyp** | **Pflicht** | **Editierbar** | **Standardwert** | **Referenzliste (Schlüssel → Wert)** |
| --- | --- | --- | --- | --- | --- | --- |
| System | fid | INTEGER | ja | **nein** | – | – |
| System | Kennung | TEXT | ja | nein | uuid() | – |
| System | Utm_east | REAL | ja | nein | x(@geometry) | – |
| System | Utm_north | TEXT | ja | nein | y(@geometry) | – |
| System | Aenderungsdatum | DATETIME | ja | nein | now() | – |
| System | Eingabedatum | DATE | ja | nein | now() | – |
| System | Artname_deutsch | TEXT | nein | ja | – | – |
| System | Artname_wiss | TEXT | nein | ja | – | – |
| Pflicht | Artengruppe | TEXT | ja | ja | – | Artengruppen (Schlüssel: listitemid, Wert: term) |
| Pflicht | Artname | TEXT | ja | ja | – | Arten (Schlüssel: entityid, Wert: term) |
| Pflicht | Beobachtungsdatum | DATE | ja | ja | now() | – |
| optional | kein_Export | BOOLEAN | nein | ja | – | – |
| optional | Kartierer | TEXT | nein | ja | – | – |
| optional | Institution | TEXT | nein | ja | – | Institution (Schlüssel: entityid, Wert: term) |
| optional | Anzahl | MEDIUMINT | nein | ja | – | – |
| optional | Zaehleinheit | TEXT | nein | ja | – | Einheit (Schlüssel: entityid, Wert: term) |
| optional | Status | TEXT | nein | ja | – | Status (Schlüssel: entityid, Wert: term) |
| optional | Stadium | TEXT | nein | ja | – | Stadium (Schlüssel: entityid, Wert: term) |
| optional | Geschlecht | TEXT | nein | ja | – | Geschlecht (Schlüssel: entityid, Wert: term) |
| optional | Fundort | TEXT | nein | ja | – | – |
| optional | Bemerkung | TEXT | nein | ja | – | – |
| optional | pop_zustand | TEXT | nein | ja | – | Bewertung_Erhaltungszustand (Schlüssel: entityid, Wert: term) |
| optional | habitatqualitaet | TEXT | nein | ja | – | Bewertung_Erhaltungszustand (Schlüssel: entityid, Wert: term) |
| optional | pop_beeintraechtigung | TEXT | nein | ja | – | Bewertung_Erhaltungszustand (Schlüssel: entityid, Wert: term) |
| optional | erhaltung_gesamt | TEXT | nein | ja | – | Bewertung_Erhaltungszustand (Schlüssel: entityid, Wert: term) |

*Geordnet und farblich nach Kategorie: System (grau, automatisch/abgeleitet, gesperrt), Pflicht (rot, NOT NULL, Nutzereingabe), optional (gelb). Spalte „Pflicht“ = NOT-NULL-Constraint in der Datenbank; Systemfelder sind ebenfalls NOT NULL, werden aber automatisch gesetzt. Der Primärschlüssel fid wird ausschließlich von der Datenbank vergeben; er ist im Formular ausgeblendet und schreibgeschützt, da eine versehentliche Änderung die Verknüpfung zu Anhängen, Relationen und Altdatenbezügen zerstören würde. Die Formularreiter sind in der Reihenfolge Pflichtangaben, Optionale Angaben, Stammdaten, Systemdaten angeordnet. Standardwerte sind QGIS-Ausdrücke, die von QField ausgeführt werden (z. B. uuid(), now(), x(@geometry)/y(@geometry)). Dabei ist zwischen einmaliger und fortlaufender Auswertung zu unterscheiden: Kennung, Eingabedatum und Beobachtungsdatum werden **einmalig beim Anlegen** des Datensatzes gesetzt; Aenderungsdatum sowie Utm_east/Utm_north werden **bei jeder Änderung erneut** ausgewertet (QGIS-Eigenschaft „applyOnUpdate“), sodass das Änderungsdatum jeden Speichervorgang und die Koordinaten jede Verschiebung der Geometrie abbilden.*

# A.2 Referenzlisten

Die zulässigen Werte werden im GeoPackage „Referenzlisten“ bereitgestellt (Anlage C). Alle Listen besitzen die Spalten entityid, term, parentid und listitemid; die Artenliste zusätzlich Name_deutsch und anzeigename.

| **Referenzliste** | **Einträge** | **Schlüssel (Key)** | **Wertefeld** | **Verwendet in Feld** | **Hinweis** |
| --- | --- | --- | --- | --- | --- |
| Artengruppen | 41 | listitemid | term | Artengruppe | Steuert die Kaskade (Filter für Artname). |
| Arten | 13291 | entityid | term | Artname | Gefiltert nach Artengruppe (parentid = current_value(Artengruppe)). |
| Institution | 94 | entityid | term | Institution | – |
| Einheit | 13 | entityid | term | Zaehleinheit | – |
| Status | 66 | entityid | term | Status | – |
| Stadium | 19 | entityid | term | Stadium | Aus der bisherigen Kombiliste herausgelöst (Trennung Stadium/Geschlecht). |
| Geschlecht | 4 | entityid | term | Geschlecht | Aus der bisherigen Kombiliste herausgelöst; enthält nur noch die Geschlechts-Werte (unbestimmt, Männchen, Weibchen, weibchenfarbig). |
| Bewertung_Erhaltungszustand | 5 | entityid | term | 4 FFH-Bewertungsfelder | LANUK-Liste 422: A/B/C/D und „keine Angabe“ (FFH-Erhaltungszustand). |

*Hinweis (Stand der Abstimmung mit dem LANUK): Die bisherige Kombiliste „Stadium/Geschlecht“ wird in die zwei getrennten Felder Stadium und Geschlecht mit je eigener Referenzliste überführt. Bis das LANUK die endgültigen Referenzlisten für beide Merkmale bereitstellt, werden die hier aufgeführten, aus der Altliste abgeleiteten Übergangslisten (Stadium: 19 Werte, Geschlecht: 4 Werte) verwendet. Ein späterer Austausch der GeoPackage-Listen erfolgt ohne Struktureingriff.*

# A.3 Synonyme zur Artenauswahl (Basislösung im Datenmodell)

Synonyme, Alt- und Trivialnamen lassen sich bereits auf Datenmodell-Ebene offline-tauglich abbilden (Basislösung, ohne Plugin). Dazu werden zu Arten zusätzliche Synonymzeilen in die Referenzliste „Arten“ aufgenommen, deren Schlüssel (entityid) auf die akzeptierte Art verweist. Die Eingabe eines Synonyms führt so zur akzeptierten entityid; die Artengruppen-Kaskade bleibt erhalten, sofern die Synonymzeile dieselbe parentid (Artengruppe) trägt. Damit beim Zurück-Anzeigen stets der akzeptierte Name erscheint, ist je entityid die kanonische Zeile zuerst zu sortieren.

**ValueRelation-Konfiguration: **Key = entityid, Value = anzeigename, FilterExpression = „parentid = current_value('Artengruppe')“, UseCompleter = true. Diese Variante funktioniert mit dem Standard-Widget offline in QGIS und QField.

## Struktur der Master-Synonymtabelle (normalisiert)

Aus dieser normalisierten Mastertabelle werden die Synonymzeilen für die Referenzliste „Arten“ erzeugt; die Mastertabelle selbst wird nicht ins Feldprojekt paketiert.

| **Spalte** | **Typ** | **Bedeutung** |
| --- | --- | --- |
| fid | INTEGER PK | Primärschlüssel |
| synonym_term | TEXT | Synonym-/Alt-/Trivialname (Suchtext) |
| akzeptiert_entityid | INTEGER | Fremdschlüssel → Arten.entityid (akzeptierte Art) |
| art | TEXT | Typ des Namens: wissenschaftlich / deutsch / Synonym / Code |
| quelle | TEXT | Herkunft/Referenz (optional) |

*Das darüber hinausgehende verdeckte Synonym-Register (Synonyme nur durchsuchbar, Anzeige stets des akzeptierten Namens) ist Gegenstand der optionalen Plugin-Funktion (Leistungsbeschreibung, Abschnitt 5.4).*

# A.4 Beziehungsdiagramm

*UML-Übersicht der Tabelle Fund und der acht Referenzlisten (Schlüssel/Wert-Bindungen, Kaskade Artengruppen → Arten). Felder geordnet und farblich nach System (grau), Pflicht (rot) und optional (gelb).*
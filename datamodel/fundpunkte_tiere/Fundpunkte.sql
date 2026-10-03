-- Erzeugt aus Fundpunkte.gpkg
-- Nicht von Hand aendern: tools/export_from_gpkg.py

CREATE TABLE "Fund" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "geom" POINT, "Kennung" TEXT NOT NULL, "Utm_east" REAL NOT NULL, "Utm_north" TEXT NOT NULL, "Aenderungsdatum" DATETIME NOT NULL, "Artengruppe" TEXT NOT NULL, "Artname" TEXT NOT NULL, "Beobachtungsdatum" DATE NOT NULL, "kein_Export" BOOLEAN, "Kartierer" TEXT, "Institution" TEXT, "Anzahl" MEDIUMINT, "Zaehleinheit" TEXT, "Status" TEXT, "Stadium" TEXT, "Fundort" TEXT, "Bemerkung" TEXT, Artname_deutsch TEXT DEFAULT '', Artname_wiss    TEXT DEFAULT '', "Eingabedatum" DATE NOT NULL, "pop_zustand" TEXT, "habitatqualitaet" TEXT, "pop_beeintraechtigung" TEXT, "erhaltung_gesamt" TEXT, "Geschlecht" TEXT);

CREATE TABLE layer_styles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        f_table_catalog TEXT, f_table_schema TEXT, f_table_name TEXT,
        f_geometry_column TEXT, styleName TEXT, styleQML TEXT, styleSLD TEXT,
        useAsDefault INTEGER, description TEXT, owner TEXT, ui TEXT, update_time TEXT);

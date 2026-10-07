-- Erzeugt aus Referenzen.gpkg
-- Nicht von Hand aendern: tools/export_from_gpkg.py

CREATE TABLE "Arten" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT, Name_deutsch TEXT DEFAULT '', anzeigename TEXT DEFAULT '');

CREATE TABLE "Arten_Synonyme"("fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,"synonym_term" TEXT,"akzeptiert_entityid" MEDIUMINT,"parentid" TEXT,"art" TEXT,"quelle" TEXT, "erfasst_von" TEXT, "erfasst_am" TEXT);

CREATE TABLE "Artengruppen" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

CREATE TABLE "Bewertung_Erhaltungszustand" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

CREATE TABLE "Einheit" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

CREATE TABLE "Geschlecht" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

CREATE TABLE "Institution" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

CREATE TABLE "Stadium" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

CREATE TABLE "Status" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

CREATE TABLE "Unschaerfe" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "entityid" MEDIUMINT, "term" TEXT, "parentid" TEXT, "listitemid" TEXT);

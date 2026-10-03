-- Erzeugt aus Referenzlisten.gpkg
-- Nicht von Hand aendern: tools/export_from_gpkg.py

CREATE TABLE "BAUM_Sonderstrukturen" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Baeume_BAUM" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Baumhoehlen" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Besitz" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Chance7_Aufnahmetyp" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Chance7_Baumpilze" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" MEDIUMINT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Chance7_Beschattung" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" MEDIUMINT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Chance7_Biotopbaum" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Chance7_HoeheLage" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" MEDIUMINT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Chance7_Position" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" MEDIUMINT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Chance7_Zersetzung" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Hoehlen" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "Baumhoehlen_Typ" MEDIUMINT, "Anzahl" MEDIUMINT, "Baum_ObjektID" TEXT, "Eintragungsdatum" DATE);

CREATE TABLE "LandschlLage_Baum" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "LangBreitHoch" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Tabelle1" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "Formular Biotopbaumkartierung2016a" TEXT, "Tabelle.Name" TEXT, "Attribute.Name" TEXT, "Referenzliste.Name" TEXT, "DataType" TEXT, "Kardinalität" TEXT, "Referenzliste:" TEXT);

CREATE TABLE "Termin_BT" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Verkehrssicherung_BAUM" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "Zusatz_Vitalitaet_BAUM" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

CREATE TABLE "adressrollle" ( "fid" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "listitemid" MEDIUMINT, "kurzname" TEXT, "langname" TEXT, "parentlistitemid" MEDIUMINT, "entityid" MEDIUMINT);

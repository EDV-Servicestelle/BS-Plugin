/**
 * NRW Brutvogel QField Plugin v1.86
 * Exakt nach Heather Hillers Demo-Pattern:
 *   parent: iface.mainWindow().contentItem
 *   Loader { source: Qt.resolvedUrl("panel.qml") }
 *   signal closed() → pluginLoader.active = false
 */
import QtQuick
import QtQuick.Controls
import org.qfield
import org.qgis
import Theme
import "qrc:/qml" as QFieldItems

Item {
    id: plugin
    parent: iface.mainWindow().contentItem
    anchors.fill: parent

    property var allSpecies:      []
    property var filteredSpecies: []
    property string activeGroup:  ""

    property var gruppen: [
        { label: "Alle",      filter: "" },
        { label: "Enten",     filter: "Ente|Gans|Schwan|Tauch|Säge|Löffel|Krick|Schnatter|Brand" },
        { label: "Greife",    filter: "Bussard|Falke|Habicht|Sperber|Weihe|Milan|Adler|Fischadler" },
        { label: "Eulen",     filter: "Eule|Kauz|Uhu|Schleiereule" },
        { label: "Spechte",   filter: "Specht|Wendehals" },
        { label: "Singvögel", filter: "Meise|Drossel|Amsel|Rohrsänger|Grasmücke|Schwalbe|Rotkehlchen|Fink|Sperling|Ammer|Pieper|Würger|Star|Zaunkönig" },
        { label: "Watvögel",  filter: "Kiebitz|Bekassine|Schnepfe|Regenpfeifer|Strandläufer|Brachvogel" },
    ]

    // Loader – wie im Demo: source auf externe Datei
    Loader {
        id: pluginLoader
        active: false
        anchors.fill: parent
        source: Qt.resolvedUrl("panel.qml")
    }

    // Wenn panel.qml geladen: Properties übergeben + Signal verbinden
    Connections {
        target: pluginLoader.item
        function onClosed() { pluginLoader.active = false }
    }

    // Properties ins Panel schreiben sobald geladen
    Binding { target: pluginLoader.item; property: "allSpecies";      value: plugin.allSpecies;      when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "filteredSpecies"; value: plugin.filteredSpecies; when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "activeGroup";     value: plugin.activeGroup;     when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "gruppen";         value: plugin.gruppen;         when: pluginLoader.item }

    // Datenladen
    Connections {
        target: iface
        function onLoadProjectEnded() { plugin.allSpecies = []; plugin.filteredSpecies = []; loadSpecies() }
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(pluginButton)
        Qt.callLater(function() { loadSpecies() })
    }

    function loadSpecies() {
        var layers = qgisProject.mapLayersByName("Referenzliste_Arten")
        if (layers.length === 0) { iface.mainWindow().displayToast("⚠ 'Referenzliste_Arten' fehlt"); return }
        var arr = []
        try {
            var it = LayerUtils.createFeatureIteratorFromExpression(layers[0], "1=1")
            while (it.hasNext()) {
                var f = it.next()
                arr.push({ name: f.attribute("name") || "", wiss_name: f.attribute("wiss_name") || "", kuerzel: f.attribute("kuerzel") || "" })
            }
            it.close()
            arr.sort(function(a,b) { return a.name < b.name ? -1 : 1 })
            plugin.allSpecies = arr; plugin.filteredSpecies = arr
            iface.mainWindow().displayToast("✓ " + arr.length + " Vogelarten")
        } catch(e) { iface.mainWindow().displayToast("Ladefehler: " + e) }
    }

    // Locator
    QFieldLocatorFilter {
        id: locatorFilter; name: "brutvogel_va"; displayName: "Vogelart (NRW)"; prefix: "va"
        locatorBridge: iface.findItemByObjectName("locatorBridge")
        source: Qt.resolvedUrl("search.qml")
        function triggerResult(result) {
            if (pluginLoader.item) pluginLoader.item.setSpecies(result.displayString)
            else {
                var drawer = iface.findItemByObjectName("overlayFeatureFormDrawer")
                if (drawer && drawer.featureModel) {
                    var feat = drawer.featureModel.feature
                    var idx  = feat.fields.indexOf("Vogel_Art")
                    if (idx >= 0) { feat.setAttribute(idx, result.displayString); drawer.featureModel.feature = feat }
                }
                iface.mainWindow().displayToast("✓ " + result.displayString)
            }
        }
    }

    // Toolbar-Button
    QfToolButton {
        id: pluginButton
        bgcolor: Theme.darkGray
        iconSource: Theme.getThemeVectorIcon("ic_search_white_24dp")
        iconColor: Theme.mainColor
        round: true; tooltip: "Vogelart wählen"
        onClicked: {
            if (!pluginLoader.active) {
                plugin.activeGroup     = ""
                plugin.filteredSpecies = plugin.allSpecies
            }
            pluginLoader.active = !pluginLoader.active
        }
    }
}

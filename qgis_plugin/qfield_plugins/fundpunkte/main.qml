/**
 * NRW Fundpunkte Tiere QField Plugin v1.86
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

    property var allGruppen:      []
    property var allSpecies:      []
    property var filteredSpecies: []
    property string activeGruppeId:   ""
    property string activeGruppeName: "Alle Gruppen"
    property bool   gruppenVisible:   false

    Loader {
        id: pluginLoader
        active: false
        anchors.fill: parent
        source: Qt.resolvedUrl("panel.qml")
    }

    Connections {
        target: pluginLoader.item
        function onClosed() { pluginLoader.active = false; plugin.gruppenVisible = false }
    }

    Binding { target: pluginLoader.item; property: "allGruppen";      value: plugin.allGruppen;      when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "allSpecies";      value: plugin.allSpecies;      when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "filteredSpecies"; value: plugin.filteredSpecies; when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "activeGruppeId";  value: plugin.activeGruppeId;  when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "activeGruppeName";value: plugin.activeGruppeName;when: pluginLoader.item }
    Binding { target: pluginLoader.item; property: "gruppenVisible";  value: plugin.gruppenVisible;  when: pluginLoader.item }

    Connections {
        target: iface
        function onLoadProjectEnded() { plugin.allGruppen = []; plugin.allSpecies = []; plugin.filteredSpecies = []; loadData() }
    }

    Component.onCompleted: {
        iface.addItemToPluginsToolbar(pluginButton)
        Qt.callLater(function() { loadData() })
    }

    function loadData() {
        var gl = qgisProject.mapLayersByName("Artengruppen")
        if (gl.length > 0) {
            try {
                var grp = []; var it_g = LayerUtils.createFeatureIteratorFromExpression(gl[0], "\"parentid\" = 'nan'")
                while (it_g.hasNext()) { var fg = it_g.next(); grp.push({ term: fg.attribute("term") || "", listitemid: String(fg.attribute("listitemid") || "") }) }
                it_g.close(); grp.sort(function(a,b){ return a.term < b.term ? -1 : 1 }); plugin.allGruppen = grp
            } catch(e) { iface.mainWindow().displayToast("Gruppen-Fehler: " + e) }
        }
        var al = qgisProject.mapLayersByName("Arten")
        if (al.length === 0) { iface.mainWindow().displayToast("⚠ Layer 'Arten' fehlt"); return }
        try {
            var arr = []; var it_a = LayerUtils.createFeatureIteratorFromExpression(al[0], "\"parentid\" != 'nan'")
            while (it_a.hasNext()) { var fa = it_a.next(); arr.push({ entityid: String(fa.attribute("entityid") || ""), term: fa.attribute("term") || "", Name_deutsch: fa.attribute("Name_deutsch") || "", anzeigename: fa.attribute("anzeigename") || "", parentid: String(fa.attribute("parentid") || "") }) }
            it_a.close(); arr.sort(function(a,b){ var da=a.Name_deutsch||a.term, db=b.Name_deutsch||b.term; return da<db?-1:1 })
            plugin.allSpecies = arr; plugin.filteredSpecies = arr
            iface.mainWindow().displayToast("✓ " + arr.length + " Tierarten")
        } catch(e) { iface.mainWindow().displayToast("Arten-Fehler: " + e) }
    }

    QFieldLocatorFilter {
        id: locatorFilter; name: "fundpunkte_ft"; displayName: "Tierart (NRW)"; prefix: "ft"
        locatorBridge: iface.findItemByObjectName("locatorBridge")
        source: Qt.resolvedUrl("search.qml")
        function triggerResult(result) { if (result.userData && pluginLoader.item) pluginLoader.item.setSpecies(result.userData) }
    }

    QfToolButton {
        id: pluginButton
        bgcolor: Theme.darkGray
        iconSource: Theme.getThemeVectorIcon("ic_search_white_24dp")
        iconColor: Theme.mainColor; round: true; tooltip: "Tierart wählen"
        onClicked: {
            if (!pluginLoader.active) { plugin.activeGruppeId = ""; plugin.activeGruppeName = "Alle Gruppen"; plugin.filteredSpecies = plugin.allSpecies; plugin.gruppenVisible = false }
            pluginLoader.active = !pluginLoader.active
        }
    }
}

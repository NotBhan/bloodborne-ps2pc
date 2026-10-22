import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: window
    visible: true
    width: 1180; height: 760
    minimumWidth: 900; minimumHeight: 600
    title: "Bloodborne — Windows"
    color: Theme.base

    property string page: "Details"
    property int wizardStep: 0
    property var checks: launcher.readiness
    property bool gameBlocked: checks.length > 0 && checks[0].level === "error"
    property bool savesBlocked: (checks.length > 2 && checks[2].level === "error") || !launcher.savesWritable
    property bool onlineBlocked: launcher.playModeBlocked
    property bool blocked: gameBlocked || savesBlocked || onlineBlocked || launcher.setupRunning
    property bool setupPage: page === "Setup"

    function stateText() {
        if (window.gameBlocked) return "Game not found"
        switch (launcher.launchState) {
        case "preparing": return "Preparing"
        case "starting": return "Starting"
        case "running": return "Running"
        case "failed": return "Failed"
        default: return "Ready"
        }
    }
    function stateColor() {
        if (window.gameBlocked) return Theme.accent
        switch (launcher.launchState) {
        case "preparing": case "starting": return Theme.warn
        case "running": return Theme.good
        case "failed": return Theme.accent
        default: return Theme.good
        }
    }
    function openSettings(category, section) {
        page = "Settings"
        Qt.callLater(function () { settings.openAt(category || "", section || "") })
    }
    function openPage(name) {
        switch (name) {
        case "Home": case "Details": page = "Details"; break
        case "Trophies": page = "Trophies"; break
        case "Settings": page = "Settings"; if (settings) settings.showMenu(); break
        case "Setup": page = "Setup"; break
        case "Logs": openSettings("diagnostics", ""); break
        case "Game": openSettings("gameData", "Game files"); break
        case "Graphics": openSettings("graphics", ""); break
        case "Display": openSettings("display", ""); break
        case "Mods": openSettings("gameData", ""); break
        case "Online": openSettings("gameData", "The Hunter's Dream"); break
        case "System": openSettings("launcher", ""); break
        default: page = "Details"
        }
    }
    function openWizard(step) {
        wizardStep = step
        page = "Setup"
    }
    function primaryAction() {
        if (launcher.setupRunning) return
        if (gameBlocked) { openWizard(1); return }
        if (savesBlocked) { openWizard(2); return }
        if (onlineBlocked) {
            const target = launcher.playModeSettings
            openSettings("gameData", target[1])
            return
        }
        if (!launcher.running) launcher.playSelected()
    }
    function finishRoute() {
        const start = launcher.startPage
        if (start === "Setup") page = "Setup"
        else if (start === "Game") openSettings("gameData", "Game files")
        else if (start === "Log") openSettings("diagnostics", "")
        else page = "Details"
    }

    Component.onCompleted: {
        wizardStep = launcher.wizardStartStep
        Qt.callLater(finishRoute)
    }

    Shortcut { sequence: "Ctrl+1"; onActivated: window.openPage("Details") }
    Shortcut { sequence: "Ctrl+2"; onActivated: window.openPage("Trophies") }
    Shortcut { sequence: "Ctrl+3"; onActivated: window.openPage("Settings") }
    Shortcut { sequence: "Ctrl+L"; onActivated: window.openPage("Logs") }

    // PS5-style top bar: identity, three destinations, live status.
    Rectangle {
        id: topBar
        width: parent.width; height: 58
        color: Theme.base
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }

        Row {
            x: 24; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Image {
                width: 28; height: 28; anchors.verticalCenter: parent.verticalCenter
                source: Qt.resolvedUrl("../assets/hunter-icon.png")
                fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Bloodborne"; color: Theme.text; font.family: Theme.sans
                font.pixelSize: 15; font.weight: Font.DemiBold
            }
        }

        Row {
            visible: !window.setupPage
            anchors.centerIn: parent
            spacing: 26
            NavTab { text: "Game Details"; active: window.page === "Details"; onClicked: window.openPage("Details") }
            NavTab { text: "Trophies"; active: window.page === "Trophies"; onClicked: window.openPage("Trophies") }
            NavTab { text: "Settings"; active: window.page === "Settings"; onClicked: window.openPage("Settings") }
        }

        Rectangle {
            visible: !window.setupPage
            anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
            width: Math.max(76, statusRow.width + 16); height: 28
            color: "transparent"; radius: 3
            Row {
                id: statusRow; anchors.centerIn: parent; spacing: 7
                Rectangle { width: 7; height: 7; radius: 3.5; color: window.stateColor(); anchors.verticalCenter: parent.verticalCenter }
                Text {
                    text: window.stateText(); color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 12
                }
            }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: window.openPage("Details") }
        }
    }

    Item {
        id: pageHost
        y: 58
        width: parent.width; height: parent.height - 58

        DetailsPage {
            anchors.fill: parent
            visible: window.page === "Details"
            gameBlocked: window.gameBlocked
            savesBlocked: window.savesBlocked
            onlineBlocked: window.onlineBlocked
            onPrimaryRequested: window.primaryAction()
            onOpenTrophies: window.openPage("Trophies")
            onOpenSettings: (category, section) => window.openSettings(category, section)
        }

        TrophiesPage {
            anchors.fill: parent
            visible: window.page === "Trophies"
            onOpenSettings: (category, section) => window.openSettings(category, section)
        }

        Ps5Settings {
            id: settings
            anchors.fill: parent
            visible: window.page === "Settings"
            onOpenSetup: (step) => window.openWizard(step)
        }

        Item {
            anchors.fill: parent
            visible: window.setupPage
            Rectangle { anchors.fill: parent; color: Theme.base }
            SetupWizard {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 12
                width: Math.min(880, parent.width - 56)
                height: parent.height - 28
                startStep: window.wizardStep
                onExitRequested: (target) => window.openPage(target)
            }
        }
    }

    // Notices and launch errors surface as a quiet toast instead of a permanent footer.
    Rectangle {
        id: toast
        z: 20
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom; anchors.bottomMargin: 20
        width: Math.min(640, window.width - 80)
        height: toastText.implicitHeight + 20
        radius: 4
        color: Theme.panel
        border.color: Theme.lineStrong
        border.width: 1
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        Text {
            id: toastText
            anchors.left: parent.left; anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14; anchors.rightMargin: 14
            text: ""; color: Theme.text
            font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap
        }
        MouseArea { anchors.fill: parent; onClicked: toast.opacity = 0 }
        Timer { id: toastTimer; interval: 6000; onTriggered: toast.opacity = 0 }
    }

    Connections {
        target: launcher
        function onNoticeChanged() {
            const text = launcher.notice
            if (!text || text === "Ready to hunt.") return
            toastText.text = text
            toast.opacity = 1
            toastTimer.restart()
        }
    }

    component NavTab: Button {
        id: tab
        property bool active: false
        flat: true
        hoverEnabled: true
        padding: 0
        implicitWidth: Math.max(84, navLabel.implicitWidth + 18)
        implicitHeight: 58
        background: Rectangle {
            color: "transparent"
            Rectangle {
                anchors.bottom: parent.bottom; width: parent.width; height: 2
                color: tab.active ? Theme.text : "transparent"
            }
            Rectangle {
                anchors.fill: parent; color: "transparent"
                border.width: tab.activeFocus ? 1 : 0
                border.color: Theme.accent
            }
        }
        contentItem: Text {
            id: navLabel
            text: tab.text
            color: tab.active ? Theme.text : (tab.hovered ? Theme.textDim : Theme.textFaint)
            font.family: Theme.sans; font.pixelSize: 14; font.weight: tab.active ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        Accessible.role: Accessible.PageTab
        Accessible.name: text
        Accessible.checked: active
    }
}

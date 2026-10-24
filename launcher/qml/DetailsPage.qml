import QtQuick
import QtQuick.Controls

// PS5 game hub: full-bleed key art, launch action and real configuration details.
Item {
    id: details
    signal primaryRequested()
    signal openTrophies()
    signal openSettings(string category, string section)
    property bool gameBlocked: false
    property bool savesBlocked: false
    property bool onlineBlocked: false

    property var summary: launcher.trophySummary
    property var achievements: launcher.recentActivity
    property string playLabel: launcher.setupRunning ? "Installing…" :
                               launcher.running ? "Stop" :
                               launcher.launchState === "starting" ? "Starting…" :
                               launcher.launchState === "preparing" ? "Preparing…" : "Play"
    property string statusTitle: {
        if (launcher.setupRunning) return "Preparing game files"
        if (launcher.running) return "Game is running"
        if (launcher.launchState === "starting" || launcher.launchState === "preparing") return "Starting the hunt…"
        if (launcher.launchState === "failed") return "Launch failed"
        if (details.gameBlocked) return "Game not found"
        if (details.savesBlocked) return "Saves folder required"
        if (details.onlineBlocked) return "Setup required"
        return "Ready to launch"
    }
    property string statusDetail: {
        if (launcher.launchState === "failed") return launcher.notice
        if (launcher.running) return "The launcher is idle."
        if (details.gameBlocked) return "Choose the folder with eboot.bin"
        if (details.savesBlocked) return "Choose a writable saves folder"
        if (details.onlineBlocked) return "Sign in or choose another launch mode"
        return "eboot.bin found"
    }
    property color statusAccent: launcher.launchState === "failed" || details.gameBlocked ? Theme.accent
                                 : launcher.running ? Theme.good
                                 : details.blockedHint ? Theme.warn : Theme.good

    property bool blockedHint: details.savesBlocked || details.onlineBlocked
    property bool busy: launcher.setupRunning || launcher.launchState === "starting"
                        || launcher.launchState === "preparing"
    property string graphicsText: launcher.setupFacts.resolution + "  ·  " +
                                  launcher.setupFacts.upscaler + "  ·  " +
                                  (launcher.graphicsPreset === "custom" ? "Custom"
                                   : launcher.presetLabel(launcher.graphicsPreset))
    property string trophiesText: summary.available
                                  ? summary.earned + " of " + summary.total + "  ·  " + summary.completion + "%"
                                  : summary.localUnlocks + " local unlocks recorded."

    function readinessDetail(label) {
        const rows = launcher.readiness
        for (let i = 0; i < rows.length; i++)
            if (rows[i].label === label) return rows[i].detail || ""
        return ""
    }

    Rectangle { anchors.fill: parent; color: Theme.base }
    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl("../art/hero.png")
        fillMode: Image.PreserveAspectCrop
        smooth: true; mipmap: true
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#990b0c10" }
            GradientStop { position: 0.58; color: "#660b0c10" }
            GradientStop { position: 1.0; color: "#f20b0c10" }
        }
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#e60b0c10" }
            GradientStop { position: 0.62; color: "#430b0c10" }
            GradientStop { position: 1.0; color: "#990b0c10" }
        }
    }

    Flickable {
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: content.implicitHeight + 56
        ScrollBar.vertical: AppScrollBar {}

        Column {
            id: content
            x: 48; y: 26
            width: Math.min(1120, details.width - 96)
            spacing: 0

            Text {
                text: "GAME DETAILS"; color: Theme.textDim; font.family: Theme.sans
                font.pixelSize: 11; font.letterSpacing: 2.2
            }
            Item { width: 1; height: 12 }

            Row {
                width: parent.width
                spacing: 34
                Image {
                    width: 214; height: 214
                    source: Qt.resolvedUrl("../assets/hunter-icon.png")
                    fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
                    Rectangle { anchors.fill: parent; color: "transparent"; border.width: 1; border.color: "#35ffffff" }
                }
                Column {
                    width: parent.width - 248
                    spacing: 0
                    Text {
                        text: "Bloodborne"; color: Theme.text; font.family: Theme.sans
                        font.pixelSize: 34; font.weight: Font.DemiBold
                    }
                    Text {
                        text: "WINDOWS PORT  ·  v" + launcher.version; color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 11; font.letterSpacing: 1.2
                    }
                    Item { width: 1; height: 16 }

                    Row {
                        spacing: 14
                        Button {
                            id: playButton
                            width: 168; height: 44
                            enabled: launcher.running || (!launcher.setupRunning
                                      && launcher.launchState !== "preparing"
                                      && launcher.launchState !== "starting")
                            text: details.playLabel
                            scale: playButton.down ? 0.985 : 1
                            Behavior on scale { NumberAnimation { duration: Theme.motionFast; easing.type: Easing.OutCubic } }
                            background: Rectangle {
                                radius: 22
                                color: !playButton.enabled ? Theme.surface
                                       : launcher.running ? Theme.accent
                                       : playButton.hovered ? "#fbf9f6" : "#f2f0ec"
                                border.width: playButton.activeFocus ? 2 : (launcher.running ? 0 : 1)
                                border.color: playButton.activeFocus
                                              ? (launcher.running ? Theme.text : Theme.accent)
                                              : "#33ffffff"
                                Behavior on color { ColorAnimation { duration: Theme.motionFast } }
                            }
                            contentItem: Text {
                                text: playButton.text
                                color: !playButton.enabled ? Theme.textFaint
                                       : launcher.running ? "#fff8f3" : "#0a0b0f"
                                font.family: Theme.sans; font.pixelSize: 15; font.weight: Font.DemiBold
                                horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: details.primaryRequested()
                            Accessible.role: Accessible.Button
                            Accessible.name: playButton.text
                        }
                        Text {
                            id: chooseFolder
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Choose game folder"
                            color: chooseFolderHover.hovered ? Theme.text : Theme.textDim
                            font.family: Theme.sans; font.pixelSize: 12
                            Behavior on color { ColorAnimation { duration: Theme.motionFast } }
                            HoverHandler { id: chooseFolderHover }
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: details.openSettings("gameData", "Game files")
                            }
                        }
                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 8
                            StatusDot {
                                width: 8; height: 8
                                anchors.verticalCenter: parent.verticalCenter
                                color: details.statusAccent
                                busy: details.busy
                            }
                            Column {
                                spacing: 1
                                Text { text: details.statusTitle; color: Theme.text; font.family: Theme.sans; font.pixelSize: 12 }
                                Text {
                                    text: details.statusDetail; color: Theme.textDim
                                    font.family: Theme.sans; font.pixelSize: 10
                                    width: Math.min(220, Math.max(120, details.width - 760))
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }

                    Item { width: 1; height: 14 }
                    Row {
                        spacing: 8
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "LAUNCH MODE"; color: Theme.textFaint
                            font.family: Theme.sans; font.pixelSize: 9; font.letterSpacing: 1.2
                        }
                        Repeater {
                            model: [{mode: "offline", label: "Offline"},
                                    {mode: "huntersdream", label: "Online"},
                                    {mode: "coop", label: "Co-op"}]
                            delegate: GlassButton {
                                text: modelData.label; width: 82; height: 26
                                highlighted: launcher.playMode === modelData.mode
                                enabled: !launcher.running && !launcher.setupRunning
                                onClicked: launcher.setPlayMode(modelData.mode)
                            }
                        }
                    }
                    Item { width: 1; height: 12 }
                    Text {
                        width: parent.width; text: launcher.playModeSummary; color: Theme.textFaint
                        font.family: Theme.sans; font.pixelSize: 10; wrapMode: Text.WordWrap
                        maximumLineCount: 2; elide: Text.ElideRight
                    }

                    Item { width: 1; height: 14 }
                    Rectangle { width: parent.width; height: 1; color: "#24ffffff" }
                    InfoRow { label: "Game files"; value: details.readinessDetail("Game files") }
                    InfoRow { label: "Play time"; value: launcher.playtime }
                    InfoRow { label: "Graphics profile"; value: details.graphicsText }
                    InfoRow { label: "Trophies"; value: details.trophiesText }
                    InfoRow { label: "Save data"; value: details.readinessDetail("Saves") || launcher.saveStatus }
                    InfoRow { label: "FSR 4 assets"; value: launcher.fsrStatus }
                }
            }

            Item { width: 1; height: 16 }
            Rectangle {
                width: parent.width; height: 1; color: "#24ffffff"
            }
            Item { width: 1; height: 12 }
            Item {
                width: parent.width; height: 28
                Text {
                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                    text: "TROPHIES"; color: Theme.textDim; font.family: Theme.sans
                    font.pixelSize: 10; font.letterSpacing: 1.3
                }
                GlassButton {
                    id: viewAllTrophies
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    text: "View all trophies"; width: 156; height: 26
                    onClicked: details.openTrophies()
                }
                Text {
                    anchors.right: viewAllTrophies.left; anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    text: details.trophiesText; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 11
                }
            }
            Item { width: 1; height: 6 }
            Rectangle {
                width: parent.width; height: 3; radius: 1.5; color: "#30ffffff"
                Rectangle {
                    width: parent.width * (details.summary.available ? details.summary.completion / 100 : 0)
                    height: parent.height; radius: 1.5; color: Theme.text
                    Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
                }
            }

            Item { width: 1; height: 18 }
            Rectangle { width: parent.width; height: 1; color: "#24ffffff" }
            Item { width: 1; height: 12 }
            Text { text: "RECENT ACTIVITY"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 10; font.letterSpacing: 1.3 }
            Text {
                text: "Game sessions and trophy unlocks"; color: Theme.textFaint
                font.family: Theme.sans; font.pixelSize: 10
            }
            Item { width: 1; height: 6 }
            Text {
                visible: details.achievements.length === 0
                text: "No game activity yet."; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 11
            }
            Column {
                width: parent.width
                Repeater {
                    model: details.achievements
                    delegate: Item {
                        width: parent.width; height: 24
                        Row {
                            anchors.fill: parent; spacing: 12
                            Text {
                                width: 44; text: modelData.time; color: Theme.textFaint
                                font.family: Theme.mono; font.pixelSize: 10
                            }
                            Text {
                                width: parent.width - 56; text: modelData.text; color: Theme.textDim
                                font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight
                            }
                        }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#18ffffff" }
                    }
                }
            }
        }
    }

    component InfoRow: Item {
        property string label: ""
        property string value: ""
        width: parent ? parent.width : 0
        height: 38
        Text {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            text: parent.label; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 13
        }
        Text {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: Math.min(parent.width * 0.62, implicitWidth)
            text: parent.value; color: Theme.text; font.family: Theme.sans; font.pixelSize: 13
            horizontalAlignment: Text.AlignRight; elide: Text.ElideRight
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#20ffffff" }
    }
}

import QtQuick
import QtQuick.Controls

// Keyboard and mouse bindings (bbport.ini key_*): grouped rows with a capture dialog for
// keys, mouse buttons and the wheel. The runtime applies them at the next start.
Column {
    id: root
    width: parent ? parent.width : 400
    spacing: 0

    property string action: ""
    property string actionLabel: ""
    property string boundKey: ""
    property string boundMouse: ""
    property string feedback: ""

    function begin(action, label, key, mouse) {
        root.action = action
        root.actionLabel = label
        root.boundKey = key
        root.boundMouse = mouse
        root.feedback = ""
        rebind.open()
    }

    function mouseToken(button) {
        switch (button) {
        case Qt.LeftButton: return "Mouse1"
        case Qt.RightButton: return "Mouse2"
        case Qt.MiddleButton: return "Mouse3"
        case Qt.BackButton: return "Mouse4"
        case Qt.ForwardButton: return "Mouse5"
        }
        return ""
    }

    Repeater {
        model: launcher.keyBindings
        delegate: Column {
            width: root.width
            spacing: 0
            Item { width: 1; height: 10 }
            Text {
                text: modelData.section
                color: Theme.text
                font.family: Theme.sans; font.pixelSize: 14; font.weight: Font.DemiBold
            }
            Repeater {
                model: modelData.bindings
                delegate: Item {
                    width: root.width
                    height: 46
                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 220
                        text: modelData.label
                        color: Theme.text; elide: Text.ElideRight
                        font.family: Theme.sans; font.pixelSize: 13
                    }
                    Row {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 12
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 120
                            text: modelData.display
                            color: modelData.display === "Unbound" ? Theme.textFaint : Theme.textDim
                            font.family: Theme.mono; font.pixelSize: 12
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                        }
                        GlassButton {
                            text: "Change"; width: 76; height: 28
                            onClicked: root.begin(modelData.action, modelData.label,
                                                  modelData.key, modelData.mouse)
                        }
                    }
                    Rectangle {
                        anchors.bottom: parent.bottom
                        width: parent.width; height: 1; color: Theme.line
                    }
                }
            }
        }
    }

    Item { width: 1; height: 12 }
    Row {
        width: parent.width; spacing: 10
        GlassButton {
            text: "Reset key bindings"; height: 30
            onClicked: launcher.resetKeyBindings()
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 170
            text: "Restores the defaults. Gamepad bindings are not changed."
            color: Theme.textDim; wrapMode: Text.WordWrap
            font.family: Theme.sans; font.pixelSize: 11
        }
    }
    Item { width: 1; height: 6 }
    Note {
        width: parent.width
        text: "Click Change, then press a key, mouse button or the wheel. One key and one mouse input per action; picking one that is in use takes it from the other action."
    }

    Popup {
        id: rebind
        parent: Overlay.overlay
        modal: true
        focus: true
        width: Math.min(480, Overlay.overlay ? Overlay.overlay.width - 48 : 480)
        height: 292
        x: Overlay.overlay ? Math.round((Overlay.overlay.width - width) / 2) : 0
        y: Overlay.overlay ? Math.round((Overlay.overlay.height - height) / 2) : 0
        closePolicy: Popup.NoAutoClose
        padding: 0
        background: Rectangle {
            color: Theme.panel
            border.color: Theme.lineStrong
            border.width: 1
            radius: Theme.radius
        }
        onOpened: capture.forceActiveFocus()
        contentItem: Column {
            width: rebind.width
            spacing: 0

            Item { width: 1; height: 18 }
            Text {
                x: 20
                width: parent.width - 40
                text: "Rebind " + root.actionLabel
                color: Theme.text
                font.family: Theme.sans; font.pixelSize: 17; font.weight: Font.DemiBold
            }
            Item { width: 1; height: 4 }
            Text {
                x: 20
                width: parent.width - 40
                text: "Press a key, mouse button or the wheel."
                color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 11
            }
            Item { width: 1; height: 10 }

            Item {
                id: capture
                x: 20
                width: parent.width - 40
                height: 92
                focus: true
                Keys.onPressed: (event) => {
                    const name = launcher.sdlKeyName(event.key, event.text,
                                                     (event.modifiers & Qt.KeypadModifier) !== 0)
                    if (name === "") {
                        root.feedback = "That key cannot be bound."
                    } else {
                        launcher.setKeyBinding(root.action, name, root.boundMouse)
                        rebind.close()
                    }
                    event.accepted = true
                }
                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radiusSmall
                    color: Theme.surface
                    border.width: 1
                    border.color: capture.activeFocus ? Theme.accent : Theme.line
                }
                Text {
                    anchors.centerIn: parent
                    width: parent.width - 20
                    text: {
                        const parts = [root.boundKey, root.boundMouse].filter(function (part) {
                            return part !== "" })
                        return parts.length ? parts.join(" + ") : "Unbound"
                    }
                    color: Theme.text
                    font.family: Theme.mono; font.pixelSize: 15
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                                    | Qt.BackButton | Qt.ForwardButton
                    onPressed: (mouse) => {
                        const name = root.mouseToken(mouse.button)
                        if (name !== "") {
                            launcher.setKeyBinding(root.action, root.boundKey, name)
                            rebind.close()
                        }
                    }
                    onWheel: (wheel) => {
                        const name = wheel.angleDelta.y > 0 ? "WheelUp"
                                   : wheel.angleDelta.y < 0 ? "WheelDown" : ""
                        if (name !== "") {
                            launcher.setKeyBinding(root.action, root.boundKey, name)
                            rebind.close()
                        }
                    }
                }
            }

            Item { width: 1; height: 8 }
            Text {
                x: 20
                width: parent.width - 40
                text: root.feedback
                color: Theme.warn
                font.family: Theme.sans; font.pixelSize: 11
            }
            Item { width: 1; height: 10 }

            Row {
                x: 20
                width: parent.width - 40
                spacing: 8
                GlassButton {
                    text: "Reset to default"; height: 30
                    onClicked: {
                        launcher.resetKeyBinding(root.action)
                        rebind.close()
                    }
                }
                GlassButton {
                    text: "Clear"; height: 30
                    onClicked: {
                        launcher.setKeyBinding(root.action, "", "")
                        rebind.close()
                    }
                }
                GlassButton {
                    text: "Cancel"; height: 30
                    onClicked: rebind.close()
                }
            }
        }
    }
}

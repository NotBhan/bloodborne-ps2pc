import QtQuick
import QtQuick.Controls

// One-click starting points for image quality and frame rate. The individual settings below
// remain editable; changing one turns the preset into Custom.
Column {
    id: root
    width: parent ? parent.width : 400
    spacing: 10

    Flow {
        width: parent.width
        spacing: 8
        Repeater {
            model: launcher.graphicsPresets
            delegate: GlassButton {
                width: 108; height: 32
                text: modelData.label
                      + (launcher.recommendedPreset === modelData.key ? "  *" : "")
                highlighted: launcher.graphicsPreset === modelData.key
                onClicked: launcher.applyGraphicsPreset(modelData.key)
            }
        }
    }
    Text {
        width: parent.width
        wrapMode: Text.WordWrap
        color: Theme.textDim
        font.family: Theme.sans; font.pixelSize: 11; lineHeight: 1.35
        text: launcher.presetDescription(launcher.graphicsPreset)
              + (launcher.recommendedPreset !== "" ? "  * Suggested for the detected card." : "")
    }
    Note {
        width: parent.width
        text: "Presets set upscaling, model detail, ambient occlusion, dynamic-light shadows, reflections and the frame-rate mode. Your output resolution and look settings stay as chosen."
    }
}

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bloodborne launcher for the native Linux port (GTK4 / libadwaita).

Game-first shell with three destinations:
- Game Details: artwork, real readiness, launch controls and activity journal
- Trophies: local trophy cache and unlock history
- Settings: display, graphics, upscaling, performance, compatibility, controller,
  game data, launcher preferences and diagnostics
- Dedicated 6-language switcher (EN, FR, RU, ZH, KO, JA)
- Robust settings persistence and supervisor integration
"""

import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parent
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))

from bbport_assets import (
    FSR4_BASE,
    KEYBOARD_PROMPTS,
    KEYBOARD_PROMPT_LAYOUT,
    apply_control_scheme,
    bundled_keyboard_prompts,
    canonical_control_scheme,
    detect_control_scheme,
    fsr411_problem,
    fsr4_files,
    fsr4_gpu_supported,
    fsr4_missing,
    install_keyboard_prompts,
    is_keyboard_prompt,
    is_prompt_mod,
    is_xbox_prompt,
    validate_fsr4_file,
)
from bbport_activity import add_playtime, load_events, load_playtime, record_event
from bbport_i18n import language, set_language, tr
from bbport_readiness import check_readiness, import_trophy_key, valid_trophy_key
from bbport_trophies import GRADE_ORDER, GRADES, load_trophy_report

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

GRADE_NAMES = {"P": "Platinum", "G": "Gold", "S": "Silver", "B": "Bronze", "?": "Unknown"}
GAME_ACTIVITY_KINDS = {"session", "trophy"}


def format_playtime(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return tr("{} h {} m").format(hours, minutes)
    if minutes:
        return tr("{} m").format(minutes)
    return tr("Less than a minute")

PORT_DIR = LAUNCHER_DIR.parent  # native_probe (or the package's copy)
sys.path.insert(0, str(PORT_DIR / 'scripts'))
from mods import discover as discover_mods  # noqa: E402
from patches import external_patches  # noqa: E402
# Packaged (AppImage): generated files, saves and bbport.ini live in BB_DATA_DIR.
PACKAGED = bool(os.environ.get("BB_PREBUILT"))
DATA_DIR = Path(os.environ.get("BB_DATA_DIR", PORT_DIR))
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "bbport-launcher"
CONFIG_FILE = CONFIG_DIR / "settings.json"
MAX_LOG_LINES = 5000
VERSION = "1.10.7"
REPO_URL = "https://github.com/NotBhan/bloodborne_pc_notbhan"
ISSUES_URL = f"{REPO_URL}/issues"
THEME_FILE = LAUNCHER_DIR / "theme.css"


def activity_path():
    return CONFIG_FILE.parent / "activity.json"


def log_path():
    return CONFIG_FILE.parent / "launcher.log"

# Choices: (native display label, value). Default is English ("en").
UI_LANGUAGES = [
    ("English", "en"),
    ("Français", "fr"),
    ("Русский", "ru"),
    ("简体中文", "zh"),
    ("한국어", "ko"),
    ("日本語", "ja"),
]

CONTROL_SCHEMES = [
    ("ПК — клавиатура и мышь", "pc"),
    ("Геймпад Xbox", "xbox"),
    ("Геймпад PlayStation", "playstation"),
]

UPSCALERS = [
    ("FSR 4 (Experimental)", "fsr4"),
    ("FSR 4.1.1 (Experimental)", "fsr411"),
    ("FSR 3.1 (Recommended)", "fsr3"),
    ("DLSS (RTX)", "dlss"),
    ("TAA (native anti-aliasing)", "taa"),
    ("Off", "off"),
]

PRESETS = [("Native AA", 0), ("Quality (x1.5)", 1), ("Balanced (x1.7)", 2),
           ("Performance (x2)", 3), ("Ultra Performance (x3)", 4)]
PRESET_SCALES = [1.0, 1.5, 1.7, 2.0, 3.0]

# The runtime's bindings (src/input_bindings.c): key_<action>=<SDL key>, <mouse input>.
# One key and one mouse input per action; "none" leaves an action unbound.
KEY_BINDING_SECTIONS = [
    ("Movement", (
        ("move_forward", "Move Forward", "W", ""),
        ("move_back", "Move Back", "S", ""),
        ("move_left", "Move Left", "A", ""),
        ("move_right", "Move Right", "D", ""),
        ("walk", "Walk", "Left Alt", ""),
        ("look_up", "Look Up", "I", ""),
        ("look_down", "Look Down", "K", ""),
        ("look_left", "Look Left", "J", ""),
        ("look_right", "Look Right", "L", ""),
        ("roll", "Dodge / Sprint", "Space", ""),
        ("lock_on", "Lock On", "Q", ""),
    )),
    ("Combat and items", (
        ("attack", "Attack", "", "Mouse1"),
        ("strong_attack", "Strong Attack", "V", ""),
        ("strong_modifier", "Strong Attack Modifier", "Left Shift", ""),
        ("transform", "Transform", "C", "Mouse3"),
        ("firearm", "Firearm / Parry", "X", "Mouse2"),
        ("blood_vial", "Blood Vial", "R", ""),
        ("use_item", "Use Item", "F", ""),
        ("interact", "Interact", "E", ""),
    )),
    ("Menus and switching", (
        ("switch_item", "Switch Item", "Down", ""),
        ("switch_right", "Switch Right Weapon", "Right", ""),
        ("switch_left", "Switch Left Weapon", "Left", ""),
        ("dpad_up", "D-pad Up", "Up", ""),
        ("gestures", "Gestures", "G", ""),
        ("personal_effects", "Personal Effects", "T", ""),
        ("menu", "Menu", "Escape", ""),
        ("confirm", "Menu Confirm", "Return", ""),
        ("back", "Menu Back", "Backspace", ""),
        ("l3", "Left Stick Press", "Left Ctrl", ""),
    )),
]
KEY_BINDING_SPECS = tuple(spec for _section, specs in KEY_BINDING_SECTIONS for spec in specs)
KEY_BINDING_BY_ACTION = {spec[0]: spec for spec in KEY_BINDING_SPECS}
MOUSE_TOKEN_NAMES = {
    "mouse1": "Mouse1", "mouse2": "Mouse2", "mouse3": "Mouse3", "mouse4": "Mouse4",
    "mouse5": "Mouse5", "wheelup": "WheelUp", "wheeldown": "WheelDown",
}
SDL_KEY_NAMES = {
    "Escape": "Escape", "Return": "Return", "KP_Enter": "Keypad Enter",
    "BackSpace": "Backspace", "Tab": "Tab", "ISO_Left_Tab": "Tab", "space": "Space",
    "Caps_Lock": "CapsLock", "Print": "PrintScreen", "Scroll_Lock": "ScrollLock",
    "Pause": "Pause", "Insert": "Insert", "Delete": "Delete", "Home": "Home",
    "End": "End", "Page_Up": "PageUp", "Page_Down": "PageDown", "Up": "Up",
    "Down": "Down", "Left": "Left", "Right": "Right", "Num_Lock": "Numlock",
    "Menu": "Menu", "KP_Add": "Keypad +", "KP_Subtract": "Keypad -",
    "KP_Multiply": "Keypad *", "KP_Divide": "Keypad /", "KP_Decimal": "Keypad .",
    "KP_Equal": "Keypad =", "KP_Space": "Keypad Space",
    "Shift_L": "Left Shift", "Shift_R": "Right Shift",
    "Control_L": "Left Ctrl", "Control_R": "Right Ctrl",
    "Alt_L": "Left Alt", "Alt_R": "Right Alt",
    "Super_L": "Left GUI", "Super_R": "Right GUI",
    "Meta_L": "Left GUI", "Meta_R": "Right GUI",
    "Hyper_L": "Left GUI", "Hyper_R": "Right GUI",
    "ISO_Level3_Shift": "Right Alt",
}
SHIFTED_KEYS = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
    "*": "8", "(": "9", ")": "0", ":": ";", "\"": "'", "<": ",", ">": ".",
    "?": "/", "{": "[", "}": "]", "|": "\\", "+": "=", "_": "-", "~": "`",
}
SDL_PUNCTUATION = set("-=[]\\#;'`,./")


def parse_key_binding(raw, default_key="", default_mouse=""):
    """Read key_<action> the way the runtime does; None means the defaults apply."""
    if raw is None:
        return default_key, default_mouse
    key, mouse = "", ""
    for part in str(raw).split(","):
        token = part.strip()
        if not token or token.lower() == "none":
            continue
        mouse_name = MOUSE_TOKEN_NAMES.get(token.lower())
        if mouse_name:
            mouse = mouse_name
        else:
            key = token
    return key, mouse


def format_key_binding(key, mouse):
    parts = [part for part in (key, mouse) if part]
    return ", ".join(parts) if parts else "none"


def sdl_key_name(keyval):
    """GDK keyval to the SDL scancode name bbport.ini expects."""
    name = Gdk.keyval_name(keyval)
    if name in SDL_KEY_NAMES:
        return SDL_KEY_NAMES[name]
    if name and len(name) > 1 and name[0] == "F" and name[1:].isdigit():
        return name
    if name and name.startswith("KP_") and name[3:].isdigit():
        return f"Keypad {name[3:]}"
    char = Gdk.keyval_to_unicode(keyval)
    if char:
        value = chr(char)
        if value.isascii() and value.isalpha():
            return value.upper()
        if value.isdigit():
            return value
        if value in SHIFTED_KEYS:
            return SHIFTED_KEYS[value]
        if value in SDL_PUNCTUATION:
            return value
    return None


def compute_internal_resolution(output_res_str, preset_idx, custom_render_res=None):
    """(render_w, render_h, scale): calculates internal rendering resolution."""
    if custom_render_res:
        try:
            w, h = (int(v) for v in str(custom_render_res).lower().split("x"))
            return w, h, None
        except (ValueError, TypeError):
            pass
    try:
        out_w, out_h = (int(v) for v in str(output_res_str).lower().split("x"))
    except (ValueError, TypeError):
        out_w, out_h = 1920, 1080
    try:
        idx = max(0, min(int(preset_idx), len(PRESET_SCALES) - 1))
    except (ValueError, TypeError):
        idx = 2
    scale = PRESET_SCALES[idx]
    render_w = max(2, round(out_w / scale / 2) * 2)
    render_h = max(2, round(out_h / scale / 2) * 2)
    return render_w, render_h, scale


OUTPUT_RES = [
    ("1280×720 (Steam Deck)", "1280x720"),
    ("1920×1080", "1920x1080"),
    ("2560×1440", "2560x1440"),
    ("3840×2160", "3840x2160"),
    ("1280×800 (16:10)", "1280x800"),
    ("2560×1080 (Ultrawide 21:9)", "2560x1080"),
    ("3440×1440 (Ultrawide 21:9)", "3440x1440"),
    ("3840×1600 (Ultrawide)", "3840x1600"),
    ("5120×1440 (32:9 Super Ultrawide)", "5120x1440"),
]

# Ultrawide outputs: where the HUD's corner groups go (run.py hud_position, 0 = centred 16:9).
HUD_POSITIONS = [("У краёв экрана (100%)", "100"), ("75%", "75"), ("Посередине (50%)", "50"),
                 ("25%", "25"), ("По центру (16:9)", "0")]

# Game effects (patches applied at start): bbport.ini key, title, default.
EFFECTS = [
    ("effect_chromatic_aberration", "Хроматическая аберрация", True),
    ("effect_dof", "Глубина резкости (DoF)", True),
    ("effect_motion_blur", "Размытие в движении", True),
    ("effect_ssao", "Затенение SSAO", True),
    ("effect_game_aa", "Собственное сглаживание игры", True),
    ("effect_dynamic_shadows", "Тени от динамических источников", True),
    ("effect_ssr", "Отражения SSR (не было в игре)", False),
    ("skip_intro", "Пропуск заставок при запуске", False),
    ("debug_camera", "Свободная камера (Cross + L3 / Space + Z)", False),
    ("debug_menu", "Debug menu (левый touchpad / Tab; нужны шрифты)", False),
]

# PC enhancements (scripts/enhancements.py): game files made at start; off is original game.
ENHANCEMENTS = [
    ("pc_mirror_appearance", "Зеркало в Сне охотника: смена внешности", False),
    ("pc_two_invaders", "Два захватчика в поздних локациях", False),
    ("pc_rebirth", "Перерождение у Алтаря отчаяния", False),
    ("pc_enhanced_lamps", "Фонари: повышение уровня и хранилище", False),
    ("pc_boss_rematches", "Повторные бои с боссами у фонарей", False),
]

# Cheats and gameplay tweaks: game patches for 1.09, off by default.
CHEATS_AND_TWEAKS = [
    ("cheat_no_death", "Бессмертие (здоровье не ниже 1 HP)", False),
    ("cheat_stealth", "Враги не видят вас", False),
    ("cheat_silent", "Враги не слышат вас", False),
    ("cheat_rally_no_decay", "Rally не угасает", False),
    ("cheat_enemy_control", "Управление выбранным врагом (R3)", False),
    ("tweak_no_rally", "Без Rally", False),
    ("tweak_camera_distance", "Камера дальше от персонажа", False),
    ("tweak_no_camera_rotation", "Без автоповорота камеры при движении", False),
    ("tweak_easy_run", "Бег при меньшем наклоне стика", False),
    ("tweak_ragdoll", "Физика тел Dark Souls", False),
]

MODEL_LOD = [("Как в игре", "0"), ("Максимальная (-2)", "-2"), ("Ниже (1)", "1"),
             ("Минимальная (2)", "2")]
FPS_MODES = [("Без ограничения (патч)", "uncap"), ("60", "60"), ("90", "90"),
             ("30 (как на PS4)", "30")]
PRESENT_MODES = [("Mailbox", "Mailbox"), ("FIFO (VSync)", "Fifo"),
                 ("FIFO Relaxed", "FifoRelaxed"), ("Immediate", "Immediate")]
DRAW_PIPE = [("Авто (8+ потоков)", ""), ("Включён", "1"), ("Выключен (стабильнее)", "0")]
LANGUAGES = [("Английский", "1"), ("Русский", "8"), ("Японский", "0"), ("Французский", "2"),
             ("Испанский", "3"), ("Немецкий", "4"), ("Итальянский", "5")]
LIVE_RESOLUTION = [("Авто (по видеокарте)", "auto"), ("Выключена (быстрее)", "0"), ("Включена", "1")]
READBACKS = [("Relaxed (по умолчанию)", ""), ("Выключены", "0"), ("Precise", "2")]

DEFAULTS = {
    "ui_language": "en",
    "control_scheme": "xbox",
    "game_dir": "" if PACKAGED else str(PORT_DIR.parent / "CUSA03173"),
    "user_dir": "",
    "mods_dir": "",
    "mods_enabled": True,
    "patches_dir": "",
    "language": "1",
    "player_name": "",
    "dlc_dir": "",
    "fullscreen": False,
    "hdr": False,
    "present_mode": "Mailbox",
    "fps_mode": "uncap",
    "fps_limit": 0,
    "frames_ahead": 1,
    "draw_pipe": "",
    "readbacks": "",
    "mangohud": False,
    "precompile_shaders": True,
    "discord_rpc": True,
    "frame_stats": False,
    "gpu_profile": False,
    "vk_validation": False,
    "extra_env": "",
    "reduce_motion": False,
}

# bbport.ini keys the launcher edits; the rest of the file is kept.
INI_DEFAULTS = {
    "upscaler": "dlss",
    "preset": "2",
    "sharpen": "1",
    "sharpness": "0.50",
    "object_motion": "1",
    "show_fps": "1",
    "output_res": "1920x1080",
    "hud_position": "100",
    "model_lod": "0",
    "live_resolution": "0",
    **{key: "1" if default else "0"
       for key, _, default in EFFECTS + ENHANCEMENTS + CHEATS_AND_TWEAKS},
}

BOOL_SETTINGS = {"mods_enabled", "fullscreen", "hdr", "mangohud", "precompile_shaders",
                 "discord_rpc", "frame_stats", "gpu_profile", "vk_validation", "reduce_motion"}
STRING_SETTINGS = {"ui_language", "control_scheme", "game_dir", "user_dir", "mods_dir", "patches_dir",
                    "language", "player_name", "dlc_dir", "present_mode", "fps_mode",
                    "draw_pipe", "readbacks", "extra_env"}


def setting_value(key, value):
    """The value as the launcher uses it, or None when invalid for `key`."""
    if key in BOOL_SETTINGS:
        return value if isinstance(value, bool) else None
    if key == "ui_language":
        if isinstance(value, str) and value in ("en", "fr", "ru", "zh", "ko", "ja"):
            return value
        return "en"
    if key in STRING_SETTINGS:
        return value if isinstance(value, str) else None
    if key == "fps_limit":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        return max(0, min(480, int(value)))
    if key == "frames_ahead":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value):
            return None
        return max(0, min(8, int(value)))
    return value


def load_settings():
    settings = dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError, TypeError):
        return settings
    if not isinstance(data, dict):
        return settings
    for key, value in data.items():
        if key not in DEFAULTS:
            settings[key] = value
            continue
        val = setting_value(key, value)
        if val is not None:
            settings[key] = val
    return settings


def atomic_write_text(path, text):
    """Writes `text` through a temporary file in the target directory, then replaces `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding='utf-8') as temp:
            temp.write(text)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_name, path)
        # The file's fsync does not cover the rename: sync the directory entry too.
        try:
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def save_settings(settings):
    atomic_write_text(CONFIG_FILE, json.dumps(settings, indent=2, ensure_ascii=False))


def ini_path():
    return Path(os.environ.get("BB_CONFIG") or DATA_DIR / "bbport.ini")


def ini_int(values, key, fallback):
    try:
        return int(str(values.get(key, fallback)).strip())
    except (TypeError, ValueError):
        return fallback


def ini_float(values, key, fallback):
    try:
        value = float(str(values.get(key, fallback)).strip())
    except (TypeError, ValueError):
        return fallback
    return value if math.isfinite(value) else fallback


def load_ini():
    values = dict(INI_DEFAULTS)
    lines = []
    try:
        lines = ini_path().read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        pass
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values, lines


def save_ini(values, lines):
    """Rewrites the edited keys in place, appends missing ones, keeps comments and others."""
    written = set()
    out = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in values:
                out.append(f"{key}={values[key]}")
                written.add(key)
                continue
        out.append(line)
    if not lines:
        out.append("# bbport settings (in-game menu: Insert / L3+R3)")
    for key, value in values.items():
        if key not in written:
            out.append(f"{key}={value}")
    atomic_write_text(ini_path(), "\n".join(out) + "\n")


def patches_dir(settings):
    return Path(settings.get("patches_dir") or DATA_DIR / "patches").expanduser()


def game_info(path):
    """(title, version) from the game's param.sfo, or None when it cannot be read."""
    game = Path(path)
    try:
        from prepare import sfo
        values = sfo((game / "sce_sys" / "param.sfo").read_bytes())
    except (OSError, ValueError, ImportError):
        return None
    title = str(values.get("TITLE") or values.get("TITLE_ID") or "Bloodborne")
    version = str(values.get("APP_VER") or values.get("VERSION") or "")
    return title, version


def game_environment(s):
    """Environment for run.sh from the launcher settings."""
    env = dict(os.environ)
    env["BB_GAME_DIR"] = str(Path(s["game_dir"]).expanduser())
    env["BB_USER_DIR"] = str(Path(s["user_dir"]).expanduser() if s["user_dir"]
                             else DATA_DIR / "user")
    if s.get("player_name", "").strip():
        env["BB_USER_NAME"] = s["player_name"].strip()
    if s.get("dlc_dir", "").strip():
        env["BB_DLC_DIR"] = str(Path(s["dlc_dir"]).expanduser())
    env["BB_MODS_DIR"] = str(Path(s.get("mods_dir") or DATA_DIR / "mods").expanduser())
    env["BB_MODS_CONFIG"] = str(DATA_DIR / "mods.json")
    env["BB_MODS_ENABLED"] = "1" if s.get("mods_enabled", True) else "0"
    scheme = canonical_control_scheme(s.get("control_scheme"))
    keyboard = (scheme == "pc")
    if not keyboard and s.get("mods_enabled", True):
        try:
            mods_cfg = DATA_DIR / "mods.json"
            if mods_cfg.is_file():
                cfg = json.loads(mods_cfg.read_text(encoding="utf-8"))
                keyboard = any(is_keyboard_prompt(n) for n in cfg.get("enabled", []))
        except (OSError, ValueError):
            pass
    env["BB_BUTTON_PROMPTS"] = "Keyboard" if keyboard else ""
    env["BB_KEY_PROMPT_IMAGES"] = "1" if keyboard else "0"
    env["BB_PATCHES_DIR"] = str(patches_dir(s))
    env["BB_PATCHES_CONFIG"] = str(DATA_DIR / "patches.json")
    env["BB_LANGUAGE"] = s["language"]
    env["BB_FULLSCREEN"] = "1" if s["fullscreen"] else "0"
    env["BB_PRESENT_MODE"] = s["present_mode"]
    if s["hdr"]:
        env["BB_HDR"] = "1"
    env["BB_FPS"] = s["fps_mode"]
    if s["fps_limit"] > 0:
        env["BB_FPS_LIMIT"] = str(s["fps_limit"])
    # 1 is the game's default; only export a different overlap bound (0 = unlimited).
    frames_ahead = int(s.get("frames_ahead", 1))
    if frames_ahead != 1:
        env["BB_FRAMES_AHEAD"] = str(frames_ahead)
    if s["draw_pipe"]:
        env["BB_DRAW_PIPE"] = s["draw_pipe"]
    if s["readbacks"]:
        env["BB_READBACKS"] = s["readbacks"]
    if s["mangohud"]:
        env["MANGOHUD"] = "1"
    if s["frame_stats"]:
        env["BB_FRAME_STATS"] = "1"
    if s["gpu_profile"]:
        env["BB_GPU_PROFILE"] = "1"
    if s["vk_validation"]:
        env["BB_VK_VALIDATION"] = "1"
    env["BB_SHADER_PREBUILD"] = "1" if s.get("precompile_shaders", True) else "0"
    env["BB_DISCORD_RPC"] = "1" if s.get("discord_rpc", True) else "0"
    for item in s["extra_env"].split():
        if "=" in item:
            key, value = item.split("=", 1)
            env[key] = value
    return env


def flat_button(icon, tooltip, handler):
    button = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, tooltip_text=tooltip)
    button.add_css_class("flat")
    button.connect("clicked", handler)
    return button


def open_folder(window, path):
    """Opens `path` in the file manager."""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(window, None, None)


def combo_row(title, subtitle, choices, current):
    values = [value for _, value in choices]
    if current not in values:
        choices = [*choices, (str(current), current)]
        values.append(current)
    labels = [GLib.markup_escape_text(tr(label)) for label, _ in choices]
    model = Gtk.StringList.new(labels)
    row = Adw.ComboRow(title=title, model=model)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_selected(values.index(current))
    row.values = values
    return row


def combo_value(row):
    return row.values[row.get_selected()]


def invalid_utf8(error):
    """Whether `error` is GLib's UTF-8 conversion failure."""
    quark = GLib.convert_error_quark() if hasattr(GLib, "convert_error_quark") else None
    return getattr(error, "domain", None) in ("g_convert_error", quark)


class FolderList:
    """A preferences group with a folder row and one switch row per item below it."""

    def __init__(self, group):
        self.group = group
        self.rows = []

    def clear(self):
        for _, row in self.rows:
            self.group.remove(row)
        self.rows = []

    def add(self, key, row):
        self.group.add(row)
        self.rows.append((key, row))


def expand_preferences_page(page, max_size=1150, tightening_threshold=900):
    """Walk the widget hierarchy of an Adw.PreferencesPage to expand its internal Adw.Clamp."""
    def walk(widget):
        if widget is None:
            return
        if hasattr(widget, "set_maximum_size"):
            widget.set_maximum_size(max_size)
        if hasattr(widget, "set_tightening_threshold"):
            widget.set_tightening_threshold(tightening_threshold)
        child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
        while child:
            walk(child)
            child = child.get_next_sibling()
    walk(page)


FALLBACK_CSS = b"""
window.bbport-window { background-color: #08090c; color: #f2f2f2; }
headerbar.ps5-header { background-color: transparent; border: none; box-shadow: none; }
button.ps5-nav-item { background: transparent; border: none; color: rgba(255,255,255,.6); }
button.ps5-nav-item.active { color: #fff; border-bottom: 2px solid #fff; }
button.ps5-play { background-color: #f2f0ec; color: #0a0b0f; border-radius: 999px; }
.ps5-backdrop-shade { background-color: rgba(8, 9, 12, 0.72); }
.ps5-info-row { border-bottom: 1px solid rgba(255,255,255,.1); }
"""


def install_theme():
    """Installs the launcher's restrained dark theme from theme.css."""
    try:
        css = THEME_FILE.read_bytes()
    except OSError:
        css = FALLBACK_CSS
    try:
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        display = Gdk.Display.get_default() if hasattr(Gdk, "Display") else None
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        if hasattr(Adw, "StyleManager"):
            style_manager = Adw.StyleManager.get_default()
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    except Exception:
        pass


class LauncherWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Bloodborne")
        self.set_default_size(1180, 760)
        self.set_size_request(900, 600)
        self.add_css_class("bbport-window")
        install_theme()
        self.settings = load_settings()
        set_language(self.settings.get("ui_language") or "en")
        self.ini, self.ini_lines = load_ini()
        self.process = None
        self._stopping_pid = None
        self.stream = None
        self.downloading_fsr4 = False
        self.precompiling = False
        self.launch_state = "idle"
        self.log_entries = []
        self.trophies = None
        self.session_started_at = None
        self._seen_trophy_ids = None
        self._trophy_poll_source = None
        self.settings_category = ""
        self.build()
        self.connect("close-request", self.on_close)

    def build(self):
        """(Re)creates the PS5-style shell in the current language."""
        prev_page = (self.stack.get_visible_child_name()
                     if hasattr(self, "stack") and self.stack.get_visible_child_name()
                     else "details")
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("ps5-header")

        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand_box.set_valign(Gtk.Align.CENTER)
        brand_box.add_css_class("ps5-brand")
        mark = PORT_DIR / "launcher" / "assets" / "hunter-icon.png"
        if not mark.is_file():
            mark = LAUNCHER_DIR / "assets" / "hunter-icon.png"
        if mark.is_file():
            brand_mark = self.square_picture(mark, 28)
            if brand_mark is not None:
                brand_mark.add_css_class("ps5-brand-mark")
                brand_box.append(brand_mark)
        brand_title = Gtk.Label(label="Bloodborne", xalign=0)
        brand_title.add_css_class("ps5-brand-title")
        brand_box.append(brand_title)
        header.pack_start(brand_box)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=160, vexpand=True, hexpand=True)
        self.stack.add_css_class("ps5-shell")

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=26)
        nav.add_css_class("ps5-nav")
        self.nav_buttons = {}
        for key, label in (("details", tr("Game Details")),
                           ("trophies", tr("Trophies")),
                           ("settings", tr("Settings"))):
            button = Gtk.Button(label=label)
            button.add_css_class("ps5-nav-item")
            button.set_tooltip_text(label)
            if key == "settings":
                button.connect("clicked", lambda _button: self.show_settings_menu())
            else:
                button.connect("clicked", lambda _button, name=key: self.show_page(name))
            self.nav_buttons[key] = button
            nav.append(button)
        header.set_title_widget(nav)

        self.shell_status_dot = Gtk.Box()
        self.shell_status_dot.add_css_class("ps5-status-dot")
        self.shell_status_dot.set_size_request(7, 7)
        self.shell_status_dot.set_halign(Gtk.Align.CENTER)
        self.shell_status_dot.set_valign(Gtk.Align.CENTER)
        self.shell_status_label = Gtk.Label(label=tr("Ready"))
        self.shell_status_label.add_css_class("ps5-status-text")
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.append(self.shell_status_dot)
        status_box.append(self.shell_status_label)
        self.shell_status_button = Gtk.Button()
        self.shell_status_button.add_css_class("ps5-status")
        self.shell_status_button.set_child(status_box)
        self.shell_status_button.set_tooltip_text(tr("Game Details"))
        self.shell_status_button.connect("clicked", lambda _button: self.show_page("details"))
        header.pack_end(self.shell_status_button)
        toolbar.add_top_bar(header)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(self.stack)
        toolbar.set_content(self.toasts)
        self.set_content(toolbar)

        self.pages = {
            "details": self.build_details_page(),
            "trophies": self.build_trophies_page(),
            "settings": self.build_settings_shell(),
        }
        for key, page in self.pages.items():
            self.stack.add_named(page, key)
        requested_page = os.environ.get("BB_LAUNCHER_PAGE")
        if requested_page in self.pages:
            prev_page = requested_page
        requested_category = os.environ.get("BB_LAUNCHER_CATEGORY")
        if requested_category in getattr(self, "settings_category_pages", {}):
            self.settings_category = requested_category
            prev_page = "settings"
        self.stack.connect("notify::visible-child", self.on_page_changed)

        self.stack.set_visible_child_name(prev_page if prev_page in self.pages else "details")
        if self.stack.get_visible_child_name() == "settings":
            if getattr(self, "settings_category", "") in getattr(
                    self, "settings_category_pages", {}):
                self.show_settings_category(self.settings_category)
            else:
                self.show_settings_menu()
        self.on_page_changed(self.stack, None)
        self.set_reduce_motion(bool(self.settings.get("reduce_motion", False)))
        self.refresh_log_view()
        self.refresh_details()
        self.refresh_trophies()
        self.update_shell_status()

    def show_page(self, name):
        if name in getattr(self, "pages", {}):
            self.stack.set_visible_child_name(name)

    def show_settings_menu(self):
        self.settings_category = ""
        self.show_page("settings")
        if hasattr(self, "settings_view_stack"):
            self.settings_view_stack.set_visible_child_name("menu")

    def show_settings_category(self, category):
        if category not in getattr(self, "settings_category_pages", {}):
            category = "display"
        self.settings_category = category
        self.show_page("settings")
        if hasattr(self, "settings_view_stack"):
            self.settings_view_stack.set_visible_child_name("category")
        if hasattr(self, "settings_category_stack"):
            self.settings_category_stack.set_visible_child_name(category)
        if hasattr(self, "settings_category_title"):
            self.settings_category_title.set_text(
                self.settings_category_labels.get(category, category))

    def on_page_changed(self, _stack, _param):
        visible = self.stack.get_visible_child_name()
        for key, button in getattr(self, "nav_buttons", {}).items():
            button.remove_css_class("active")
            if key == visible:
                button.add_css_class("active")
        if visible == "trophies":
            self.refresh_trophies()
        elif visible == "details":
            self.refresh_details()
        elif visible == "settings" and hasattr(self, "settings_view_stack"):
            if not getattr(self, "settings_category", ""):
                self.settings_view_stack.set_visible_child_name("menu")

    def update_shell_status(self):
        if not hasattr(self, "shell_status_label"):
            return
        ok = bool(self.settings.get("game_dir")) and (self.game_dir() / "eboot.bin").is_file()
        if self.launch_state == "running":
            text, state = tr("Running"), "running"
        elif self.launch_state in ("starting", "stopping"):
            text, state = tr("Starting…") if self.launch_state == "starting" else tr("Stopping…"), "running"
        elif ok:
            text, state = tr("Ready"), "ready"
        else:
            text, state = tr("Game not found"), "error"
        self.shell_status_label.set_text(text)
        for name in ("ready", "running", "error"):
            self.shell_status_dot.remove_css_class(name)
        self.shell_status_dot.add_css_class(state)
        if hasattr(self, "hero_status_dot"):
            for name in ("ready", "running", "error"):
                self.hero_status_dot.remove_css_class(name)
            self.hero_status_dot.add_css_class(state)


    # --- Shared page helpers -------------------------------------------------------------

    def page_scroller(self, content):
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.add_css_class("page-scroller")
        scroller.set_child(content)
        return scroller

    def page_content(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.add_css_class("page-content")
        return content

    def text_label(self, text, css_class=None, xalign=0, wrap=False):
        label = Gtk.Label(label=text, xalign=xalign)
        if css_class:
            label.add_css_class(css_class)
        if wrap:
            label.set_wrap(True)
            label.set_max_width_chars(96)
        return label

    def text_link(self, text, callback):
        button = Gtk.Button(label=text)
        button.add_css_class("text-link")
        button.connect("clicked", lambda _button: callback())
        return button

    def activity_row(self, event):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("activity-row")
        stamp = datetime.fromtimestamp(event["time"]).strftime("%H:%M")
        row.append(self.text_label(stamp, "activity-time"))
        row.append(self.text_label(event["text"], "activity-text", wrap=True))
        return row

    def square_picture(self, path, size):
        """A fixed-size square image, center-cropped without stretching."""
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
            width, height = pixbuf.get_width(), pixbuf.get_height()
            side = min(width, height)
            pixbuf = pixbuf.new_subpixbuf((width - side) // 2, (height - side) // 2,
                                          side, side)
            pixbuf = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            image = Gtk.Image.new_from_pixbuf(pixbuf)
            image.set_pixel_size(size)
            image.set_size_request(size, size)
            return image
        except (GLib.Error, ValueError):
            return None

    def ps5_info_row(self, label_text, value_attr):
        """A PS5 information-screen row: quiet label left, light value right."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        row.add_css_class("ps5-info-row")
        label = self.text_label(label_text, "ps5-info-label")
        label.set_valign(Gtk.Align.CENTER)
        row.append(label)
        value = self.text_label("", "ps5-info-value")
        value.set_hexpand(True)
        value.set_halign(Gtk.Align.END)
        value.set_xalign(1.0)
        value.set_ellipsize(Pango.EllipsizeMode.END)
        setattr(self, value_attr, value)
        row.append(value)
        return row

    def make_readiness_row(self, label_text):
        row = Adw.ActionRow(title=label_text)
        icon = Gtk.Image()
        icon.set_from_icon_name("dialog-information-symbolic")
        row.add_prefix(icon)
        self.readiness_rows[label_text] = row
        self.readiness_icons[label_text] = icon
        return row

    def clear_box(self, box):
        child = box.get_first_child() if hasattr(box, "get_first_child") else None
        while child:
            next_child = child.get_next_sibling()
            box.remove(child)
            child = next_child

    # --- Game Details --------------------------------------------------------------------

    def build_details_page(self):
        """Full-bleed PS5 game information screen with the Play action."""
        page = Gtk.Overlay()
        page.add_css_class("ps5-screen")

        artwork = LAUNCHER_DIR / "art" / "hero.png"
        if not artwork.is_file():
            artwork = PORT_DIR / "launcher" / "art" / "hero.png"
        if artwork.is_file():
            picture = Gtk.Picture.new_for_filename(str(artwork))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_hexpand(True)
            picture.set_vexpand(True)
            picture.add_css_class("ps5-backdrop-art")
            page.set_child(picture)
        else:
            fallback = Gtk.Box()
            fallback.add_css_class("ps5-backdrop-fallback")
            page.set_child(fallback)

        shade = Gtk.Box()
        shade.add_css_class("ps5-backdrop-shade")
        page.add_overlay(shade)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.add_css_class("ps5-details-content")

        content.append(self.text_label(tr("Game Details"), "ps5-screen-eyebrow"))

        main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=38)
        main.add_css_class("ps5-details-main")

        tile = Gtk.Box()
        tile.add_css_class("ps5-game-tile")
        tile.set_size_request(214, 214)
        tile.set_halign(Gtk.Align.START)
        tile.set_valign(Gtk.Align.START)
        tile.set_hexpand(False)
        tile.set_vexpand(False)
        icon_path = PORT_DIR / "launcher" / "assets" / "hunter-icon.png"
        if not icon_path.is_file():
            icon_path = LAUNCHER_DIR / "assets" / "hunter-icon.png"
        tile_art = self.square_picture(icon_path, 214) if icon_path.is_file() else None
        if tile_art is not None:
            tile_art.add_css_class("ps5-game-tile-art")
            tile.append(tile_art)
        else:
            tile.append(self.text_label("B", "ps5-tile-fallback"))
        main.append(tile)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        right.set_hexpand(True)
        right.append(self.text_label("Bloodborne", "ps5-game-title"))
        right.append(self.text_label(f"{tr('NATIVE LINUX PORT')} · {VERSION}",
                                     "ps5-game-subtitle"))

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        action_row.add_css_class("ps5-game-actions")
        self.hero_launch_button = Gtk.Button()
        self.hero_launch_button.add_css_class("ps5-play")
        self.hero_launch_button.connect("clicked", self.on_launch)
        self.launch_button = self.hero_launch_button
        action_row.append(self.hero_launch_button)
        secondary = self.text_link(tr("Choose game folder"),
                                   lambda: self.show_settings_category("game_data"))
        secondary.add_css_class("ps5-secondary-action")
        action_row.append(secondary)

        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        status.add_css_class("ps5-game-status")
        status.set_valign(Gtk.Align.CENTER)
        self.hero_status_dot = Gtk.Box()
        self.hero_status_dot.add_css_class("ps5-status-dot")
        self.hero_status_dot.set_size_request(8, 8)
        self.hero_status_dot.set_halign(Gtk.Align.CENTER)
        self.hero_status_dot.set_valign(Gtk.Align.CENTER)
        status.append(self.hero_status_dot)
        status_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.hero_status_label = self.text_label("", "ps5-status-title")
        self.hero_status_detail = self.text_label("", "ps5-status-detail")
        status_text.append(self.hero_status_label)
        status_text.append(self.hero_status_detail)
        status.append(status_text)
        action_row.append(status)
        right.append(action_row)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        info.add_css_class("ps5-info-table")
        info.append(self.ps5_info_row(tr("Game files"), "hero_game_summary"))
        info.append(self.ps5_info_row(tr("Play time"), "hero_playtime_summary"))
        info.append(self.ps5_info_row(tr("Graphics profile"), "hero_graphics_summary"))
        info.append(self.ps5_info_row(tr("Trophies"), "hero_trophy_summary"))
        info.append(self.ps5_info_row(tr("Save data"), "hero_hunter_summary"))
        info.append(self.ps5_info_row(tr("FSR 4 assets"), "hero_assets_summary"))
        right.append(info)
        self.hero_fsr_summary = self.hero_assets_summary

        snapshot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        snapshot.add_css_class("ps5-details-trophy-strip")
        self.details_trophy_progress = Gtk.ProgressBar()
        self.details_trophy_progress.add_css_class("ps5-progress")
        self.details_trophy_progress.set_show_text(False)
        self.details_trophy_progress.set_hexpand(True)
        snapshot.append(self.details_trophy_progress)
        snapshot_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.details_trophy_count = self.text_label("", "ps5-trophy-count")
        self.details_trophy_meta = self.text_label("", "ps5-meta", wrap=True)
        snapshot_row.append(self.details_trophy_count)
        snapshot_row.append(self.details_trophy_meta)
        snap_spacer = Gtk.Box()
        snap_spacer.set_hexpand(True)
        snapshot_row.append(snap_spacer)
        snapshot_row.append(self.text_link(tr("View all trophies"),
                                           lambda: self.show_page("trophies")))
        snapshot.append(snapshot_row)
        right.append(snapshot)
        main.append(right)
        content.append(main)

        activity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        activity.add_css_class("ps5-activity-block")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        head.append(self.text_label(tr("Recent activity"), "ps5-section-title"))
        head.append(self.text_link(tr("Open diagnostics"),
                                   lambda: self.show_settings_category("diagnostics")))
        activity.append(head)
        self.activity_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.activity_list.add_css_class("ps5-activity-list")
        self.activity_label = self.text_label("", "ps5-meta", wrap=True)
        self.activity_list.append(self.activity_label)
        activity.append(self.activity_list)
        content.append(activity)

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.add_css_class("ps5-scroll")
        scroller.set_child(content)
        page.add_overlay(scroller)
        return page

    def refresh_details(self):
        if not hasattr(self, "hero_game_summary"):
            return
        self.update_game_status()
        self.update_user_status()
        self.update_dlc_status()
        self.update_upscaler_status()
        self.refresh_fsr4_status()
        self.update_playtime_summary()
        self.update_recent_activity()
        self.update_trophy_snapshot()
        self.refresh_readiness()
        self.update_shell_status()

    # --- Trophies ------------------------------------------------------------------------

    def build_trophies_page(self):
        """PS5 trophy screen: summary header, filter, and large rounded rows."""
        page = Gtk.Overlay()
        page.add_css_class("ps5-screen")
        art = PORT_DIR / "launcher" / "art" / "strip.png"
        if art.is_file():
            picture = Gtk.Picture.new_for_filename(str(art))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_hexpand(True)
            picture.set_vexpand(True)
            picture.add_css_class("ps5-backdrop-art")
            page.set_child(picture)
        else:
            fallback = Gtk.Box()
            fallback.add_css_class("ps5-backdrop-fallback")
            page.set_child(fallback)
        shade = Gtk.Box()
        shade.add_css_class("ps5-backdrop-shade")
        shade.add_css_class("ps5-trophy-shade")
        page.add_overlay(shade)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.add_css_class("ps5-trophies-content")
        content.append(self.text_label(tr("Trophies"), "ps5-screen-eyebrow"))

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header.add_css_class("ps5-trophy-header")
        icon_path = PORT_DIR / "launcher" / "assets" / "hunter-icon.png"
        if not icon_path.is_file():
            icon_path = LAUNCHER_DIR / "assets" / "hunter-icon.png"
        game_icon = self.square_picture(icon_path, 64) if icon_path.is_file() else None
        if game_icon is not None:
            game_icon.add_css_class("ps5-game-icon")
            header.append(game_icon)
        identity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        identity.set_valign(Gtk.Align.CENTER)
        self.trophy_game_title = self.text_label("Bloodborne", "ps5-game-title")
        self.trophy_subtitle = self.text_label(tr("Trophies"), "ps5-game-subtitle")
        identity.append(self.trophy_game_title)
        identity.append(self.trophy_subtitle)
        header.append(identity)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        progress_block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        progress_block.add_css_class("ps5-trophy-stat")
        progress_block.append(self.text_label(tr("Progress"), "ps5-stat-label"))
        self.trophy_percent_label = self.text_label("", "ps5-stat-value")
        progress_block.append(self.trophy_percent_label)
        self.trophy_progress = Gtk.ProgressBar()
        self.trophy_progress.add_css_class("ps5-progress")
        self.trophy_progress.set_show_text(False)
        self.trophy_progress.set_size_request(132, -1)
        progress_block.append(self.trophy_progress)
        header.append(progress_block)

        earned_block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        earned_block.add_css_class("ps5-trophy-stat")
        earned_block.append(self.text_label(tr("Earned"), "ps5-stat-label"))
        self.trophy_count_label = self.text_label("", "ps5-stat-value")
        earned_block.append(self.trophy_count_label)
        header.append(earned_block)

        self.trophy_grade_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.trophy_grade_box.add_css_class("ps5-grade-summary")
        self.trophy_grade_box.set_valign(Gtk.Align.END)
        header.append(self.trophy_grade_box)
        self.trophy_progress_block = progress_block
        self.trophy_earned_block = earned_block
        self.trophy_summary_note = self.text_label(tr("Trophy details unavailable"),
                                                  "ps5-meta")
        self.trophy_summary_note.set_valign(Gtk.Align.CENTER)
        header.append(self.trophy_summary_note)
        content.append(header)

        self.trophy_local_note = self.text_label("", "ps5-meta", wrap=True)
        content.append(self.trophy_local_note)
        self.trophy_warning = self.text_label("", "ps5-warning", wrap=True)
        self.trophy_warning.set_visible(False)
        content.append(self.trophy_warning)

        subheader = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        subheader.add_css_class("ps5-trophy-subheader")
        self.trophy_all_label = self.text_label("", "ps5-meta")
        subheader.append(self.trophy_all_label)
        sub_spacer = Gtk.Box()
        sub_spacer.set_hexpand(True)
        subheader.append(sub_spacer)

        self.trophy_sort_values = ["default", "grade", "recent"]
        self.trophy_sort = "default"
        self.trophy_sort_button = Gtk.MenuButton()
        self.trophy_sort_button.add_css_class("ps5-sort")
        self.trophy_sort_label = Gtk.Label(label=tr("Sort by: {}").format(tr("Game Default")))
        self.trophy_sort_button.set_child(self.trophy_sort_label)
        sort_popover = Gtk.Popover()
        sort_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for value, label in (("default", tr("Game Default")), ("grade", tr("Grade")),
                             ("recent", tr("Recently earned"))):
            choice = Gtk.Button(label=label)
            choice.add_css_class("ps5-popover-item")
            choice.connect("clicked", lambda _b, v=value: self.set_trophy_sort(v))
            sort_box.append(choice)
        sort_popover.set_child(sort_box)
        self.trophy_sort_button.set_popover(sort_popover)
        subheader.append(self.trophy_sort_button)
        content.append(subheader)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        body.set_vexpand(True)
        body.add_css_class("ps5-trophy-body")

        self.trophy_filter_values = ["all", "earned", "locked"]
        self.trophy_filter = "all"
        self.trophy_filter_button = Gtk.MenuButton()
        self.trophy_filter_button.set_icon_name("view-filter-symbolic")
        self.trophy_filter_button.add_css_class("ps5-filter")
        self.trophy_filter_button.set_valign(Gtk.Align.START)
        self.trophy_filter_button.set_tooltip_text(tr("Filter"))
        filter_popover = Gtk.Popover()
        filter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for value, label in (("all", tr("All")), ("earned", tr("Earned")),
                             ("locked", tr("Locked"))):
            choice = Gtk.Button(label=label)
            choice.add_css_class("ps5-popover-item")
            choice.connect("clicked", lambda _b, v=value: self.set_trophy_filter(v))
            filter_box.append(choice)
        filter_popover.set_child(filter_box)
        self.trophy_filter_button.set_popover(filter_popover)
        body.append(self.trophy_filter_button)

        self.trophy_content_stack = Gtk.Stack()
        self.trophy_content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.trophy_content_stack.set_transition_duration(120)
        self.trophy_content_stack.set_vexpand(True)
        self.trophy_content_stack.set_hexpand(True)

        self.trophy_list = Gtk.ListBox()
        self.trophy_list.add_css_class("ps5-trophy-list")
        self.trophy_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.trophy_list.set_vexpand(True)
        list_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        list_scroller.add_css_class("ps5-scroll")
        list_scroller.set_child(self.trophy_list)
        self.trophy_content_stack.add_named(list_scroller, "list")

        self.trophy_empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.trophy_empty.add_css_class("ps5-empty")
        self.trophy_empty.set_halign(Gtk.Align.CENTER)
        self.trophy_empty.set_valign(Gtk.Align.CENTER)
        self.trophy_empty_title = self.text_label("", "ps5-empty-title")
        self.trophy_empty_title.set_halign(Gtk.Align.CENTER)
        self.trophy_empty_body = self.text_label("", "ps5-meta", xalign=0.5, wrap=True)
        self.trophy_empty_body.set_halign(Gtk.Align.CENTER)
        self.trophy_empty_body.set_max_width_chars(64)
        self.trophy_empty.append(self.trophy_empty_title)
        self.trophy_empty.append(self.trophy_empty_body)
        empty_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        empty_actions.set_halign(Gtk.Align.CENTER)
        open_data = Gtk.Button(label=tr("Open Game & Data"))
        open_data.add_css_class("ps5-button")
        open_data.connect("clicked", lambda _b: self.show_settings_category("game_data"))
        import_keys = Gtk.Button(label=tr("Import keys.json"))
        import_keys.add_css_class("ps5-button-primary")
        import_keys.connect("clicked", self.on_import_trophy_keys)
        empty_actions.append(open_data)
        empty_actions.append(import_keys)
        self.trophy_empty.append(empty_actions)
        self.trophy_content_stack.add_named(self.trophy_empty, "empty")
        body.append(self.trophy_content_stack)
        content.append(body)
        page.add_overlay(content)
        return page

    def set_trophy_filter(self, value):
        self.trophy_filter = value
        if hasattr(self, "trophy_filter_button"):
            self.trophy_filter_button.set_tooltip_text(
                tr("Filter") + ": " + {"all": tr("All"), "earned": tr("Earned"),
                                       "locked": tr("Locked")}.get(value, tr("All")))
        self.refresh_trophies()

    def set_trophy_sort(self, value):
        self.trophy_sort = value
        labels = {"default": tr("Game Default"), "grade": tr("Grade"),
                  "recent": tr("Recently earned")}
        if hasattr(self, "trophy_sort_label"):
            self.trophy_sort_label.set_text(
                tr("Sort by: {}").format(labels.get(value, tr("Game Default"))))
        self.refresh_trophies()

    def refresh_trophies(self):
        if not hasattr(self, "trophy_list"):
            return
        report = load_trophy_report(
            self.user_dir(), self.game_dir() if self.settings.get("game_dir") else None)
        self.trophies = report
        self._record_new_trophies(report)
        available = report.metadata_available
        self.trophy_game_title.set_text(report.set_title or "Bloodborne")
        self.trophy_progress.set_visible(available)
        self.trophy_progress.set_fraction((report.completion or 0) / 100)
        self.trophy_filter_button.set_visible(available)
        self.trophy_sort_button.set_visible(available)
        self.trophy_progress_block.set_visible(available)
        self.trophy_earned_block.set_visible(available)
        self.trophy_grade_box.set_visible(available)
        self.trophy_summary_note.set_visible(not available)
        self.clear_box(self.trophy_grade_box)
        if available:
            self.trophy_count_label.set_text(f"{report.earned}/{report.total}")
            self.trophy_percent_label.set_text(f"{report.completion}%")
            self.trophy_all_label.set_text(tr("All trophies: {}").format(report.total))
            for grade in ("P", "G", "S", "B"):
                badge = self.text_label(
                    grade, f"ps5-grade ps5-grade-{grade}")
                badge.set_valign(Gtk.Align.CENTER)
                count = self.text_label(str(report.grade_counts.get(grade, 0)),
                                        "ps5-grade-count")
                pair = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                pair.append(badge)
                pair.append(count)
                self.trophy_grade_box.append(pair)
            self.trophy_local_note.set_text(
                tr("Local records from this port. Not synced to PlayStation Network."))
        else:
            self.trophy_count_label.set_text("—")
            self.trophy_percent_label.set_text("—")
            self.trophy_all_label.set_text("")
            self.trophy_local_note.set_text(
                tr("{} local unlocks recorded.").format(report.local_unlocks))

        stale = report.stale and available
        self.trophy_warning.set_visible(stale)
        if stale:
            self.trophy_warning.set_text(
                tr("Cached trophy data is older than the current trophy pack."))

        self.trophy_content_stack.set_visible_child_name("list" if available else "empty")
        if not available:
            self.trophy_empty_title.set_text(
                tr("No trophy data yet") if not report.metadata_complete
                else tr("Trophy details are not available yet"))
            body = report.reason or tr("Trophy metadata is unavailable.")
            if report.local_unlocks:
                body += "\n" + tr("{} local unlocks recorded.").format(report.local_unlocks)
            self.trophy_empty_body.set_text(body)
            self.clear_box(self.trophy_list)
            self.update_trophy_snapshot()
            return

        entries = list(report.entries)
        if self.trophy_filter == "earned":
            entries = [entry for entry in entries if entry.earned]
        elif self.trophy_filter == "locked":
            entries = [entry for entry in entries if not entry.earned]
        if self.trophy_sort == "grade":
            entries.sort(key=lambda entry: (GRADE_ORDER.get(entry.grade, 4), entry.id))
        elif self.trophy_sort == "recent":
            entries.sort(key=lambda entry: (0 if entry.earned else 1,
                                            -(entry.unlocked_at or 0), entry.id))
        self.clear_box(self.trophy_list)
        groups = []
        if self.trophy_filter != "locked":
            groups.append((tr("Unlocked"), [entry for entry in entries if entry.earned]))
        if self.trophy_filter != "earned":
            groups.append((tr("Locked"), [entry for entry in entries if not entry.earned]))
        shown = 0
        for title, group in groups:
            if not group:
                continue
            self.trophy_list.append(self.make_trophy_section_row(title, len(group)))
            for entry in group:
                self.trophy_list.append(self.make_trophy_row(entry))
                shown += 1
        if not shown:
            empty_row = Gtk.ListBoxRow()
            empty_row.set_activatable(False)
            empty_row.set_selectable(False)
            empty_row.set_child(self.text_label(tr("No trophies match this filter."),
                                               "ps5-meta"))
            self.trophy_list.append(empty_row)
        self.update_trophy_snapshot()

    def make_trophy_section_row(self, title, count):
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        row.add_css_class("ps5-trophy-section")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        line.append(self.text_label(f"{title} ({count})", "ps5-trophy-section-title"))
        row.set_child(line)
        return row

    def make_trophy_row(self, entry):
        row = Gtk.ListBoxRow()
        row.add_css_class("ps5-trophy-row")
        row.set_activatable(False)
        row.set_selectable(False)
        row.add_css_class("earned" if entry.earned else "locked")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        line.add_css_class("ps5-trophy-row-line")

        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        icon_box.set_size_request(54, 54)
        icon_box.add_css_class("ps5-trophy-icon")
        icon_box.add_css_class(f"ring-{entry.grade}" if entry.grade in GRADES else "ring-unknown")
        icon_box.set_valign(Gtk.Align.CENTER)
        if entry.icon is not None:
            picture = Gtk.Picture.new_for_filename(str(entry.icon))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_size_request(52, 52)
            icon_box.append(picture)
        else:
            fallback = self.text_label("?" if entry.grade == "?" else entry.grade,
                                       "ps5-trophy-icon-fallback")
            fallback.set_halign(Gtk.Align.CENTER)
            fallback.set_valign(Gtk.Align.CENTER)
            icon_box.append(fallback)
        line.append(icon_box)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        body.set_hexpand(True)
        body.set_valign(Gtk.Align.CENTER)
        secret = entry.hidden and not entry.earned
        name_label = self.text_label(tr("Secret trophy") if secret else entry.name,
                                     "ps5-trophy-name")
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        body.append(name_label)
        grade_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        grade = entry.grade if entry.grade in GRADES else "?"
        badge = self.text_label(grade, f"ps5-grade ps5-grade-{grade}"
                                if grade in GRADES else "ps5-grade ps5-grade-unknown")
        grade_line.append(badge)
        grade_line.append(self.text_label(
            tr(GRADE_NAMES.get(grade, "Unknown")), "ps5-trophy-state"))
        body.append(grade_line)
        line.append(body)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        meta.add_css_class("ps5-trophy-detail")
        meta.set_size_request(330, -1)
        meta.set_valign(Gtk.Align.CENTER)
        if entry.earned and entry.unlocked_at:
            try:
                stamp = datetime.fromtimestamp(entry.unlocked_at).strftime("%d/%m/%Y %H:%M")
            except (OSError, OverflowError, ValueError):
                stamp = tr("Unknown date")
            meta.append(self.text_label(tr("Unlocked {}").format(stamp), "ps5-trophy-date"))
        elif entry.earned:
            meta.append(self.text_label(tr("Earned locally"), "ps5-trophy-date"))
        else:
            meta.append(self.text_label(tr("Not earned locally"), "ps5-trophy-date"))
        if secret:
            meta.append(self.text_label(tr("Hidden until earned"), "ps5-trophy-description"))
        elif entry.description:
            description = self.text_label(entry.description, "ps5-trophy-description", wrap=True)
            description.set_lines(2)
            description.set_ellipsize(Pango.EllipsizeMode.END)
            meta.append(description)
        line.append(meta)
        row.set_child(line)
        return row

    def update_trophy_snapshot(self):
        if not hasattr(self, "details_trophy_count"):
            return
        report = self.trophies
        if report and report.metadata_available:
            summary = tr("{} of {} trophies").format(report.earned, report.total)
            self.details_trophy_count.set_text(summary)
            self.details_trophy_meta.set_text(f"{report.completion}% · " + tr("Local records only"))
            self.details_trophy_progress.set_fraction((report.completion or 0) / 100)
            self.hero_trophy_summary.set_text(f"{summary} · {report.completion}%")
        else:
            self.details_trophy_count.set_text(tr("Trophy details unavailable"))
            local = report.local_unlocks if report else 0
            self.details_trophy_meta.set_text(
                tr("{} local unlocks recorded.").format(local))
            self.details_trophy_progress.set_fraction(0)
            self.hero_trophy_summary.set_text(
                tr("{} local unlocks recorded.").format(local))



    # --- Settings ------------------------------------------------------------------------

    def category_page(self, *groups):
        page = Adw.PreferencesPage()
        for group in groups:
            if group is None:
                continue
            if group.get_parent() is not None:
                group.unparent()
            page.add(group)
        expand_preferences_page(page, max_size=1040, tightening_threshold=860)
        return page

    def build_settings_shell(self):
        self.build_graphics_page()
        self.build_game_page()
        self.build_downloads_page()
        self.keybinding_rows = {}
        self.keybinding_groups = [
            self.build_keybinding_group(section, specs, with_note=(index == 0))
            for index, (section, specs) in enumerate(KEY_BINDING_SECTIONS)
        ]
        self.keybinding_reset_group = self.build_keybinding_reset_group()

        for row in (getattr(self, "validation_row", None), getattr(self, "extra_row", None)):
            if row is not None:
                if row.get_parent() is not None:
                    self.perf_group.remove(row)
                self.compat_group.add(row)
        if hasattr(self, "discord_row") and self.discord_row.get_parent() is not None:
            self.perf_group.remove(self.discord_row)
        integrations = Adw.PreferencesGroup(
            title=tr("Integrations"),
            description=tr("Optional runtime integrations."))
        if hasattr(self, "discord_row"):
            integrations.add(self.discord_row)

        self.render_group.set_title(tr("Output and presentation"))
        self.render_group.set_description(tr("Output resolution, HDR and frame presentation."))
        self.quality_group.set_title(tr("Image quality"))
        self.quality_group.set_description(tr("Sharpening, model detail and image effects."))
        self.upscale_group.set_title(tr("Reconstruction"))
        self.upscale_group.set_description(
            tr("Preset, reconstruction, FSR assets and motion vectors."))
        self.compat_group.set_title(tr("Vulkan pipeline"))
        self.compat_group.set_description(tr("Vulkan pipeline options and runtime overrides."))
        self.perf_group.set_title(tr("Frame pacing"))
        self.perf_group.set_description(tr("Frame pacing, diagnostics and shader warm-up."))
        self.game_group.set_title(tr("Game folder"))
        self.game_group.set_description(tr("Game folder, save data and game language."))
        self.mods_group.set_title(tr("Mods"))
        self.patches_group.set_title(tr("Patches"))
        self.enhancements_group.set_title(tr("Enhancements"))
        self.cheats_group.set_title(tr("Cheats and tweaks"))
        self.prompt_group.set_title(tr("Controller and prompts"))
        if hasattr(self, "fsr_group"):
            self.fsr_group.set_title(tr("FSR assets"))

        self.readiness_rows = {}
        self.readiness_icons = {}
        self.readiness_group = Adw.PreferencesGroup(
            title=tr("Compatibility status"),
            description=tr("Read-only checks of the selected game and save folders."))
        for key in ("Game files", "Trophies", "Saves"):
            self.readiness_group.add(self.make_readiness_row(key))

        pages = {
            "display": self.category_page(self.render_group),
            "graphics": self.category_page(self.quality_group),
            "upscaling": self.category_page(self.upscale_group),
            "performance": self.category_page(self.perf_group),
            "compatibility": self.category_page(self.compat_group, self.readiness_group),
            "controller": self.category_page(self.controls_group, *self.keybinding_groups,
                                             self.keybinding_reset_group, self.prompt_group),
            "game_data": self.category_page(self.game_group, self.mods_group, self.patches_group,
                                            self.enhancements_group, self.cheats_group),
            "launcher": self.build_launcher_page(integrations),
            "diagnostics": self.build_diagnostics_page(),
        }
        self.settings_category_pages = pages
        categories = [
            ("display", tr("Display"), "video-display-symbolic"),
            ("graphics", tr("Graphics"), "applications-graphics-symbolic"),
            ("upscaling", tr("Upscaling"), "image-x-generic-symbolic"),
            ("performance", tr("Performance"), "speedometer-symbolic"),
            ("compatibility", tr("Compatibility"), "preferences-system-symbolic"),
            ("controller", tr("Controller"), "input-gaming-symbolic"),
            ("game_data", tr("Game & Data"), "folder-open-symbolic"),
            ("launcher", tr("Launcher"), "applications-system-symbolic"),
            ("diagnostics", tr("Diagnostics"), "utilities-terminal-symbolic"),
        ]
        self.settings_category_values = [key for key, *_ in categories]
        self.settings_category_labels = {key: label for key, label, _ in categories}

        self.settings_view_stack = Gtk.Stack()
        self.settings_view_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.settings_view_stack.set_transition_duration(140)
        self.settings_view_stack.set_vexpand(True)
        self.settings_view_stack.set_hexpand(True)

        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        menu.add_css_class("ps5-settings-menu")
        menu.append(self.text_label(tr("Settings"), "ps5-settings-title"))
        self.settings_category_list = Gtk.ListBox()
        self.settings_category_list.add_css_class("ps5-settings-categories")
        self.settings_category_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.settings_category_list.connect("row-activated", self.on_settings_category_row)
        self.settings_category_rows = {}
        for key, label, icon_name in categories:
            row = Gtk.ListBoxRow()
            row.category = key
            row.add_css_class("ps5-settings-category")
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(22)
            icon.add_css_class("ps5-settings-icon")
            row_box.append(icon)
            row_box.append(self.text_label(label, "ps5-settings-label"))
            row.set_child(row_box)
            self.settings_category_rows[key] = row
            self.settings_category_list.append(row)
        menu.append(self.settings_category_list)
        menu_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        menu_scroller.add_css_class("ps5-scroll")
        menu_scroller.set_child(menu)
        self.settings_view_stack.add_named(menu_scroller, "menu")

        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        detail.add_css_class("ps5-settings-detail")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        head.add_css_class("ps5-settings-detail-head")
        back = Gtk.Button()
        back.add_css_class("ps5-back")
        back_child = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back_child.append(Gtk.Image.new_from_icon_name("go-previous-symbolic"))
        back_child.append(Gtk.Label(label=tr("Settings")))
        back.set_child(back_child)
        back.connect("clicked", lambda _b: self.show_settings_menu())
        head.append(back)
        self.settings_category_title = self.text_label("", "ps5-settings-category-title")
        head.append(self.settings_category_title)
        detail.append(head)

        self.settings_category_stack = Gtk.Stack()
        self.settings_category_stack.add_css_class("settings-stack")
        self.settings_category_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.settings_category_stack.set_transition_duration(140)
        self.settings_category_stack.set_vexpand(True)
        self.settings_category_stack.set_hexpand(True)
        for key, _label, _icon in categories:
            self.settings_category_stack.add_named(pages[key], key)
        detail.append(self.settings_category_stack)
        self.settings_save_status = self.text_label("", "ps5-save-status")
        detail.append(self.settings_save_status)
        self.settings_view_stack.add_named(detail, "category")

        self.settings_view_stack.set_visible_child_name("menu")
        self.refresh_readiness()
        self.wire_setting_saves()
        return self.settings_view_stack

    def on_settings_category_row(self, _listbox, row):
        if row is None or not hasattr(row, "category"):
            return
        self.show_settings_category(row.category)

    def select_settings_category(self, category):
        self.show_settings_category(category)

    def wire_setting_saves(self):
        """Persist every real control through the debounced saver."""
        controls = [
            getattr(self, name, None) for name in (
                "output_row", "hud_row", "live_row", "fullscreen_row", "present_row",
                "hdr_row", "upscaler_row", "preset_row", "motion_row", "sharpen_row",
                "sharpness_row", "lod_row", "pipe_row", "readbacks_row",
                "frames_ahead_row", "show_fps_row", "fps_row", "limit_row",
                "mangohud_row", "stats_row", "precompile_row", "discord_row",
                "profile_row", "validation_row", "extra_row", "language_row",
                "player_row", "mods_enabled_row", "control_scheme_row")
        ]
        controls += list(getattr(self, "effect_rows", {}).values())
        controls += list(getattr(self, "enhancement_rows", {}).values())
        controls += list(getattr(self, "cheat_rows", {}).values())
        for control in controls:
            if control is None:
                continue
            try:
                if isinstance(control, Adw.SwitchRow):
                    control.connect("notify::active", lambda *_: self.schedule_save())
                elif isinstance(control, Adw.SpinRow):
                    control.connect("notify::value", lambda *_: self.schedule_save())
                elif isinstance(control, Adw.EntryRow):
                    control.connect("notify::text", lambda *_: self.schedule_save())
                elif hasattr(control, "get_selected"):
                    control.connect("notify::selected", lambda *_: self.schedule_save())
            except TypeError:
                pass

    def build_keybinding_group(self, title, specs, with_note=False):
        group = Adw.PreferencesGroup(
            title=tr(title),
            description=tr("Rebind keyboard and mouse actions. Applies next launch.")
            if with_note else "")
        for action, label, _default_key, _default_mouse in specs:
            row = Adw.ActionRow(title=tr(label))
            row.set_subtitle(self.binding_display(action))
            change = Gtk.Button(label=tr("Change"))
            change.add_css_class("ps5-secondary-action")
            change.set_valign(Gtk.Align.CENTER)
            change.connect("clicked", lambda _b, a=action: self.open_key_capture(a))
            row.add_suffix(change)
            group.add(row)
            self.keybinding_rows[action] = row
        return group

    def build_keybinding_reset_group(self):
        group = Adw.PreferencesGroup(title=tr("Key bindings"))
        row = Adw.ActionRow(
            title=tr("Reset key bindings"),
            subtitle=tr("Restore the default keyboard and mouse bindings."))
        reset = Gtk.Button(label=tr("Reset"))
        reset.add_css_class("ps5-secondary-action")
        reset.set_valign(Gtk.Align.CENTER)
        reset.connect("clicked", self.on_reset_key_bindings)
        row.add_suffix(reset)
        group.add(row)
        return group

    def binding_parts(self, action):
        spec = KEY_BINDING_BY_ACTION.get(action)
        if spec is None:
            return "", ""
        return parse_key_binding(self.ini.get(f"key_{action}"), spec[2], spec[3])

    def binding_display(self, action):
        key, mouse = self.binding_parts(action)
        parts = [part for part in (key, mouse) if part]
        return " + ".join(parts) if parts else tr("Unbound")

    def refresh_keybinding_rows(self):
        for action, row in getattr(self, "keybinding_rows", {}).items():
            row.set_subtitle(self.binding_display(action))

    def save_key_binding(self, action, key, mouse):
        """Persist one binding, keeping one key and one mouse input per action."""
        for spec in KEY_BINDING_SPECS:
            other = spec[0]
            if other == action:
                continue
            other_key, other_mouse = self.binding_parts(other)
            changed = False
            if key and other_key.lower() == key.lower():
                other_key, changed = "", True
            if mouse and other_mouse.lower() == mouse.lower():
                other_mouse, changed = "", True
            if changed:
                self.ini[f"key_{other}"] = format_key_binding(other_key, other_mouse)
        self.ini[f"key_{action}"] = format_key_binding(key, mouse)
        try:
            save_ini(self.ini, self.ini_lines)
            self.ini, self.ini_lines = load_ini()
        except OSError as error:
            if hasattr(self, "toasts"):
                self.toasts.add_toast(Adw.Toast(
                    title=tr("Could not save key binding: {}").format(error)))
            return
        self.refresh_keybinding_rows()
        if hasattr(self, "toasts"):
            self.toasts.add_toast(
                Adw.Toast(title=tr("Binding saved. Takes effect next launch.")))

    def on_reset_key_bindings(self, _button=None):
        self.ini_lines = [line for line in self.ini_lines
                          if not line.strip().startswith("key_")]
        for name in [name for name in self.ini if name.startswith("key_")]:
            self.ini.pop(name, None)
        try:
            save_ini(self.ini, self.ini_lines)
            self.ini, self.ini_lines = load_ini()
        except OSError as error:
            if hasattr(self, "toasts"):
                self.toasts.add_toast(Adw.Toast(
                    title=tr("Could not save key binding: {}").format(error)))
            return
        self.refresh_keybinding_rows()
        if hasattr(self, "toasts"):
            self.toasts.add_toast(Adw.Toast(title=tr("Key bindings reset.")))

    def open_key_capture(self, action):
        spec = KEY_BINDING_BY_ACTION.get(action)
        if spec is None:
            return
        label = tr(spec[1])
        base_key, base_mouse = self.binding_parts(action)

        dialog = Adw.Window()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_title(tr("Rebind {}").format(label))
        dialog.set_default_size(480, 248)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title=tr("Rebind {}").format(label)))
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.set_margin_top(18)
        body.set_margin_bottom(18)
        body.set_margin_start(22)
        body.set_margin_end(22)
        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area.add_css_class("ps5-rebind-area")
        area.set_size_request(-1, 96)
        area.set_focusable(True)
        area.append(self.text_label(tr("Press a key, mouse button or wheel"),
                                    "ps5-rebind-hint"))
        current_label = self.text_label(self.binding_display(action), "ps5-rebind-value")
        area.append(current_label)
        body.append(area)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)

        def finish(key, mouse):
            dialog.close()
            self.save_key_binding(action, key, mouse)

        reset = Gtk.Button(label=tr("Reset to default"))
        reset.connect("clicked", lambda _b: finish(spec[2], spec[3]))
        clear = Gtk.Button(label=tr("Clear"))
        clear.connect("clicked", lambda _b: finish("", ""))
        cancel = Gtk.Button(label=tr("Cancel"))
        cancel.connect("clicked", lambda _b: dialog.close())
        buttons.append(reset)
        buttons.append(clear)
        buttons.append(cancel)
        body.append(buttons)
        toolbar.set_content(body)
        dialog.set_content(toolbar)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        def on_key(_controller, keyval, _keycode, _state):
            name = sdl_key_name(keyval)
            if name is None:
                current_label.set_text(tr("Unsupported key"))
                return True
            finish(name, base_mouse)
            return True
        keys.connect("key-pressed", on_key)
        dialog.add_controller(keys)

        click = Gtk.GestureClick()
        click.set_button(0)
        def on_click(gesture, _n_press, _x, _y):
            mouse = {1: "Mouse1", 2: "Mouse2", 3: "Mouse3",
                     4: "Mouse4", 5: "Mouse5", 8: "Mouse4", 9: "Mouse5"}.get(
                         gesture.get_button())
            if mouse:
                finish(base_key, mouse)
        click.connect("pressed", on_click)
        area.add_controller(click)

        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.HORIZONTAL)
        def on_scroll(_controller, dx, dy):
            if dy < 0 or (dy == 0 and dx < 0):
                finish(base_key, "WheelUp")
            elif dy > 0 or dx > 0:
                finish(base_key, "WheelDown")
            return True
        scroll.connect("scroll", on_scroll)
        area.add_controller(scroll)

        dialog.present()

    def build_launcher_page(self, integrations):
        page = Adw.PreferencesPage()
        interface = Adw.PreferencesGroup(
            title=tr("Interface"),
            description=tr("Language and motion preferences for the launcher."))
        self.ui_language_row = combo_row(
            tr("Language"),
            tr("Applies to the launcher; the game language is set in Game & Data."),
            UI_LANGUAGES, self.settings.get("ui_language") or "en")
        self.ui_language_row.connect("notify::selected", self.on_ui_language)
        interface.add(self.ui_language_row)
        self.reduce_motion_row = Adw.SwitchRow(
            title=tr("Reduce motion"),
            subtitle=tr("Disable non-essential transitions and animations."),
            active=bool(self.settings.get("reduce_motion", False)))
        self.reduce_motion_row.connect("notify::active", self.on_reduce_motion)
        interface.add(self.reduce_motion_row)
        page.add(interface)
        page.add(integrations)

        storage = Adw.PreferencesGroup(title=tr("Storage and version"))
        cfg_row = Adw.ActionRow(title=tr("Configuration directory"), subtitle=str(CONFIG_DIR))
        cfg_row.set_subtitle_lines(1)
        cfg_row.add_suffix(flat_button("folder-open-symbolic", tr("Open Folder"),
                                       lambda _b: open_folder(self, CONFIG_DIR)))
        storage.add(cfg_row)
        log_row = Adw.ActionRow(title=tr("Launcher log"), subtitle=str(log_path()))
        log_row.set_subtitle_lines(1)
        log_row.add_suffix(flat_button("folder-open-symbolic", tr("Open Folder"),
                                       lambda _b: self.on_open_log_file(None)))
        storage.add(log_row)
        storage.add(Adw.ActionRow(title=tr("Version"), subtitle=VERSION))
        storage.add(Adw.ActionRow(title=tr("Build"), subtitle="linux-x86_64"))
        page.add(storage)

        about = Adw.PreferencesGroup(title=tr("About"),
                                     description=tr("A community-driven native PC port."))
        for title, uri in ((tr("Project repository"), REPO_URL),
                           (tr("Report an issue"), ISSUES_URL),
                           (tr("License"), (PORT_DIR / "LICENSE").as_uri())):
            row = Adw.ActionRow(title=title)
            link = Gtk.LinkButton(uri=uri, label=tr("Open"))
            link.set_valign(Gtk.Align.CENTER)
            row.add_suffix(link)
            about.add(row)
        page.add(about)
        expand_preferences_page(page, max_size=1040, tightening_threshold=860)
        return page

    def build_diagnostics_page(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.add_css_class("page-content")

        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        toolbar.add_css_class("diagnostics-toolbar")
        filters = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.log_search_entry = Gtk.SearchEntry()
        self.log_search_entry.set_placeholder_text(tr("Search in log…"))
        self.log_search_entry.set_hexpand(True)
        self.log_search_entry.connect("search-changed", self.on_log_search)
        filters.append(self.log_search_entry)
        filters.append(self.text_label(tr("Level"), "dim-label"))
        self.log_level_drop = Gtk.DropDown.new_from_strings(
            [tr("All"), "INFO", "WARNING", "ERROR", "DEBUG"])
        self.log_level_drop.connect("notify::selected", lambda *_: self.refresh_log_view())
        filters.append(self.log_level_drop)
        toolbar.append(filters)

        toggles = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.log_timestamps = Gtk.Switch(active=True)
        self.log_timestamps.connect("notify::active", lambda *_: self.refresh_log_view())
        toggles.append(self.text_label(tr("Timestamps"), "dim-label"))
        toggles.append(self.log_timestamps)
        self.log_autoscroll = Gtk.Switch(active=True)
        toggles.append(self.text_label(tr("Auto-scroll"), "dim-label"))
        toggles.append(self.log_autoscroll)
        toggles.append(self.text_label(tr("Runtime output from the game and renderer."),
                                       "dim-label"))
        toolbar.append(toggles)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.START)
        for label, callback in ((tr("Copy"), self.on_copy_log),
                                (tr("Copy selected"), self.on_copy_selected),
                                (tr("Clear"), self.on_clear_log),
                                (tr("Save…"), self.on_save_log),
                                (tr("Open log"), self.on_open_log_file)):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            actions.append(button)
        toolbar.append(actions)
        content.append(toolbar)

        self.log_view = Gtk.TextView(editable=False, monospace=True, cursor_visible=True,
                                     wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_top_margin(10)
        self.log_view.set_left_margin(12)
        self.log_view.set_right_margin(12)
        self.log_view.set_bottom_margin(10)
        self.log_view.set_pixels_above_lines(1)
        self.log_view.set_pixels_below_lines(1)
        self.log_view.add_css_class("log-terminal-view")
        self.log_view.get_buffer().create_tag("log-info", foreground="#c6c0b5")
        self.log_view.get_buffer().create_tag("log-warning", foreground="#c3a877")
        self.log_view.get_buffer().create_tag("log-error", foreground="#c47a7a")
        self.log_view.get_buffer().create_tag("log-debug", foreground="#8f897e")
        self.log_view.get_buffer().connect("notify::cursor-position", self.on_log_cursor)
        self.log_scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.log_scroller.add_css_class("log-terminal-frame")
        self.log_scroller.set_child(self.log_view)
        content.append(self.log_scroller)

        detail = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        detail.add_css_class("log-detail")
        self.log_detail_time = self.text_label("—", "log-detail-value")
        self.log_detail_level = self.text_label("—", "log-detail-value")
        self.log_detail_text = self.text_label("", "log-detail-value", wrap=True)
        self.log_detail_text.set_hexpand(True)
        detail.append(self.text_label(tr("Selected line"), "log-detail-label"))
        detail.append(self.log_detail_time)
        detail.append(self.log_detail_level)
        detail.append(self.log_detail_text)
        content.append(detail)
        return content

    def on_reduce_motion(self, row, _param):
        self.set_reduce_motion(row.get_active())
        self.schedule_save()

    def set_reduce_motion(self, reduce):
        self.settings["reduce_motion"] = bool(reduce)
        if reduce:
            self.add_css_class("reduce-motion")
        else:
            self.remove_css_class("reduce-motion")
        try:
            gtk_settings = Gtk.Settings.get_default()
            if gtk_settings is not None:
                gtk_settings.set_property("gtk-enable-animations", not reduce)
        except Exception:
            pass

    def schedule_save(self):
        if getattr(self, "_save_source", None):
            try:
                GLib.source_remove(self._save_source)
            except Exception:
                pass
        self._save_source = GLib.timeout_add(250, self.save_now)
        if hasattr(self, "settings_save_status"):
            self.settings_save_status.set_text(tr("Saving…"))
            self.settings_save_status.remove_css_class("error")

    def save_now(self):
        self._save_source = None
        try:
            self.store()
        except Exception as error:
            if hasattr(self, "settings_save_status"):
                self.settings_save_status.set_text(tr("Save failed"))
                self.settings_save_status.add_css_class("error")
            if hasattr(self, "toasts"):
                self.toasts.add_toast(Adw.Toast(
                    title=tr("Could not save settings: {}").format(error)))
            return False
        if hasattr(self, "settings_save_status"):
            self.settings_save_status.set_text(tr("Saved"))
            self.settings_save_status.remove_css_class("error")
        return False

    def refresh_readiness(self):
        if not hasattr(self, "readiness_rows"):
            return
        try:
            rows = check_readiness(self.settings.get("game_dir") or None, self.user_dir(), game_info)
        except (OSError, ValueError, TypeError):
            rows = []
        by_label = {item.get("label"): item for item in rows if isinstance(item, dict)}
        for label, row in self.readiness_rows.items():
            item = by_label.get(label)
            if item is None:
                row.set_subtitle(tr("Not checked"))
                continue
            level = item.get("level", "warning")
            icon_name = "object-select-symbolic" if level == "ready" else (
                "dialog-error-symbolic" if level == "error" else "dialog-warning-symbolic")
            icon = getattr(self, "readiness_icons", {}).get(label)
            if icon is not None:
                icon.set_from_icon_name(icon_name)
            row.set_subtitle(item.get("detail", ""))

    # --- Settings control groups ---------------------------------------------------------

    def build_graphics_page(self):
        page = Adw.PreferencesPage()

        # 1. Rendering and Resolution
        self.render_group = screen = Adw.PreferencesGroup(
            title=tr("1. Рендеринг и разрешение"),
            description=tr("Разрешение вывода, режим отображения и синхронизация кадров"))
        self.output_row = combo_row(tr("Разрешение вывода"),
                                    tr("Апскейлер дорисовывает кадр; Steam Deck — 720p"),
                                    OUTPUT_RES, self.ini.get("output_res", "1920x1080"))
        screen.add(self.output_row)
        self.hud_row = combo_row(
            tr("Позиция HUD"),
            tr("Ультраширокие экраны: элементы у краёв или в центре 16:9"),
            HUD_POSITIONS, self.ini.get("hud_position", "100"))
        screen.add(self.hud_row)
        self.live_row = combo_row(tr("Смена разрешения на лету"),
                                  tr("Без перезапуска, но медленнее на Steam Deck и старых GPU"),
                                  LIVE_RESOLUTION, self.ini.get("live_resolution", "0"))
        screen.add(self.live_row)
        self.fullscreen_row = Adw.SwitchRow(title=tr("Полноэкранный режим"),
                                            subtitle=tr("Применяется сразу"),
                                            active=self.settings["fullscreen"])
        screen.add(self.fullscreen_row)
        self.present_row = combo_row(tr("Режим показа кадров"), None, PRESENT_MODES,
                                     self.settings["present_mode"])
        screen.add(self.present_row)
        self.hdr_row = Adw.SwitchRow(title=tr("Разрешить HDR"),
                                     subtitle=tr("Требуется поддержка HDR на дисплее"),
                                     active=self.settings["hdr"])
        screen.add(self.hdr_row)
        page.add(screen)

        # 2. Upscaling and Temporal Reconstruction
        self.upscale_group = upscaler = Adw.PreferencesGroup(
            title=tr("2. Апскейлинг и реконструкция"),
            description=tr("Реконструкция изображения из пониженного разрешения рендеринга"))
        self.upscaler_row = combo_row(tr("Апскейлер"), None, UPSCALERS, self.ini["upscaler"])
        self.upscaler_row.connect("notify::selected", lambda *_: self.update_upscaler_status())
        upscaler.add(self.upscaler_row)

        self.fsr4_warning_row = Adw.ActionRow(
            title=tr("Предупреждение: FSR 4 на RX 6600M (RDNA 2)"),
            subtitle=tr("Experimental on this GPU. AMD Radeon RX 6600M is RDNA 2. FSR 4 may run significantly slower or less reliably than FSR 3.1. Performance is not guaranteed. If you experience frame drops, stuttering, or instability, switch to FSR 3.1."))
        warn_img = Gtk.Image()
        warn_img.set_from_icon_name("dialog-warning-symbolic")
        self.fsr4_warning_row.add_prefix(warn_img)
        self.fsr4_compat_warning_label = self.fsr4_warning_row
        upscaler.add(self.fsr4_warning_row)

        self.preset_row = combo_row(tr("Пресет"), None, PRESETS,
                                    ini_int(self.ini, "preset", int(INI_DEFAULTS["preset"])))
        self.preset_row.connect("notify::selected", lambda *_: self.update_upscaler_status())
        self.output_row.connect("notify::selected", lambda *_: self.update_upscaler_status())
        upscaler.add(self.preset_row)

        self.fsr4_row = Adw.ActionRow(title=tr("Ассеты FSR 4"))
        self.fsr4_progress = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
        self.fsr4_progress.set_margin_start(12)
        self.fsr4_progress.set_margin_end(12)
        self.fsr4_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.fsr4_button.connect("clicked", self.on_fetch_fsr4)
        self.fsr4_row.add_suffix(self.fsr4_progress)
        self.fsr4_row.add_suffix(self.fsr4_button)
        self.fsr4_row.add_suffix(flat_button(
            "system-file-manager-symbolic", tr("Открыть в файловом менеджере"),
            lambda _button: open_folder(self, PORT_DIR / "fsr4_shaders")))
        upscaler.add(self.fsr4_row)

        self.motion_row = Adw.SwitchRow(
            title=tr("Векторы движения объектов"),
            subtitle=tr("ВНИМАНИЕ: На AMD RX 6000 (RDNA 2) возможен сбой видеочипа (device loss). Оставьте выключенным."),
            active=self.ini.get("object_motion") == "1")
        upscaler.add(self.motion_row)
        page.add(upscaler)

        # 3. Image Quality and Sharpening
        self.quality_group = quality = Adw.PreferencesGroup(
            title=tr("3. Качество изображения и резкость"),
            description=tr("Повышение четкости и графические эффекты рендеринга"))
        self.sharpen_row = Adw.SwitchRow(title=tr("Резкость (RCAS) [Применяется сразу]"),
                                         subtitle=tr("AMD FidelityFX Robust Contrast Adaptive Sharpening; применяется сразу"),
                                         active=self.ini.get("sharpen") == "1")
        quality.add(self.sharpen_row)
        self.sharpness_row = Adw.SpinRow.new_with_range(0.0, 2.0, 0.05)
        self.sharpness_row.set_title(tr("Сила резкости [Применяется сразу]"))
        self.sharpness_row.set_subtitle(tr("Коэффициент 0.0–2.0 (по умолчанию 0.50); применяется сразу"))
        self.sharpness_row.set_digits(2)
        self.sharpness_row.set_value(max(0.0, min(2.0, ini_float(
            self.ini, "sharpness", float(INI_DEFAULTS["sharpness"])))))
        quality.add(self.sharpness_row)

        self.lod_row = combo_row(tr("Детализация моделей"), None, MODEL_LOD,
                                 self.ini.get("model_lod", "0"))
        quality.add(self.lod_row)
        self.effect_rows = {}
        for key, title, default in EFFECTS:
            row = Adw.SwitchRow(title=tr(title),
                                active=self.ini.get(key, "1" if default else "0") == "1")
            if key == "debug_menu":
                row.set_subtitle(tr("Установите DbgFont14h.ccm и DbgFont14h.tpf в dvdroot_ps4/font "
                                    "из мода Nexus #253"))
            self.effect_rows[key] = row
            quality.add(row)
        page.add(quality)

        # 4. Compatibility and GPU Pipeline
        self.compat_group = compat = Adw.PreferencesGroup(
            title=tr("4. Совместимость и конвейер GPU"),
            description=tr("Низкоуровневые параметры Vulkan; при нестабильности выключите"))
        self.pipe_row = combo_row(
            tr("Двухстадийный конвейер GPU"),
            tr("Быстрее на 20–30%; при нестабильности выключите"), DRAW_PIPE,
            self.settings["draw_pipe"])
        compat.add(self.pipe_row)
        self.readbacks_row = combo_row(tr("Чтение данных GPU процессором"), None, READBACKS,
                                       self.settings["readbacks"])
        compat.add(self.readbacks_row)
        self.frames_ahead_row = Adw.SpinRow.new_with_range(0, 8, 1)
        self.frames_ahead_row.set_title(tr("Кадров вперёд (конвейер GPU)"))
        self.frames_ahead_row.set_subtitle(tr(
            "На сколько кадров поток команд может опережать GPU: 1 — по умолчанию "
            "(стабильно), 0 — без ограничения, 2 и больше — больше перекрытия CPU/GPU "
            "ценой задержки"))
        self.frames_ahead_row.set_value(self.settings["frames_ahead"])
        compat.add(self.frames_ahead_row)
        page.add(compat)

        # 5. Performance Diagnostics
        self.perf_group = perf = Adw.PreferencesGroup(
            title=tr("5. Производительность и диагностика"),
            description=tr("Ограничение частоты кадров и сбор телеметрии"))
        self.show_fps_row = Adw.SwitchRow(title=tr("Показывать FPS [Применяется сразу]"),
                                          subtitle=tr("Встроенный счетчик кадров в левом верхнем углу"),
                                          active=self.ini.get("show_fps") == "1")
        perf.add(self.show_fps_row)
        self.fps_row = combo_row(tr("Режим"), tr("Какой патч частоты кадров применить к игре"),
                                 FPS_MODES, self.settings["fps_mode"])
        perf.add(self.fps_row)
        self.limit_row = Adw.SpinRow.new_with_range(0, 480, 1)
        self.limit_row.set_title(tr("Ограничение FPS"))
        self.limit_row.set_subtitle(tr("0 — по частоте экрана (не выше 120 Гц); "
                                       "укажите число, чтобы ограничить иначе"))
        self.limit_row.set_value(self.settings["fps_limit"])
        perf.add(self.limit_row)

        self.mangohud_row = Adw.SwitchRow(title="MangoHud", active=self.settings["mangohud"])
        perf.add(self.mangohud_row)
        self.stats_row = Adw.SwitchRow(title=tr("Статистика кадров в журнале"),
                                       subtitle="BB_FRAME_STATS",
                                       active=self.settings["frame_stats"])
        perf.add(self.stats_row)
        self.precompile_row = Adw.SwitchRow(
            title=tr("Предварительно компилировать шейдеры"),
            subtitle=tr("Собирать известные шейдеры при запуске (меньше подтормаживаний)"),
            active=self.settings.get("precompile_shaders", True))
        perf.add(self.precompile_row)
        self.precompile_build_row = Adw.ActionRow(
            title=tr("Скомпилировать шейдеры сейчас"),
            subtitle=tr("Короткий запуск игры для прогрева кэша; окно игры откроется ненадолго"))
        self.precompile_button = Gtk.Button(label=tr("Скомпилировать"), valign=Gtk.Align.CENTER)
        self.precompile_button.connect("clicked", self.on_precompile_shaders)
        self.precompile_build_row.add_suffix(self.precompile_button)
        perf.add(self.precompile_build_row)
        self.discord_row = Adw.SwitchRow(
            title="Discord Rich Presence",
            subtitle=tr("Показывать область, босса и прогресс в Discord"),
            active=self.settings.get("discord_rpc", True))
        perf.add(self.discord_row)
        self.profile_row = Adw.SwitchRow(title=tr("Профиль GPU в журнале"),
                                         subtitle="BB_GPU_PROFILE",
                                         active=self.settings["gpu_profile"])
        perf.add(self.profile_row)
        self.validation_row = Adw.SwitchRow(title=tr("Слои валидации Vulkan"),
                                            subtitle=tr("Сильно замедляет"),
                                            active=self.settings["vk_validation"])
        perf.add(self.validation_row)
        self.extra_row = Adw.EntryRow(title=tr("Доп. переменные (ИМЯ=значение через пробел)"),
                                      text=self.settings["extra_env"])
        perf.add(self.extra_row)
        page.add(perf)
        expand_preferences_page(page, max_size=1150)
        return page

    def build_game_page(self):
        page = Adw.PreferencesPage()

        game = Adw.PreferencesGroup(title=tr("Игра"))
        self.game_group = game
        self.game_row = Adw.ActionRow(title=tr("Папка игры (CUSA03173)"))
        self.game_row.set_subtitle_lines(1)
        self.game_status = Gtk.Image()
        self.game_row.add_suffix(self.game_status)
        self.game_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку с eboot.bin"),
                                             self.on_choose_game))
        self.game_row.add_suffix(flat_button("system-file-manager-symbolic",
                                             tr("Открыть в файловом менеджере"),
                                             lambda _b: open_folder(self, self.game_dir())))
        game.add(self.game_row)

        # Saves folder
        self.user_row = Adw.ActionRow(title=tr("Папка сохранений"))
        self.user_row.set_subtitle_lines(1)
        self.user_status = Gtk.Image()
        self.user_row.add_suffix(self.user_status)
        self.user_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку сохранений"),
                                             self.on_choose_user))
        self.user_row.add_suffix(flat_button("system-file-manager-symbolic",
                                             tr("Открыть в файловом менеджере"),
                                             lambda _b: open_folder(self, self.user_dir())))
        self.user_reset = flat_button("edit-undo-symbolic", tr("Вернуть папку по умолчанию"),
                                      self.on_reset_user)
        self.user_row.add_suffix(self.user_reset)
        game.add(self.user_row)

        self.trophy_row = Adw.ActionRow(title=tr("Ключи трофеев"))
        self.trophy_row.add_suffix(flat_button("document-open-symbolic", tr("Импорт keys.json"),
                                               self.on_import_trophy_keys))
        game.add(self.trophy_row)
        self.refresh_trophy_status()

        self.player_row = Adw.EntryRow(title=tr("Имя охотника"),
                                       text=self.settings.get("player_name", ""))
        if hasattr(self.player_row, "set_subtitle"):
            self.player_row.set_subtitle("BB_USER_NAME")
        else:
            hint = Gtk.Label(label="BB_USER_NAME")
            hint.add_css_class("dim-label")
            self.player_row.add_suffix(hint)
        game.add(self.player_row)

        self.dlc_row = Adw.ActionRow(title=tr("Папка DLC"))
        self.dlc_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку DLC"),
                                            self.on_choose_dlc))
        self.dlc_row.add_suffix(flat_button("system-file-manager-symbolic", tr("Открыть папку DLC"),
                                            lambda _b: open_folder(self, self.dlc_dir())))
        self.dlc_reset = flat_button("edit-undo-symbolic", tr("Вернуть папку DLC по умолчанию"),
                                     self.on_reset_dlc)
        self.dlc_row.add_suffix(self.dlc_reset)
        game.add(self.dlc_row)

        self.language_row = combo_row(tr("Язык системы"), None, LANGUAGES, self.settings["language"])
        game.add(self.language_row)
        page.add(game)

        controls = Adw.PreferencesGroup(
            title=tr("Управление"),
            description=tr("Отображение кнопок и раскладка в игре"))
        self.controls_group = controls
        self.control_scheme_row = combo_row(
            tr("Схема управления"), None, CONTROL_SCHEMES,
            self.current_control_scheme())
        self.control_scheme_row.connect("notify::selected", self.on_control_scheme_changed)
        controls.add(self.control_scheme_row)
        page.add(controls)

        self.mods_group = Adw.PreferencesGroup(
            title=tr("Моды"), description=tr(
                "Распакуйте каждый мод в отдельную папку (с dvdroot_ps4 или сразу с chr/, parts/ и т. п.). "
                "При совпадении файлов побеждает мод ниже в списке. Применяется при запуске."))
        self.mods_enabled_row = Adw.SwitchRow(title=tr("Загружать моды"),
                                               active=self.settings["mods_enabled"])
        self.mods_group.add(self.mods_enabled_row)
        self.mods_folder_row = Adw.ActionRow(title=tr("Папка модов"))
        self.mods_folder_row.set_subtitle_lines(1)
        self.mods_folder_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку модов"),
                                                    self.on_choose_mods))
        self.mods_folder_row.add_suffix(flat_button("system-file-manager-symbolic", tr("Открыть папку модов"),
                                                    lambda _b: open_folder(self, self.mods_dir())))
        self.mods_folder_row.add_suffix(flat_button("view-refresh-symbolic", tr("Обновить список"),
                                                    self.on_refresh_mods))
        self.mods_group.add(self.mods_folder_row)
        self.mod_list = FolderList(self.mods_group)
        self.refresh_mods()
        page.add(self.mods_group)

        self.patches_group = Adw.PreferencesGroup(
            title=tr("Сторонние патчи"),
            description=tr("XML-патчи в формате shadPS4 для версии 01.09 из папки патчей. "
                           "Применяются при запуске."))
        self.patches_folder_row = Adw.ActionRow(title=tr("Папка патчей"))
        self.patches_folder_row.set_subtitle_lines(1)
        self.patches_folder_row.add_suffix(flat_button("folder-open-symbolic", tr("Выбрать папку патчей"),
                                                       self.on_choose_patches))
        self.patches_folder_row.add_suffix(flat_button(
            "system-file-manager-symbolic", tr("Открыть папку патчей"),
            lambda _b: open_folder(self, patches_dir(self.settings))))
        self.patches_folder_row.add_suffix(flat_button("view-refresh-symbolic", tr("Обновить список"),
                                                       self.on_refresh_patches))
        self.patches_group.add(self.patches_folder_row)
        self.patch_list = FolderList(self.patches_group)
        self.refresh_patches()
        page.add(self.patches_group)

        enhancements = Adw.PreferencesGroup(
            title=tr("Улучшения (PC)"),
            description=tr("Игровые файлы создаются при запуске; выключено — игра как в оригинале"))
        self.enhancements_group = enhancements
        self.enhancement_rows = {}
        for key, title, default in ENHANCEMENTS:
            row = Adw.SwitchRow(title=tr(title),
                                active=self.ini.get(key, "1" if default else "0") == "1")
            self.enhancement_rows[key] = row
            enhancements.add(row)
        page.add(enhancements)

        cheats = Adw.PreferencesGroup(
            title=tr("Читы и твики"),
            description=tr("Патчи игры 1.09: сложность, физика и камера"))
        self.cheats_group = cheats
        self.cheat_rows = {}
        for key, title, default in CHEATS_AND_TWEAKS:
            row = Adw.SwitchRow(title=tr(title),
                                active=self.ini.get(key, "1" if default else "0") == "1")
            self.cheat_rows[key] = row
            cheats.add(row)
        page.add(cheats)

        return page

    def build_downloads_page(self):
        page = Adw.PreferencesPage()

        # FSR 4 Shaders Group
        fsr_group = Adw.PreferencesGroup(
            title=tr("Ассеты FSR 4"),
            description=tr("FSR 4 assets"))
        self.fsr_group = fsr_group

        row_fsr = Adw.ActionRow(title=tr("Ассеты FSR 4"))
        total = len(fsr4_files())
        missing = len(fsr4_missing())
        if missing == 0:
            row_fsr.set_subtitle(tr("Установлены: {} файлов в fsr4_shaders").format(total))
        else:
            row_fsr.set_subtitle(tr("Отсутствует {} из {} файлов в fsr4_shaders").format(missing, total))

        btn_fetch = Gtk.Button(valign=Gtk.Align.CENTER)
        btn_fetch.set_label(tr("Проверить") if missing == 0 else tr("Скачать ассеты"))
        btn_fetch.connect("clicked", self.on_fetch_fsr4)
        row_fsr.add_suffix(btn_fetch)
        row_fsr.add_suffix(flat_button("system-file-manager-symbolic", tr("Открыть в файловом менеджере"),
                                       lambda _: open_folder(self, PORT_DIR / "fsr4_shaders")))
        fsr_group.add(row_fsr)
        page.add(fsr_group)

        # Prompts Group
        prompt_group = Adw.PreferencesGroup(
            title=tr("Отображение кнопок и раскладка в игре"))
        self.prompt_group = prompt_group

        row_kb = Adw.ActionRow(title=tr("ПК — клавиатура и мышь"))
        kb_bundled = bundled_keyboard_prompts(PORT_DIR) is not None
        row_kb.set_subtitle(tr("Ассеты найдены") if kb_bundled else tr("Клавиатурные подсказки отсутствуют в дистрибутиве"))
        if kb_bundled:
            row_kb.add_suffix(flat_button("edit-undo-symbolic", tr("Вернуть папку по умолчанию"),
                                          lambda _: install_keyboard_prompts(self.mods_dir(), PORT_DIR)))
        prompt_group.add(row_kb)

        row_xbox = Adw.ActionRow(title=tr("Геймпад Xbox"))
        xbox_mods = [p.name for p in self.mods_dir().iterdir() if p.is_dir() and is_xbox_prompt(p.name)] if self.mods_dir().is_dir() else []
        row_xbox.set_subtitle(tr("Ассеты найдены") if xbox_mods else tr("Подсказки Xbox отсутствуют в папке модов"))
        prompt_group.add(row_xbox)

        page.add(prompt_group)

        # Game Files Integrity Group
        game_group = Adw.PreferencesGroup(
            title=tr("Папка игры (CUSA03173)"))

        row_eboot = Adw.ActionRow(title="eboot.bin")
        eboot_ok = bool(self.settings.get("game_dir")) and (self.game_dir() / "eboot.bin").is_file()
        row_eboot.set_subtitle(tr("Найден eboot.bin") if eboot_ok else tr("Нет eboot.bin в папке"))
        img_e = Gtk.Image()
        img_e.set_from_icon_name("object-select-symbolic" if eboot_ok else "dialog-warning-symbolic")
        row_eboot.add_prefix(img_e)
        game_group.add(row_eboot)

        row_dvd = Adw.ActionRow(title="dvdroot_ps4")
        dvd_ok = bool(self.settings.get("game_dir")) and (self.game_dir() / "dvdroot_ps4").is_dir()
        row_dvd.set_subtitle(tr("Ассеты найдены") if dvd_ok else tr("Нет eboot.bin в папке"))
        img_d = Gtk.Image()
        img_d.set_from_icon_name("object-select-symbolic" if dvd_ok else "dialog-warning-symbolic")
        row_dvd.add_prefix(img_d)
        game_group.add(row_dvd)

        page.add(game_group)
        expand_preferences_page(page, max_size=1150)
        return page

    # --- Settings control groups ---

    def log_level_for(self, text):
        low = text.lower()
        if any(word in low for word in ("error", "fatal", "failed", "failure",
                                        "exception", "signal")):
            return "ERROR"
        if "warn" in low:
            return "WARNING"
        if "debug" in low:
            return "DEBUG"
        return "INFO"

    def log_filter_level(self):
        if not hasattr(self, "log_level_drop"):
            return "All"
        index = self.log_level_drop.get_selected()
        return ("All", "INFO", "WARNING", "ERROR", "DEBUG")[index] if index < 5 else "All"

    def log_entry_matches(self, entry):
        wanted = self.log_filter_level()
        return wanted == "All" or entry["level"] == wanted

    def insert_log_entry(self, entry):
        buffer = self.log_view.get_buffer()
        stamp = f"[{entry['time']}] " if (hasattr(self, "log_timestamps")
                                           and self.log_timestamps.get_active()) else ""
        buffer.insert_with_tags_by_name(
            buffer.get_end_iter(), stamp + entry["text"] + "\n", f"log-{entry['level'].lower()}")

    def refresh_log_view(self):
        if not hasattr(self, "log_view"):
            return
        buffer = self.log_view.get_buffer()
        buffer.set_text("")
        visible = 0
        for entry in self.log_entries:
            if self.log_entry_matches(entry):
                self.insert_log_entry(entry)
                visible += 1
        if not self.log_entries:
            buffer.set_text(tr("No runtime output yet. Launch the game to see live output."))
        elif not visible:
            buffer.set_text(tr("No log lines match this filter."))
        if hasattr(self, "log_autoscroll") and self.log_autoscroll.get_active():
            if hasattr(self, "log_scroller"):
                adjustment = self.log_scroller.get_vadjustment()
                GLib.idle_add(lambda: adjustment.set_value(adjustment.get_upper()) and False)

    def on_log_search(self, entry):
        text = entry.get_text()
        if not text:
            return
        buffer = self.log_view.get_buffer()
        start = buffer.get_start_iter()
        match = start.forward_search(text, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
        if match:
            buffer.select_range(match[0], match[1])
            self.log_view.scroll_to_iter(match[0], 0.1, False, 0.0, 0.0)

    def on_log_cursor(self, buffer, _param):
        if not hasattr(self, "log_detail_text"):
            return
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        start = cursor.copy()
        start.set_line_offset(0)
        end = cursor.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        line = buffer.get_text(start, end, False)
        self.log_detail_text.set_text(line)
        match = re.match(r"\[(\d\d:\d\d:\d\d)\]\s*(.*)", line)
        self.log_detail_time.set_text(match.group(1) if match else "—")
        self.log_detail_level.set_text(self.log_level_for(match.group(2) if match else line))

    def on_clear_log(self, _button):
        self.log_entries = []
        self.log_view.get_buffer().set_text("")
        try:
            log_path().write_text("", encoding="utf-8")
        except OSError:
            pass

    def on_copy_log(self, _button):
        buffer = self.log_view.get_buffer()
        text = buffer.get_text(*buffer.get_bounds(), False)
        display = Gdk.Display.get_default()
        if display and hasattr(display, "get_clipboard"):
            display.get_clipboard().set(text)

    def on_copy_selected(self, _button):
        buffer = self.log_view.get_buffer()
        sel = buffer.get_selection_bounds()
        if sel:
            text = buffer.get_text(sel[0], sel[1], False)
            display = Gdk.Display.get_default()
            if display and hasattr(display, "get_clipboard"):
                display.get_clipboard().set(text)

    def on_save_log(self, _button):
        buffer = self.log_view.get_buffer()
        text = buffer.get_text(*buffer.get_bounds(), False)
        dialog = Gtk.FileDialog(title=tr("Save log"))

        def finish(d, result):
            try:
                gfile = d.save_finish(result)
            except GLib.Error:
                return
            if gfile:
                try:
                    Path(gfile.get_path()).write_text(text, encoding="utf-8")
                except OSError as error:
                    self.toasts.add_toast(Adw.Toast(
                        title=tr("Could not save log: {}").format(error)))

        dialog.save(self, None, finish)

    def on_open_log_file(self, _button):
        path = log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(self, None, None)
        except (OSError, GLib.Error):
            open_folder(self, path.parent)

    def append_log(self, text):
        entries = []
        for line in str(text).splitlines():
            if not line:
                continue
            entries.append({"time": datetime.now().strftime("%H:%M:%S"),
                            "level": self.log_level_for(line), "text": line})
            try:
                path = log_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except OSError:
                pass
        if not entries:
            return
        self.log_entries.extend(entries)
        trimmed = len(self.log_entries) > MAX_LOG_LINES
        if trimmed:
            self.log_entries = self.log_entries[-MAX_LOG_LINES:]
            self.refresh_log_view()
        else:
            for entry in entries:
                if self.log_entry_matches(entry):
                    self.insert_log_entry(entry)
        if hasattr(self, "log_autoscroll") and self.log_autoscroll.get_active():
            if hasattr(self, "log_scroller"):
                adjustment = self.log_scroller.get_vadjustment()
                GLib.idle_add(lambda: adjustment.set_value(adjustment.get_upper()) and False)

    # --- State updates -------------------------------------------------------------------

    def update_playtime_summary(self):
        if not hasattr(self, "hero_playtime_summary"):
            return
        seconds = load_playtime(activity_path())
        if self.session_started_at is not None:
            seconds += max(0, int(time.time() - self.session_started_at))
        self.hero_playtime_summary.set_text(
            format_playtime(seconds) if seconds else tr("No play time yet"))

    def update_recent_activity(self):
        if not hasattr(self, "activity_list"):
            return
        self.clear_box(self.activity_list)
        try:
            events = [event for event in load_events(activity_path(), 50)
                      if event["kind"] in GAME_ACTIVITY_KINDS][:5]
        except (OSError, ValueError, TypeError):
            events = []
        if not events:
            self.activity_list.append(
                self.text_label(tr("No game activity yet."), "activity-empty"))
            return
        for event in events:
            self.activity_list.append(self.activity_row(event))

    def record_activity(self, kind, text):
        try:
            record_event(activity_path(), kind, text)
        except OSError:
            return
        self.update_recent_activity()

    def _record_new_trophies(self, report):
        earned_ids = {entry.id for entry in report.entries if entry.earned}
        previous = self._seen_trophy_ids
        self._seen_trophy_ids = earned_ids
        if previous is None:
            return
        for entry in report.entries:
            if entry.id in previous or entry.id not in earned_ids:
                continue
            if entry.name_available and entry.name:
                text = tr("Trophy unlocked: {}").format(entry.name)
            else:
                text = tr("Trophy #{} unlocked").format(entry.id)
            self.record_activity("trophy", text)

    def poll_trophy_activity(self):
        """Detect trophy unlocks while the game runs without rebuilding the page."""
        if not self.process_active():
            self._trophy_poll_source = None
            return False
        try:
            report = load_trophy_report(
                self.user_dir(), self.game_dir() if self.settings.get("game_dir") else None)
        except (OSError, ValueError, TypeError):
            return True
        self._record_new_trophies(report)
        self.update_playtime_summary()
        return True

    def launch_is_ready(self):
        return bool(self.settings.get("game_dir")) and (self.game_dir() / "eboot.bin").is_file()

    def update_launch_button(self):
        state = getattr(self, "launch_state", "idle")
        running = state == "running"
        starting = state == "starting"
        stopping = state == "stopping"
        ready = self.launch_is_ready()
        if starting:
            label = tr("Starting…")
        elif stopping:
            label = tr("Stopping…")
        elif running:
            label = tr("Stop")
        else:
            label = tr("Play")
        if hasattr(self, "hero_launch_button"):
            self.hero_launch_button.set_label(label)
            self.hero_launch_button.set_sensitive(ready or running or starting or stopping)
            self.hero_launch_button.remove_css_class("running")
            if running or stopping:
                self.hero_launch_button.add_css_class("running")
        if hasattr(self, "launch_button") and self.launch_button is not getattr(
                self, "hero_launch_button", None):
            self.launch_button.set_label(label)
            self.launch_button.set_sensitive(ready or running or starting or stopping)

        if hasattr(self, "hero_status_label"):
            if running:
                self.hero_status_label.set_text(tr("Game is running"))
                self.hero_status_detail.set_text(
                    f"PID {self.process.get_identifier()}" if self.process else "")
            elif starting:
                self.hero_status_label.set_text(tr("Starting the hunt…"))
                self.hero_status_detail.set_text(tr("Waiting for the renderer"))
            elif stopping:
                self.hero_status_label.set_text(tr("Stopping…"))
                self.hero_status_detail.set_text(tr("Waiting for the game to close"))
            elif state == "failed":
                self.hero_status_label.set_text(tr("Launch failed"))
                self.hero_status_detail.set_text(tr("Open Diagnostics for the full output"))
            elif ready:
                self.hero_status_label.set_text(tr("Ready to launch"))
                self.hero_status_detail.set_text(tr("eboot.bin found"))
            else:
                self.hero_status_label.set_text(tr("Game not found"))
                self.hero_status_detail.set_text(tr("Choose the folder with eboot.bin"))
        self.update_shell_status()

    def on_ui_language(self, row, _param):
        choice = combo_value(row)
        if choice == (self.settings.get("ui_language") or "en"):
            return
        self.store()
        self.settings["ui_language"] = choice
        save_settings(self.settings)
        if self.process:
            set_language(choice)
            self.toasts.add_toast(Adw.Toast(
                title=tr("Применится после перезапуска лаунчера, пока игра запущена")))
            return
        set_language(choice)
        GLib.idle_add(lambda: self.build() and False)

    def game_dir(self):
        return Path(self.settings["game_dir"]).expanduser()

    def user_dir(self):
        return Path(self.settings["user_dir"]).expanduser() if self.settings["user_dir"] \
            else DATA_DIR / "user"

    def dlc_dir(self):
        return Path(self.settings["dlc_dir"]).expanduser() if self.settings["dlc_dir"] \
            else DATA_DIR / "dlc"

    def update_dlc_status(self):
        custom = bool(self.settings["dlc_dir"])
        self.dlc_row.set_subtitle(str(self.dlc_dir()) if custom else tr("не выбрана"))
        self.dlc_reset.set_sensitive(custom)

    def update_user_status(self):
        path = self.user_dir()
        custom = bool(self.settings["user_dir"])
        self.user_row.set_subtitle(str(path) if custom else tr("По умолчанию: {}").format(path))
        saves = path / "savedata"
        found = saves.is_dir() and any(saves.iterdir())
        self.user_status.set_from_icon_name("object-select-symbolic" if found
                                            else "document-new-symbolic")
        self.user_status.set_tooltip_text(tr("Найдены сохранения") if found
                                          else tr("Сохранений пока нет: игра создаст их здесь"))
        self.user_reset.set_sensitive(custom)
        if hasattr(self, "hero_hunter_summary"):
            self.hero_hunter_summary.set_text(
                tr("Save data found") if found else tr("No saves yet"))

    def update_game_status(self):
        path = self.game_dir()
        ok = self.launch_is_ready()
        self.game_row.set_subtitle(str(path) if self.settings.get("game_dir") else tr("не выбрана"))
        self.game_status.set_from_icon_name("object-select-symbolic" if ok
                                            else "dialog-warning-symbolic")
        self.game_status.set_tooltip_text(tr("Найден eboot.bin") if ok
                                          else tr("Нет eboot.bin в папке"))
        if hasattr(self, "hero_game_summary"):
            self.hero_game_summary.set_text(
                tr("eboot.bin found") if ok
                else tr("No eboot.bin in the selected folder"))
            self.hero_game_summary.set_tooltip_text(str(path))
        self.update_launch_button()

    def on_choose_game(self, _button):
        def chosen(path):
            self.settings["game_dir"] = path
            self.store()
            self.refresh_details()
            self.record_activity("game", tr("Game folder selected"))
        self.choose_folder(tr("Папка игры (с eboot.bin)"), self.game_dir(), chosen)

    def choose_folder(self, title, current, done):
        dialog = Gtk.FileDialog(title=title)
        if Path(current).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(current)))

        def finish(dialog, result):
            try:
                folder = dialog.select_folder_finish(result)
            except GLib.Error:
                return
            if folder:
                done(folder.get_path())
        dialog.select_folder(self, None, finish)

    def on_choose_user(self, _button):
        def chosen(path):
            self.settings["user_dir"] = path
            self.update_user_status()
            self.refresh_trophy_status()
            self.refresh_trophies()
            self.store()
        self.choose_folder(tr("Папка сохранений"), self.user_dir(), chosen)

    def refresh_trophy_status(self):
        if not hasattr(self, "trophy_row"):
            return
        key_file = self.user_dir() / "keys.json"
        if not key_file.is_file():
            self.trophy_row.set_subtitle(tr("Нет keys.json: имена и описания трофеев не отображаются"))
            return
        try:
            data = json.loads(key_file.read_text(encoding="utf-8-sig"))
            valid = valid_trophy_key(data["TrophyKeySet"]["ReleaseTrophyKey"])
        except (OSError, ValueError, KeyError, TypeError):
            valid = False
        self.trophy_row.set_subtitle(tr("keys.json установлен") if valid
                                     else tr("keys.json установлен, но ключ неверный"))

    def on_import_trophy_keys(self, _button):
        dialog = Gtk.FileDialog(title=tr("Выберите keys.json"))

        def finish(dialog, result):
            try:
                file = dialog.open_finish(result)
            except GLib.Error:
                return
            path = file.get_path()
            if not path:
                return
            try:
                import_trophy_key(path, self.user_dir())
            except (OSError, ValueError) as error:
                self.toasts.add_toast(Adw.Toast(
                    title=tr("Не удалось установить ключи трофеев: {}").format(error)))
                return
            self.refresh_trophy_status()
            self.refresh_trophies()
            self.record_activity("settings", tr("Trophy keys imported"))
            self.toasts.add_toast(Adw.Toast(
                title=tr("Ключи трофеев установлены. Имена появятся после запуска игры.")))

        dialog.open(self, None, finish)

    def on_reset_user(self, _button):
        self.settings["user_dir"] = ""
        self.update_user_status()
        self.refresh_trophies()
        self.store()

    def on_choose_dlc(self, _button):
        def chosen(path):
            self.settings["dlc_dir"] = path
            self.update_dlc_status()
            self.store()
        self.choose_folder(tr("Папка DLC"), self.dlc_dir(), chosen)

    def on_reset_dlc(self, _button):
        self.settings["dlc_dir"] = ""
        self.update_dlc_status()
        self.store()

    def refresh_fsr4_status(self):
        if not hasattr(self, "fsr4_row"):
            return
        supported = fsr4_gpu_supported(PORT_DIR)
        total = len(fsr4_files())
        missing = len(fsr4_missing())
        if self.downloading_fsr4:
            self.fsr4_button.set_sensitive(False)
            self.fsr4_progress.set_visible(True)
            return
        if supported is False:
            self.fsr4_row.set_subtitle(tr("Видеокарта не поддерживает FSR 4 (требуется INT8 dot product)"))
            self.fsr4_progress.set_visible(False)
            self.fsr4_button.set_sensitive(False)
            self.fsr4_button.set_label(tr("Не поддерживается"))
            if hasattr(self, "hero_assets_summary"):
                self.hero_assets_summary.set_text(tr("Unsupported GPU"))
        elif missing == 0:
            self.fsr4_row.set_subtitle(tr("Установлены: {} файлов в fsr4_shaders").format(total))
            self.fsr4_progress.set_visible(False)
            self.fsr4_button.set_sensitive(True)
            self.fsr4_button.set_label(tr("Проверить"))
            if hasattr(self, "hero_assets_summary"):
                self.hero_assets_summary.set_text(
                    tr("{} / {} files · Verified").format(total, total))
        else:
            self.fsr4_row.set_subtitle(tr("Отсутствует {} из {} файлов в fsr4_shaders").format(missing, total))
            self.fsr4_progress.set_fraction((total - missing) / total)
            self.fsr4_progress.set_visible(True)
            self.fsr4_button.set_sensitive(True)
            self.fsr4_button.set_label(tr("Скачать ассеты"))
            if hasattr(self, "hero_assets_summary"):
                self.hero_assets_summary.set_text(
                    tr("{} / {} files · Missing {}").format(total - missing, total, missing))

    def on_precompile_shaders(self, _button):
        """Warm the shader/pipeline cache: run the game's pre-build, then exit
        (BB_PRECOMPILE_ONLY), so the next launch starts with the cache warm."""
        if self.process_active():
            self.toasts.add_toast(Adw.Toast(title=tr("Сначала закройте игру.")))
            return
        if self.precompiling:
            return
        self.store()
        self.precompiling = True
        self.precompile_button.set_sensitive(False)
        self.precompile_button.set_label(tr("Компиляция…"))
        self.toasts.add_toast(Adw.Toast(
            title=tr("Компиляция шейдеров… окно игры откроется ненадолго.")))
        env = self.environment()
        env["BB_PRECOMPILE_ONLY"] = "1"
        env["BB_SHADER_PREBUILD"] = "1"
        lines = []

        def work():
            code = 1
            try:
                process = subprocess.Popen(
                    ["bash", str(PORT_DIR / "run.sh")], cwd=str(PORT_DIR), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    errors="replace")
                for line in process.stdout:
                    lines.append(line.rstrip("\n"))
                code = process.wait()
                if code == 0 and not any("Shader pre-build:" in text for text in lines):
                    code = 2  # the game started but the pre-build did not run
            except OSError as error:
                lines.append(str(error))
            GLib.idle_add(self.on_precompile_finished, code, lines)

        threading.Thread(target=work, daemon=True).start()

    def on_precompile_finished(self, code, lines):
        self.precompiling = False
        if hasattr(self, "precompile_button"):
            self.precompile_button.set_sensitive(True)
            self.precompile_button.set_label(tr("Скомпилировать"))
        if code == 0:
            self.record_activity("precompile", tr("Shader precompile finished"))
            self.toasts.add_toast(Adw.Toast(
                title=tr("Шейдеры скомпилированы. Следующий запуск будет быстрее.")))
            return
        self.record_activity("precompile", tr("Shader precompile failed (code {})").format(code))
        dialog = Adw.MessageDialog.new(
            self,
            tr("Не удалось скомпилировать шейдеры (код {}).").format(code),
            "\n".join(lines[-12:]) or None,
        )
        dialog.add_response("ok", tr("Закрыть"))
        dialog.present()

    def on_fetch_fsr4(self, _button):
        if self.downloading_fsr4:
            return
        missing = fsr4_missing()
        if not missing:
            self.refresh_fsr4_status()
            dialog = Adw.MessageDialog.new(
                self,
                tr("Ассеты FSR 4"),
                tr("Все 189 файлов проверены и установлены в fsr4_shaders."),
            )
            dialog.add_response("ok", tr("Закрыть"))
            dialog.present()
            return
        self.downloading_fsr4 = True
        self.fsr4_button.set_sensitive(False)
        self.fsr4_progress.set_visible(True)
        folder = PORT_DIR / "fsr4_shaders"
        total = len(fsr4_files())

        def work():
            error = None
            try:
                folder.mkdir(parents=True, exist_ok=True)
                for name in missing:
                    part = folder / (name + ".part")
                    target = folder / name
                    req = urllib.request.Request(
                        f"{FSR4_BASE}/{name}",
                        headers={"User-Agent": "bbport-launcher"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        part.write_bytes(resp.read())
                    if not validate_fsr4_file(part):
                        part.unlink(missing_ok=True)
                        raise ValueError(f"Corrupted or invalid asset: {name}")
                    part.replace(target)
                    done_count = total - len(fsr4_missing())
                    fraction = done_count / total
                    GLib.idle_add(
                        lambda f=fraction, d=done_count: self.update_fsr4_download_progress(f, d, total) and False
                    )

                if shutil.which("spirv-cross") and shutil.which("glslangValidator"):
                    opt_script = PORT_DIR / "tools" / "fsr4_optimize.sh"
                    if opt_script.is_file():
                        subprocess.run(
                            ["bash", str(opt_script)],
                            cwd=str(PORT_DIR),
                            capture_output=True,
                            timeout=60,
                        )
            except Exception as ex:
                error = ex
            finally:
                GLib.idle_add(lambda: self.on_fsr4_download_finished(error) and False)

        threading.Thread(target=work, daemon=True).start()

    def update_fsr4_download_progress(self, fraction, done, total):
        self.fsr4_progress.set_fraction(fraction)
        self.fsr4_row.set_subtitle(tr("Загрузка: {} из {}...").format(done, total))

    def on_fsr4_download_finished(self, error):
        self.downloading_fsr4 = False
        self.refresh_fsr4_status()
        self.update_upscaler_status()
        if error:
            self.record_activity("fsr4", tr("FSR 4 asset download failed"))
            dialog = Adw.MessageDialog.new(
                self,
                tr("Ошибка загрузки FSR 4: {}").format(error),
                None,
            )
            dialog.add_response("ok", tr("Закрыть"))
            dialog.present()
        else:
            self.record_activity("fsr4", tr("FSR 4 assets downloaded"))

    def update_upscaler_status(self):
        value = combo_value(self.upscaler_row)
        if hasattr(self, "fsr4_row"):
            self.refresh_fsr4_status()
        if hasattr(self, "fsr4_warning_row"):
            self.fsr4_warning_row.set_visible(value in ("fsr4", "fsr411"))
        if value == "fsr4":
            missing = fsr4_missing()
            ok = len(missing) == 0
            hint = tr("Ассеты найдены") if ok else tr("Нет ассетов (скачайте в строке ниже)")
        elif value == "fsr411":
            directory = Path(os.environ["BB_FSR411_DIR"]) if os.environ.get("BB_FSR411_DIR") else (
                PORT_DIR / "fsr4_411" if (PORT_DIR / "fsr4_411").is_dir() else DATA_DIR / "fsr4_411")
            try:
                problem = fsr411_problem(directory, combo_value(self.output_row),
                                         int(combo_value(self.preset_row)))
            except (TypeError, ValueError):
                problem = tr("Некорректное разрешение вывода")
            hint = tr("Ассеты для выбранного режима найдены") if not problem else (
                tr("{}. Установите полный набор fsr4_411 в {}.").format(problem, directory))
        elif value == "dlss":
            hint = tr("DLSS работает только на видеокартах NVIDIA GeForce RTX")
        else:
            hint = tr("Сглаживание в разрешении вывода без модели FSR") if value == "taa" else None
        self.preset_row.set_sensitive(value not in ("taa", "off"))
        self.sharpen_row.set_sensitive(value != "off")
        self.sharpness_row.set_sensitive(value != "off")
        self.upscaler_row.set_subtitle(hint or "")

        if hasattr(self, "preset_row"):
            try:
                preset_idx = int(combo_value(self.preset_row))
            except (TypeError, ValueError):
                preset_idx = 2
            out_str = combo_value(self.output_row) if hasattr(self, "output_row") else "1920x1080"
            custom_res = self.ini.get("render_res")
            rw, rh, scale = compute_internal_resolution(out_str, preset_idx, custom_res)
            try:
                ow, oh = (int(v) for v in str(out_str).lower().split("x"))
            except (ValueError, TypeError):
                ow, oh = 1920, 1080
            if value in ("taa", "off"):
                preset_desc = tr("Нативное разрешение: {} × {}").format(ow, oh)
                preset_desc_short = f"Native: {ow}×{oh}"
            elif custom_res:
                preset_desc = tr("Внутреннее разрешение: {} × {} (ручной ввод) → вывод {} × {}").format(
                    rw, rh, ow, oh)
                preset_desc_short = f"Internal: {rw}×{rh} (custom)"
            else:
                preset_desc = tr("Внутреннее разрешение: {} × {} ({:.1f}×) → вывод {} × {}").format(
                    rw, rh, scale, ow, oh)
                preset_desc_short = f"Internal: {rw}×{rh} ({scale:.1f}×)"
            self.preset_row.set_subtitle(preset_desc)
            if hasattr(self, "hero_graphics_summary"):
                upscaler_label = next(
                    (tr(label) for label, choice in UPSCALERS if choice == value), value)
                preset_label = tr(PRESETS[preset_idx][0]) if 0 <= preset_idx < len(PRESETS) \
                    else tr("Native AA")
                self.hero_graphics_summary.set_text(
                    f"{out_str.replace('x', '×')} · {upscaler_label} · {preset_label}")
                self.hero_graphics_summary.set_tooltip_text(preset_desc)
        self.update_shell_status()

    def store(self):
        s = self.settings
        if hasattr(self, "reduce_motion_row"):
            s["reduce_motion"] = self.reduce_motion_row.get_active()
        if hasattr(self, "ui_language_row"):
            s["ui_language"] = combo_value(self.ui_language_row)
        if hasattr(self, "language_row"):
            s["language"] = combo_value(self.language_row)
        if hasattr(self, "player_row"):
            s["player_name"] = self.player_row.get_text().strip()
        if hasattr(self, "fullscreen_row"):
            s["fullscreen"] = self.fullscreen_row.get_active()
        if hasattr(self, "present_row"):
            s["present_mode"] = combo_value(self.present_row)
        if hasattr(self, "hdr_row"):
            s["hdr"] = self.hdr_row.get_active()
        if hasattr(self, "fps_row"):
            s["fps_mode"] = combo_value(self.fps_row)
        if hasattr(self, "limit_row"):
            s["fps_limit"] = int(self.limit_row.get_value())
        if hasattr(self, "pipe_row"):
            s["draw_pipe"] = combo_value(self.pipe_row)
        if hasattr(self, "readbacks_row"):
            s["readbacks"] = combo_value(self.readbacks_row)
        if hasattr(self, "frames_ahead_row"):
            s["frames_ahead"] = int(self.frames_ahead_row.get_value())
        if hasattr(self, "mangohud_row"):
            s["mangohud"] = self.mangohud_row.get_active()
        if hasattr(self, "precompile_row"):
            s["precompile_shaders"] = self.precompile_row.get_active()
        if hasattr(self, "discord_row"):
            s["discord_rpc"] = self.discord_row.get_active()
        if hasattr(self, "stats_row"):
            s["frame_stats"] = self.stats_row.get_active()
        if hasattr(self, "profile_row"):
            s["gpu_profile"] = self.profile_row.get_active()
        if hasattr(self, "validation_row"):
            s["vk_validation"] = self.validation_row.get_active()
        if hasattr(self, "extra_row"):
            s["extra_env"] = self.extra_row.get_text().strip()
        if hasattr(self, "mods_enabled_row"):
            s["mods_enabled"] = self.mods_enabled_row.get_active()
        if hasattr(self, "control_scheme_row"):
            s["control_scheme"] = combo_value(self.control_scheme_row)
            try:
                apply_control_scheme(s["control_scheme"], self.mods_dir(), DATA_DIR / "mods.json", PORT_DIR,
                                     self._update_ini_for_scheme)
            except (OSError, ValueError):
                pass
        self.save_mod_profile()
        self.save_patch_profile()
        save_settings(s)

        ini_updates = {}
        if hasattr(self, "upscaler_row"):
            ini_updates["upscaler"] = combo_value(self.upscaler_row)
        if hasattr(self, "preset_row"):
            ini_updates["preset"] = str(combo_value(self.preset_row))
        if hasattr(self, "sharpen_row"):
            ini_updates["sharpen"] = "1" if self.sharpen_row.get_active() else "0"
        if hasattr(self, "sharpness_row"):
            ini_updates["sharpness"] = f"{self.sharpness_row.get_value():.2f}"
        if hasattr(self, "motion_row"):
            ini_updates["object_motion"] = "1" if self.motion_row.get_active() else "0"
        if hasattr(self, "show_fps_row"):
            ini_updates["show_fps"] = "1" if self.show_fps_row.get_active() else "0"
        if hasattr(self, "output_row"):
            ini_updates["output_res"] = combo_value(self.output_row)
        if hasattr(self, "hud_row"):
            ini_updates["hud_position"] = combo_value(self.hud_row)
        if hasattr(self, "lod_row"):
            ini_updates["model_lod"] = combo_value(self.lod_row)
        if hasattr(self, "live_row"):
            ini_updates["live_resolution"] = combo_value(self.live_row)
        if hasattr(self, "effect_rows"):
            ini_updates.update({key: "1" if row.get_active() else "0" for key, row in self.effect_rows.items()})
        if hasattr(self, "enhancement_rows"):
            ini_updates.update({key: "1" if row.get_active() else "0"
                               for key, row in self.enhancement_rows.items()})
        if hasattr(self, "cheat_rows"):
            ini_updates.update({key: "1" if row.get_active() else "0" for key, row in self.cheat_rows.items()})

        self.ini.update(ini_updates)
        save_ini(self.ini, self.ini_lines)
        self.ini, self.ini_lines = load_ini()

    def environment(self):
        return game_environment(self.settings)

    # --- Controls ------------------------------------------------------------------------

    def current_control_scheme(self):
        val = self.settings.get("control_scheme")
        return detect_control_scheme(self.mods_dir(), DATA_DIR / "mods.json", fallback=val)

    def _update_ini_for_scheme(self, key_layout, mouse_camera=True):
        self.ini.update(key_layout)
        if mouse_camera:
            self.ini["mouse_camera"] = "1"
        save_ini(self.ini, self.ini_lines)

    def on_control_scheme_changed(self, row, _param):
        choice = combo_value(row)
        self.settings["control_scheme"] = choice
        try:
            apply_control_scheme(choice, self.mods_dir(), DATA_DIR / "mods.json", PORT_DIR,
                                 self._update_ini_for_scheme)
        except ValueError as error:
            if hasattr(self, "toasts"):
                self.toasts.add_toast(Adw.Toast.new(str(error)))
        self.refresh_mods()
        self.update_user_status()

    # --- Mods ----------------------------------------------------------------------------

    def mods_dir(self):
        return Path(self.settings.get("mods_dir") or DATA_DIR / "mods").expanduser()

    def save_mod_profile(self):
        if not hasattr(self, "mod_list"):
            return
        rows = self.mod_list.rows
        content_names = {name for name, _ in rows}
        try:
            existing = json.loads((DATA_DIR / "mods.json").read_text(encoding='utf-8'))
        except (OSError, ValueError):
            existing = {}
        existing_disabled = set(existing.get("disabled", []))
        existing_enabled = set(existing.get("enabled", []))
        prompt_disabled = [n for n in existing_disabled if n not in content_names]
        prompt_enabled = [n for n in existing_enabled if n not in content_names]
        existing_order = existing.get("order", [])
        prompt_order = [n for n in existing_order if n not in content_names]

        order = [name for name, _ in rows] + prompt_order
        disabled = [name for name, row in rows if not row.get_active()] + prompt_disabled
        enabled = [name for name, row in rows if row.get_active()] + prompt_enabled
        profile = {
            "order": order,
            "disabled": sorted(set(disabled)),
            "enabled": sorted(set(enabled)),
        }
        atomic_write_text(DATA_DIR / "mods.json",
                          json.dumps(profile, indent=2, ensure_ascii=False) + "\n")

    def refresh_mods(self):
        if not hasattr(self, "mod_list"):
            return
        self.mod_list.clear()
        self.mods_folder_row.set_subtitle(str(self.mods_dir()))
        try:
            profile = json.loads((DATA_DIR / "mods.json").read_text(encoding='utf-8'))
        except (OSError, ValueError):
            profile = {}
        available = discover_mods(self.mods_dir())
        order = list(dict.fromkeys(n for n in [*profile.get("order", []), *available] if n in available))
        order = [n for n in order if not is_prompt_mod(n)]
        for name in order:
            row = Adw.SwitchRow(title=name, active=name not in profile.get("disabled", []))
            row.add_suffix(flat_button("go-up-symbolic", tr("Загрузить раньше"),
                                        lambda _b, n=name: self.move_mod(n, -1)))
            row.add_suffix(flat_button("go-down-symbolic", tr("Загрузить позже"),
                                        lambda _b, n=name: self.move_mod(n, 1)))
            self.mod_list.add(name, row)
        if not order:
            self.mods_folder_row.set_subtitle(f"{self.mods_dir()} — {tr('Модов нет')}")

    def move_mod(self, name, direction):
        rows = self.mod_list.rows
        index = next(i for i, (n, _) in enumerate(rows) if n == name)
        target = index + direction
        if 0 <= target < len(rows):
            rows[index], rows[target] = rows[target], rows[index]
            self.save_mod_profile()
            self.refresh_mods()

    def on_refresh_mods(self, _button):
        self.save_mod_profile()
        self.refresh_mods()

    def on_choose_mods(self, _button):
        self.save_mod_profile()

        def chosen(path):
            self.settings["mods_dir"] = path
            self.refresh_mods()
            self.store()
        self.choose_folder(tr("Папка модов"), self.mods_dir(), chosen)

    # --- Patches -------------------------------------------------------------------------

    def save_patch_profile(self):
        if not hasattr(self, "patch_list"):
            return
        enabled, disabled = [], []
        for key, row in self.patch_list.rows:
            if row.get_active() != row.default:
                (enabled if row.get_active() else disabled).append(key)
        path = DATA_DIR / "patches.json"
        try:
            profile = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            profile = {}
        shown = {key for key, _ in self.patch_list.rows}
        profile = {"enabled": sorted({k for k in profile.get("enabled", []) if k not in shown} | set(enabled)),
                   "disabled": sorted({k for k in profile.get("disabled", []) if k not in shown} | set(disabled))}
        atomic_write_text(path, json.dumps(profile, indent=2, ensure_ascii=False) + "\n")

    def refresh_patches(self):
        if not hasattr(self, "patch_list"):
            return
        self.patch_list.clear()
        directory = patches_dir(self.settings)
        try:
            profile = json.loads((DATA_DIR / "patches.json").read_text(encoding='utf-8'))
        except (OSError, ValueError):
            profile = {}
        found = external_patches(directory)
        for key, _path, meta in found:
            default = meta.get("isEnabled", "false").lower() == "true"
            active = key in profile.get("enabled", []) or (default and key not in profile.get("disabled", []))
            subtitle = key.split("/", 1)[0]
            if meta.get("Author"):
                subtitle += " · " + tr("Автор: {}").format(meta.get("Author"))
            row = Adw.SwitchRow(title=GLib.markup_escape_text(meta.get("Name") or key),
                                subtitle=GLib.markup_escape_text(subtitle), active=active)
            if meta.get("Note"):
                row.set_tooltip_text(meta.get("Note").replace("\\n", "\n"))
            row.default = default
            self.patch_list.add(key, row)
        self.patches_folder_row.set_subtitle(
            str(directory) if found else f"{directory} — {tr('Патчей нет')}")

    def on_refresh_patches(self, _button):
        self.save_patch_profile()
        self.refresh_patches()

    def on_choose_patches(self, _button):
        self.save_patch_profile()

        def chosen(path):
            self.settings["patches_dir"] = path
            self.refresh_patches()
            self.store()
        self.choose_folder(tr("Папка патчей"), patches_dir(self.settings), chosen)

    # --- Process lifecycle ---------------------------------------------------------------

    def on_launch(self, _button):
        if self.process:
            self.stop_game()
            return
        if self.precompiling:
            self.toasts.add_toast(Adw.Toast(title=tr("Дождитесь окончания компиляции шейдеров.")))
            return
        if self.launch_state in ("starting", "stopping"):
            return
        if not self.launch_is_ready():
            self.toasts.add_toast(Adw.Toast(
                title=tr("Choose the extracted CUSA03173 folder first.")))
            self.show_settings_category("game_data")
            return
        try:
            self.store()
        except Exception as error:
            self.toasts.add_toast(Adw.Toast(
                title=tr("Could not save settings: {}").format(error)))
            return
        self.launch_state = "starting"
        self.update_launch_button()
        self.log_entries = []
        self.refresh_log_view()
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.set_environ([f"{k}={v}" for k, v in self.environment().items()])
        launcher.set_cwd(str(PORT_DIR))
        try:
            self.process = launcher.spawnv(["setsid", "bash", str(PORT_DIR / "run.sh")])
        except GLib.Error as error:
            self.launch_state = "failed"
            self.update_launch_button()
            self.record_activity("session", tr("Game failed to start"))
            dialog = Adw.MessageDialog.new(
                self, tr("Could not launch Bloodborne"), getattr(error, "message", str(error)))
            dialog.add_response("close", tr("Close"))
            dialog.add_response("diagnostics", tr("Open Diagnostics"))
            dialog.set_response_appearance("diagnostics", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", lambda _d, response:
                           self.show_settings_category("diagnostics")
                           if response == "diagnostics" else None)
            dialog.present()
            return
        self.stream = Gio.DataInputStream.new(self.process.get_stdout_pipe())
        self.read_line()
        self.process.wait_async(None, self.on_exit)
        self.launch_state = "running"
        if self._trophy_poll_source:
            try:
                GLib.source_remove(self._trophy_poll_source)
            except Exception:
                pass
        self._trophy_poll_source = GLib.timeout_add_seconds(10, self.poll_trophy_activity)
        self.update_launch_button()
        self.update_playtime_summary()

    def read_line(self):
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)

    def process_active(self):
        return bool(self.process) and not (self.process.get_if_exited()
                                           or self.process.get_if_signaled())

    def on_line(self, stream, result):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error as error:
            self.append_log(tr("Предупреждение: не удалось прочитать журнал: {}\n").format(
                getattr(error, "message", error)))
            if invalid_utf8(error) or self.process_active():
                self.read_line()
            return
        if line is None:
            return
        if "Entering original x86-64 code" in line and self.session_started_at is None:
            self.session_started_at = time.time()
            self.record_activity("session", tr("Game started"))
            self.update_playtime_summary()
        self.append_log(line + "\n")
        self.read_line()

    def stop_game(self):
        if not self.process:
            return
        self.launch_state = "stopping"
        self.update_launch_button()
        try:
            pid = int(self.process.get_identifier())
        except (TypeError, ValueError):
            self.process.force_exit()
            return
        self._stopping_pid = pid
        if pid > 1:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                self.process.force_exit()
        else:
            self.process.force_exit()
        GLib.timeout_add_seconds(3, self.kill_if_running, pid)

    def kill_if_running(self, pid):
        if (pid > 1 and self.process_active()
                and getattr(self, "_stopping_pid", None) == pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        return False

    def on_exit(self, process, result):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        status = process.get_exit_status() if process.get_if_exited() else -1
        if process is not self.process:
            return
        self.process = None
        self._stopping_pid = None
        self.launch_state = "idle"
        poll_source = getattr(self, "_trophy_poll_source", None)
        if poll_source:
            try:
                GLib.source_remove(poll_source)
            except Exception:
                pass
            self._trophy_poll_source = None
        if hasattr(self, "_finish_session"):
            self._finish_session()
        self.update_launch_button()
        if hasattr(self, "refresh_details"):
            self.refresh_details()
        if hasattr(self, "refresh_trophies"):
            self.refresh_trophies()
        if hasattr(self, "append_log"):
            self.append_log(tr("\n— игра завершилась (код {}) —\n").format(status))

    def _finish_session(self):
        if self.session_started_at is None:
            return
        duration = max(0, int(time.time() - self.session_started_at))
        self.session_started_at = None
        try:
            add_playtime(activity_path(), duration)
        except OSError:
            pass
        self.record_activity(
            "session", tr("Played for {}").format(format_playtime(duration)))
        self.update_playtime_summary()

    def on_close(self, _window):
        if getattr(self, "_save_source", None):
            try:
                GLib.source_remove(self._save_source)
            except Exception:
                pass
            self._save_source = None
        if getattr(self, "_trophy_poll_source", None):
            try:
                GLib.source_remove(self._trophy_poll_source)
            except Exception:
                pass
            self._trophy_poll_source = None
        self._finish_session()
        self.store()
        if self.process:
            self.stop_game()
        return False


class LauncherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.bbport.Launcher",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        install_theme()
        if not getattr(self, "_activity_recorded", False):
            self._activity_recorded = True
            try:
                record_event(activity_path(), "launcher", tr("Launcher started"))
            except OSError:
                pass
        window = self.get_active_window() or LauncherWindow(self)
        window.present()
        window.update_recent_activity()


def play():
    """--play: launches the game with saved settings, headless (Steam Deck mode)."""
    settings = load_settings()
    if not (Path(settings["game_dir"]).expanduser() / "eboot.bin").is_file():
        print("bbport: choose the game folder in the launcher first", file=sys.stderr)
        return 1
    os.chdir(PORT_DIR)
    os.execvpe("bash", ["bash", str(PORT_DIR / "run.sh")], game_environment(settings))


if __name__ == "__main__":
    if "--play" in sys.argv[1:]:
        sys.exit(play())
    sys.exit(LauncherApp().run(sys.argv))

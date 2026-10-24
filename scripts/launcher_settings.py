"""Settings.json -> environment for run.sh, when run.sh is started directly.

Prints NUL-separated KEY/VALUE pairs for the settings the launcher exports when it starts the
game. run.sh applies only the pairs whose key is not already in the environment, so a launch
from the launcher (or an explicit CLI variable) always wins.
"""
import json
import os
import re
import sys


def text(value):
    return value.strip() if isinstance(value, str) else ''


def main(argv):
    if len(argv) != 3:
        return 1
    path, data = argv[1], argv[2]
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            settings = json.load(handle)
    except (OSError, ValueError, TypeError):
        return 0
    if not isinstance(settings, dict):
        return 0

    pairs = []

    def emit(key, value):
        if value is None or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            return
        pairs.append((key, str(value)))

    def folder(value):
        return os.path.expanduser(text(value))

    game = folder(settings.get('game_dir'))
    game_valid = bool(game and os.path.isfile(os.path.join(game, 'eboot.bin')))
    if game_valid:
        emit('BB_GAME_DIR', game)
    # Saves stay with the game, matching the launcher's default; the data folder is only a
    # fallback while no real game folder is configured.
    default_user = os.path.join(game, 'user') if game_valid else os.path.join(data, 'user')
    emit('BB_USER_DIR', folder(settings.get('user_dir')) or default_user)
    name = text(settings.get('player_name'))
    if name:
        emit('BB_USER_NAME', name)
    dlc = folder(settings.get('dlc_dir'))
    if dlc:
        emit('BB_DLC_DIR', dlc)
    mods = folder(settings.get('mods_dir'))
    if mods:
        emit('BB_MODS_DIR', mods)
    emit('BB_MODS_ENABLED', '1' if settings.get('mods_enabled', True) else '0')
    patches = folder(settings.get('patches_dir'))
    if patches:
        emit('BB_PATCHES_DIR', patches)
    emit('BB_LANGUAGE', text(settings.get('language')) or '1')
    emit('BB_FULLSCREEN', '1' if settings.get('fullscreen') else '0')
    emit('BB_PRESENT_MODE', text(settings.get('present_mode')) or 'Mailbox')
    if settings.get('hdr'):
        emit('BB_HDR', '1')
    fps = text(settings.get('fps_mode'))
    if fps:
        emit('BB_FPS', fps)
    limit = settings.get('fps_limit')
    if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit > 0:
        emit('BB_FPS_LIMIT', int(limit))
    ahead = settings.get('frames_ahead')
    if (isinstance(ahead, (int, float)) and not isinstance(ahead, bool)
            and int(ahead) != 1):
        emit('BB_FRAMES_AHEAD', int(ahead))
    pipe = text(settings.get('draw_pipe'))
    if pipe:
        emit('BB_DRAW_PIPE', pipe)
    readbacks = text(settings.get('readbacks'))
    if readbacks:
        emit('BB_READBACKS', readbacks)
    if settings.get('mangohud'):
        emit('MANGOHUD', '1')
    if settings.get('frame_stats'):
        emit('BB_FRAME_STATS', '1')
    if settings.get('gpu_profile'):
        emit('BB_GPU_PROFILE', '1')
    if settings.get('vk_validation'):
        emit('BB_VK_VALIDATION', '1')
    emit('BB_SHADER_PREBUILD', '1' if settings.get('precompile_shaders', True) else '0')
    emit('BB_DISCORD_RPC', '1' if settings.get('discord_rpc', True) else '0')
    for item in text(settings.get('extra_env')).split():
        if '=' in item:
            key, value = item.split('=', 1)
            emit(key, value)

    out = sys.stdout.buffer
    for key, value in pairs:
        out.write(key.encode('utf-8') + b'\0' + value.encode('utf-8') + b'\0')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

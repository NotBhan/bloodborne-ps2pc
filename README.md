# Bloodborne PC (Linux-First Fork)

A stripped, native Linux-first fork of the Bloodborne PC project.

This fork runs your own decrypted copy of Bloodborne (CUSA03173, version 1.09) natively on Linux. The game's code runs directly on x86_64 CPUs, and its graphics are translated through a Vulkan 1.3 renderer.

This project is derived from the work of [Jgamrot](https://github.com/Jgamrot/bloodborne_pc), [Supermedo](https://github.com/Supermedo/bloodborne_pc), [deadinside28](https://github.com/deadinside28/bloodborne_pc), and the [shadPS4](https://github.com/shadps4-emu/shadPS4) project.

> [!IMPORTANT]
> **No game files are included.** You must provide your own decrypted dump of Bloodborne (CUSA03173, patch version 1.09). This project is not affiliated with, endorsed by, or associated with Sony Interactive Entertainment or FromSoftware.

---

## Fork Direction & Divergence

The objective of this fork is to take the port's barebones Linux launcher and develop it into a fully featured native GTK4/libadwaita control surface with the same feature set as the Windows launcher, while keeping the optimized Vulkan upscaling path:

1. **Refined Linux Launcher (PS5-style, built out from the barebones launcher)**:
   - A game-first shell with exactly three destinations: **Game Details** (full-bleed key art, real launch/readiness state, graphics and save summary, honest activity journal), **Trophies** (local cache and unlock history with truthful unavailable states), and **Settings** (display, graphics, upscaling, performance, compatibility, controller, game & data, launcher preferences, diagnostics).
   - Matched the Windows launcher's feature set: graphics presets and FSR 3.1/FSR 4/DLSS selection, internal-resolution scaling and persistence, mods and patches, launch diagnostics, restart supervision, and desktop integration. Logs and diagnostics live inside Settings rather than a competing primary page.
   - Keyboard and mouse rebinding in **Settings → Controller**, including mouse buttons and wheel inputs. Bindings are written as `key_<action>=` in `bbport.ini`, keep one key and one mouse input per action, and apply on the next launch.
   - Added strict XDG configuration, a six-language UI, internal-resolution calculations, a debounced settings save path, and a native GTK4/libadwaita layout on top of the original launcher.
   - Trophy reporting is read-only and local ([`launcher/bbport_trophies.py`](launcher/bbport_trophies.py)); the launcher never invents names, dates, rarity, or completion. The activity journal ([`launcher/bbport_activity.py`](launcher/bbport_activity.py)) records only real launch, folder, trophy, and asset events.
   - Shader precompile controls: the automatic pre-build on launch (`BB_SHADER_PREBUILD`) and **Precompile shaders now**, which runs the pipeline warm-up in a short game run and exits. Shaders never recorded yet still compile once, the first time they are drawn.
   - Trophy keys import in **Game → Trophy keys**: names, descriptions, grades and Gamerscore from your own trophy pack, plus the local unlock history and automatic platinum.
   - Discord Rich Presence: `run.sh` starts the bundled companion beside the game (toggle in the graphics performance settings). It reports the game name and hunter level, and switches to a Platinum state when the platinum trophy is unlocked; area, Echoes and Insight are no longer shown.
   - The trophy list separates **Unlocked** and **Locked** entries. Game Details shows total play time and a game-only activity feed: sessions and real trophy unlocks, never launcher/settings noise.
   - The Windows launcher is not replaced or purged: it remains maintained in the Windows tree/branch (`windows_laucnher/`), and both launchers share the renderer, settings keys (`bbport.ini`), and preparation scripts.
   - Linux packaging (`launcher/bb-launcher.sh`, `--install-desktop`, Nix/AppImage) stays in this branch; Windows packaging stays with the Windows launcher.
   - Shared online network and Hunter's Dream account logic live in [`launcher/bbport_net.py`](launcher/bbport_net.py); bundled prompt mods are in [`bundled/`](bundled/) and [`mods/`](mods/); third-party licensing is preserved in [`licenses/`](licenses/).

2. **Native Linux Experience**:
   - The native GTK4 + libadwaita launcher ([`launcher/bbport_launcher.py`](launcher/bbport_launcher.py)) is the primary control surface on Linux.
   - Strict XDG compliance for configuration (`~/.config/bbport-launcher/settings.json`), user data, and saves (`~/.local/share/bbport/user/`).
   - Single-command desktop entry installation (`launcher/bbport_launcher.py --install-desktop`) integrating with your Linux application launcher.

3. **Preserved & Verified Internal Resolution Scaling**:
   - Retained the internal render resolution selector alongside output resolution selection.
   - Added real-time internal render resolution and scaling factor calculations in the launcher UI (e.g., rendering at `1280 × 720 (1.5×)` reconstructed to `1920 × 1080`).
   - Full persistence and bidirectional synchronization with `bbport.ini`.

4. **Diagnosed & Fixed Upscaler Performance Bottlenecks**:
   - Resolved the performance regression where enabling an upscaler dropped FPS instead of improving it.
   - Eliminated redundant native proxy resolves, unblocked depth proxy sampling, removed queue-draining barriers, and eliminated synchronous GPU/CPU waits.

---

## Upscaler Bottleneck Diagnosis & Resolution

### The Problem
When enabling temporal upscalers (FSR 3.1, FSR 4, DLSS), users reported that frame rates decreased compared to native rendering, even with lower internal render resolutions selected.

### Root-Cause Analysis
Investigation into the Vulkan rendering pipeline ([`gpu/shadps4/video_core/renderer_vulkan/vk_temporal_upscaler.cpp`](gpu/shadps4/video_core/renderer_vulkan/vk_temporal_upscaler.cpp) and [`gpu/shadps4/video_core/renderer_vulkan/vk_scene_resolution.cpp`](gpu/shadps4/video_core/renderer_vulkan/vk_scene_resolution.cpp)) revealed four critical defects:

1. **Redundant Proxy Resolves on Reduced Resolutions**:
   In `TemporalUpscaler::Run()`, before dispatching the upscaler, `runtime.Transit(&depth)` and `runtime.Transit(&color)` were unconditionally called on the native render targets. When rendering at reduced internal resolution, this forced an unnecessary 1080p color blit and a 9-draw-call depth stencil resample on the GPU every single frame, only for the upscaler immediately following to read the reduced proxy targets directly and discard the resolved native surfaces.
2. **Blocked Depth Proxy Sampling**:
   In `SceneTargets::ProxyCurrent()`, the predicate checked `|| image.info.props.is_depth`, which unconditionally rejected depth proxies from being marked as current. This caused any subsequent pass sampling depth (deferred shading, fog, SSAO) to fall back to the native depth target, continuously re-triggering the expensive 9-draw resolve churn.
3. **Queue-Draining Synchronization Barriers**:
   Vulkan pipeline barriers for motion vectors and output images used `vk::PipelineStageFlagBits2::eAllCommands`. This drained the entire GPU execution pipeline and serialized compute work with graphics passes.
4. **Synchronous CPU Stalls on Sharpening Resizes**:
   `TemporalUpscaler::ExtraSharpen()` executed `scheduler.WaitSubmitted()` on resolution adjustments, blocking the CPU render thread until the GPU became completely idle.

### Changes Implemented
- In `vk_temporal_upscaler.cpp`: Wrapped color and depth target transitions inside `if (!reduced)` so that proxy resolves are completely bypassed during upscaled rendering.
- In `vk_scene_resolution.cpp`: Removed the depth rejection from `ProxyCurrent()` and added proper `vk::ImageLayout::eDepthStencilReadOnlyOptimal` transitions in `PrepareSample()`, allowing shaders to sample reduced depth proxies directly.
- Converted image memory barriers from `eAllCommands` to targeted `eComputeShader` stages.
- Replaced the synchronous `scheduler.WaitSubmitted()` stall with non-blocking deferred destruction via `scheduler.DeferOperation()`.

> [!NOTE]
> **Performance Caveat**: Automated unit and rendering tests verify that the redundant resolves, CPU stalls, and barrier serializations have been eliminated. However, temporal upscalers incur compute dispatch overhead and reconstruct from internal targets. In CPU-bound scenes or on low-end GPUs where compute execution exceeds pixel shader savings, upscaling may not increase FPS. In-game comparative performance across gameplay scenes has not been empirically benchmarked.

---

## Graphics Configuration, Upscaling & Performance Lifecycle

### Authoritative Preset Mapping

The internal render target dimensions before upscaler reconstruction follow a single authoritative mapping across the launcher, runtime, and documentation:

| Preset Index | Display Name | Internal Scale Factor | 1080p Render Target | 1440p Render Target | 4K Render Target | Persisted Value |
|---|---|---|---|---|---|---|
| **0** | **Native AA** | 1.0× | 1920 × 1080 | 2560 × 1440 | 3840 × 2160 | `preset=0` |
| **1** | **Quality** | 1.5× | 1280 × 720 | 1706 × 960 | 2560 × 1440 | `preset=1` |
| **2** | **Balanced** | 1.7× | 1130 × 636 | 1506 × 848 | 2258 × 1270 | `preset=2` |
| **3** | **Performance** | 2.0× | 960 × 540 | 1280 × 720 | 1920 × 1080 | `preset=3` |
| **4** | **Ultra Performance** | 3.0× | 640 × 360 | 854 × 480 | 1280 × 720 | `preset=4` |

> [!NOTE]
> **Checklist Discrepancy Resolved**: An earlier manual checklist incorrectly labeled Quality as preset `4`. Quality is preset `1` (1.5× scale); preset `4` represents Ultra Performance (3.0× scale).

### Upscaler Compatibility & FSR 4 on AMD RX 6600M (RDNA 2)

- **FSR 3.1 (Recommended Baseline)**:
  Universal compatibility, proven stability, and optimal performance on AMD RDNA 2 hardware.
- **FSR 4 [Experimental ⚠️]**:
  Selectable for users who wish to test it. On AMD Radeon RX 6600M (RDNA 2, 8 GB VRAM), hardware capability checks detect INT8 dot products and derivative groups. However, RDNA 2 lacks dedicated tensor/matrix cores and executes neural-model INT8 operations via general compute ALUs, incurring high execution latency.
  - **Persistent Warning**: The graphics UI displays:
    *“Experimental on this GPU. AMD Radeon RX 6600M is RDNA 2. FSR 4 may run significantly slower or less reliably than FSR 3.1. Performance is not guaranteed. If you experience frame drops, stuttering, or instability, switch to FSR 3.1.”*
  - **Honest Upscaler Reporting**: User selection (`upscaler`) is kept distinct from the active upscaler (`active_upscaler`). If FSR 4 initialization or assets fail, the runtime falls back to FSR 3.1, logs the reason, and informs the UI without silently altering user settings.
  - **Clean Resource Lifecycle**: Switching away from FSR 4 triggers complete destruction (`Fsr4Upscaler::Impl::Destroy()`) of backend contexts, pipelines, and allocations, freeing all GPU memory.

### Long-Session Degradation & Texture Cache Fix

- On 8 GB discrete GPUs, `trigger_gc_memory` previously evaluated to 0 due to integer truncation `(device_local_memory - mem_threshold) / 2 = (8GB - 8GB) / 2 = 0`.
- This triggered heavy garbage collection sweeps on every single frame submission, causing frame times to degrade over time.
- Fixed in `gpu/shadps4/video_core/texture_cache/texture_cache.cpp` by gating GC sweeps to when VRAM usage exceeds 70% of budget.

### "Restart to Apply" Supervision Lifecycle

- Selecting "Restart to Apply" saves settings via `bbgpu_settings_save()`, flushes GPU queues and logs, and exits cleanly with exit code `85` (`EXIT_RESTART`).
- The supervisor in `run.sh` and `run.py` catches exit code `85`, re-generates patches with updated settings via `scripts/patches.py`, and relaunches the game process.
- All launch arguments, working directory, and environment variables are preserved. The supervisor bounds restarts to at most 1 relaunch attempt, preventing infinite loops.

### Redesigned 5-Section Graphics UI

Both the native GTK4/libadwaita launcher and in-game menu follow 5 clear categories:
1. **Rendering and Resolution**: Output resolution, live resolution switching, fullscreen, present mode, HDR, ultrawide HUD position.
2. **Upscaling and Temporal Reconstruction**: Upscaler selection, FSR 4 warning, quality preset, FSR 4 assets, object motion vectors.
3. **Image Quality and Sharpening**: RCAS sharpening toggle and strength, model LOD, in-game post-processing effects.
4. **Compatibility and GPU Pipeline**: Two-stage GPU pipeline, readbacks, game enhancements, and tweaks.
5. **Performance Diagnostics**: In-engine FPS counter, frame rate limiter, MangoHud, frame statistics, and GPU profiler.

---

## Requirements

### Operating System & Dependencies
- Linux x86_64 (glibc-based distributions: Ubuntu 22.04+, Fedora 38+, Arch Linux, etc.).
- Graphics card with **Vulkan 1.3** and `VK_KHR_dynamic_rendering` support (Mesa RADV/ANV, or proprietary NVIDIA driver 535+).
- Python 3.10+ with `PyGObject` (`gi`), `GTK4`, and `libadwaita`.
- Vulkan development headers, Clang/LLVM or GCC, CMake 3.22+, and Ninja (for compiling).

### CPU Requirements
- Intel Core 4th generation (Haswell, 2013) or newer, or AMD Ryzen.
- The game requires AVX, BMI1, MOVBE, and LZCNT instructions. CPUs lacking AVX cannot execute the port.

---

## Building and Running

### 1. Build the Native Port
Clone the repository recursively with submodules:
```bash
git clone --recursive https://github.com/NotBhan/bloodborne_pc_notbhan.git
cd bloodborne_pc_notbhan
```

Compile the Vulkan runtime, loader, and C tools:
```bash
./build.sh
```

To run all native C/C++ unit tests (allocator, memory, pad, semaphores, frame limiter, scene resolution, upscaler fallback):
```bash
./build.sh --test
```

### 2. Launch the Native Launcher
Launch the GTK4 launcher interface:
```bash
./run_launcher.sh
```
This is a convenience wrapper for `./launcher/bb-launcher.sh`, which uses `nix-shell` when
PyGObject, GTK 4 or libadwaita are not installed. Or directly via Python:
```bash
python3 launcher/bbport_launcher.py
```

To install the desktop shortcut into `~/.local/share/applications`:
```bash
python3 launcher/bbport_launcher.py --install-desktop
```

### 3. Direct Command-Line Launch
You can also bypass the GUI launcher and execute the game directly:
```bash
./run.sh --app0 /path/to/CUSA03173
```

---

## Configuration & Persistence

Configuration is strictly divided between user environment preferences and in-engine settings:

1. **Launcher Settings** (`~/.config/bbport-launcher/settings.json`):
   - `game_dir`: Path to extracted `CUSA03173` directory containing `eboot.bin`.
   - `user_dir`: Saves and trophy folder (defaults to `~/.local/share/bbport/user/`).
   - `mods_dir` & `mods_enabled`: Mods directory and toggle.
   - `control_scheme`: `xbox`, `pc` (keyboard/mouse with PCBButtons prompts), or `playstation`.
   - `fps_mode` & `fps_limit`: Uncapped or capped frame limits.
   - `present_mode`: Vulkan presentation mode (`Mailbox`, `Fifo`, `FifoRelaxed`, `Immediate`).
   - `fullscreen`: Fullscreen toggle.
   - `mangohud`: Integration with MangoHud overlay.

2. **Game Engine Settings** (`bbport.ini`):
   - `upscaler`: `fsr3`, `fsr4`, `fsr411`, `dlss`, `taa`, or `off`.
   - `preset`: `0` (Native), `1` (Quality), `2` (Balanced), `3` (Performance), `4` (Ultra Performance).
   - `output_res`: Output resolution string (e.g., `1920x1080`, `2560x1440`, `3840x2160`).
   - `sharpen` & `sharpness`: RCAS sharpening settings.
   - `effect_*`: Toggles for chromatic aberration, depth of field, motion blur, SSAO, dynamic shadows, SSR.
   - `pc_*`: Optional enhancements (lamp level up/storage, rebirth, mirror appearance, two invaders).

---

## Testing & Validation Suite

Run all validation test suites:

```bash
# 1. Native C/C++ engine, Vulkan, and math tests:
./build.sh --test

# 2. Python launcher, network, mod, and patch tests (421 tests, 48 skipped, 0 failures):
python3 -m unittest discover tests
```

- **Linux Launcher Tests** ([`tests/test_launcher_linux.py`](tests/test_launcher_linux.py), [`tests/test_launcher_trophies.py`](tests/test_launcher_trophies.py), [`tests/test_launcher_activity.py`](tests/test_launcher_activity.py)):
  Validates the three-destination shell, PS5 settings navigation, launch-state guards, log filtering, trophy cache/history parsing and unavailable states, activity journaling, GTK4/Adw row generation, XDG path resolution, INI roundtrips, atomic writes, control scheme switching, FSR support probing, and internal resolution calculations.
- **Supervisor & Restart Tests** ([`tests/test_run_settings.py`](tests/test_run_settings.py)):
  Validates supervisor handling of exit code `85`, argument and environment preservation, single-restart bounding, and normal exit isolation.
- **Scene Resolution & Upscaler Fallback Tests** ([`tests/test_scene_resolution.cpp`](tests/test_scene_resolution.cpp), [`tests/test_upscaler_support.cpp`](tests/test_upscaler_support.cpp)):
  Validates Vulkan target proxies, stencil preservation, downscaling math, and dynamic FSR/DLSS device fallbacks on Vulkan (runs headlessly via Lavapipe).

---

## Retained Upstream Attribution & Licenses

This fork builds upon foundational work from the open-source community:

- **[Supermedo](https://github.com/Supermedo/bloodborne_pc)** (Mohammed Albarghouthi) for the initial PC port.
- **[deadinside28](https://github.com/deadinside28/bloodborne_pc)** for `bbport`.
- **[shadPS4 Team](https://github.com/shadps4-emu/shadPS4)** for the PlayStation 4 recompiler and Vulkan translation layers.
- **[droogie](https://github.com/droogie/bbhost)** for in-engine PC menus, enhancements, and keyboard prompt systems.
- **[Awaken](https://github.com/Awakenchan/BloodBorneButPc)**, **[The Hunter's Dream Team](https://thehuntersdream.com)**, and **[Wozzardman](https://github.com/Wozzardman/shadp2p)** for online backend and multiplayer adaptation.
- **[MikeTat1988](https://github.com/MikeTat1988/HuntersAtlas)** for Hunter's Atlas (GPL-2.0).
- **[AzaharPlus](https://github.com/AzaharPlus/shadPS4Plus)** for PkgExtractor (GPL-2.0).
- **Dommo** for Xbox prompts ([Nexus Mods #30](https://www.nexusmods.com/bloodborne/mods/30)).
- **JinkiJinn** for PCBButtons keyboard prompts ([Nexus Mods #460](https://www.nexusmods.com/bloodborne/mods/460)).

All third-party licenses are preserved in [`licenses/`](licenses/) and [`LICENSE`](LICENSE).

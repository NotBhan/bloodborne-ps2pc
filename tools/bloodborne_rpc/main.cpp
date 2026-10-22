// Bloodborne PC (bbport) - Discord Rich Presence companion.
// READ-ONLY: this tool never writes to the game's memory.
// SPDX-FileCopyrightText: Copyright 2026 @erezeth
// SPDX-License-Identifier: GPL-2.0-or-later

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <tlhelp32.h>
#else
#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <cerrno>
#endif
#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include "json.hpp"

namespace fs = std::filesystem;
using json = nlohmann::json;
using clk = std::chrono::steady_clock;

constexpr uintptr_t GAME_DATA_MAN = 0x553B130;
constexpr uintptr_t WORLD_CHR_MAN = 0x553E878;
constexpr int CHR_BLOCK = 0x3F8;
// 0x5562878 is the port's quick-menu slot (src/runtime_map.c), not a boss gauge.
// Boss names stay disabled until a verified boss-gauge offset is available.
constexpr uintptr_t BOSS_GAUGE_ADDR = 0;
constexpr int PGD_HP = 0x14, PGD_MAXHP = 0x18;
constexpr int PGD_INSIGHT = 0x84, PGD_LEVEL = 0x90, PGD_ECHOES = 0x94;
constexpr int PGD_READ_SIZE = 0x98;

struct AttrDef { const char* name; int off; };
constexpr AttrDef PGD_ATTR_DEFS[6] = {{"VIT", 0x40}, {"END", 0x48}, {"STR", 0x58}, {"SKL", 0x60}, {"BLT", 0x68}, {"ARC", 0x70}};
constexpr std::array<std::pair<int32_t, const char*>, 21> BbscPlaceNames{{
    {2100, "Hunter's Dream"}, {2110, "Abandoned Old Workshop"}, {2200, "Hemwick Charnel Lane"},
    {2300, "Old Yharnam"}, {2400, "Cathedral Ward"}, {2410, "Central Yharnam"},
    {2411, "Iosefka's Clinic"}, {2420, "Upper Cathedral Ward"}, {2421, "Healing Church Workshop"},
    {2422, "Altar of Despair"}, {2500, "Forsaken Cainhurst Castle"}, {2600, "Nightmare of Mensis"},
    {2700, "Forbidden Woods"}, {2800, "Yahar'gul, Unseen Village"}, {3200, "Byrgenwerth"},
    {3201, "Lecture Building"}, {3202, "Moonside Lake"}, {3300, "Nightmare Frontier"},
    {3400, "Hunter's Nightmare"}, {3500, "Research Hall"}, {3600, "Fishing Hamlet"},
}};

constexpr std::array<std::pair<int32_t, const char*>, 87> BbscBossNames{{
    {1000, "Madman's Escort"}, {1010, "Forgotten Madman"}, {6400, "Old Hunter Henryk"},
    {6500, "Valtr, Master of the League"}, {6505, "Valtr, Beast Eater"}, {6530, "Yamamura the Wanderer"},
    {6540, "Younger Madaras Twin"}, {6550, "Mensis Scholar Damian"}, {6600, "Henriett"},
    {6640, "Defector Antal"}, {7040, "Tomb Prospector Olek"}, {7045, "Tomb Prospector Gremia"},
    {7060, "Beastclaw Jozef"}, {7160, "Queen Killer"}, {7300, "Vitus"}, {7310, "Madman Wallar"},
    {101000, "Degenerate Beast"}, {106000, "Brainsucker"}, {127000, "Maneater Boar"},
    {209000, "Blood-starved Beast"}, {209010, "Blood-starved Beast"}, {210000, "The Witch of Hemwick"},
    {212010, "Shadow of Yharnam"}, {212020, "Shadow of Yharnam"}, {212030, "Shadow of Yharnam"},
    {216000, "Keeper of the Old Lords"}, {218000, "Loran Silverbeast"}, {232000, "Martyr Logarius"},
    {251000, "Ebrietas, Daughter of the Cosmos"}, {251010, "Ebrietas, Daughter of the Cosmos"},
    {257000, "Celestial Emissary"}, {257010, "Celestial Emissary"}, {271000, "Father Gascoigne"},
    {272000, "Father Gascoigne"}, {304000, "Merciless Watcher"}, {304001, "Watcher Chieftain"},
    {304002, "Merciless Watcher"}, {304003, "Merciless Watcher"}, {305000, "Pthumerian Descendant"},
    {305001, "Pthumerian Descendant"}, {305002, "Pthumerian Elder"}, {306000, "Pthumerian Bride"},
    {306001, "Yharnam, Pthumerian Queen"}, {313000, "Undead Giant"}, {403000, "Living Failures"},
    {450000, "Laurence, the First Vicar"}, {451000, "Ludwig the Accursed"}, {451005, "Ludwig, the Holy Blade"},
    {452000, "Lady Maria of the Astral Clocktower"}, {453000, "Orphan of Kos"}, {454000, "Orphan of Kos"},
    {500000, "Cleric Beast"}, {501000, "Watchdog of the Old Lords"}, {502000, "Vicar Amelia"},
    {504000, "Loran Darkbeast"}, {504010, "Abhorrent Beast"}, {507000, "The One Reborn"},
    {508000, "Darkbeast Paarl"}, {508010, "Loran Darkbeast"}, {509000, "Bloodletting Beast"},
    {509010, "Bloodletting Beast"}, {510000, "Rom, the Vacuous Spider"}, {510010, "Rom, the Vacuous Spider"},
    {511000, "Great One Beast"}, {512000, "Amygdala"}, {512010, "Amygdala"}, {540000, "Moon Presence"},
    {551000, "Mergo's Wet Nurse"}, {551010, "Mergo's Wet Nurse"}, {750000, "Beast-possessed Soul"},
    {802000, "Slug Princess"}, {803000, "Heroine Doll"}, {804000, "Gehrman, the First Hunter"},
    {805000, "Gehrman, the First Hunter"}, {899000, "Micolash, Host of the Nightmare"},
    {899010, "Vileblood Hunter Alfred"}, {900020, "The Vileblood"}, {900030, "The Executioners"},
    {900040, "Hunter of Hunters"}, {901040, "Nameless Tomb Prospector"}, {901060, "Izzy's Admirer"},
    {901070, "Nameless Madman"}, {901110, "Bone Ash Hunter Carla"}, {901150, "Drifting Vileblood Leo"},
    {901160, "Ardeo Man"}, {901170, "Defeated Hunter"}, {901180, "Choir Intelligencer Edgar"},
}};

template <size_t N>
const char* FindBbscName(const std::array<std::pair<int32_t, const char*>, N>& names, int32_t id) {
    for (const auto& [key, text] : names) { if (key == id) return text; }
    return nullptr;
}

static std::string GetAreaName(uint32_t map_id) {
    if (map_id == 0) return "";
    int32_t area = (map_id >> 24) & 0xFF, block = (map_id >> 16) & 0xFF;
    if (area > 40 || block > 20) return "";
    if (area == 29) return "Chalice Dungeon";
    if (const char* name = FindBbscName(BbscPlaceNames, area * 100 + block * 10)) return name;
    if (const char* name = FindBbscName(BbscPlaceNames, area * 100)) return name;
    char buf[32]; std::snprintf(buf, sizeof(buf), "m%02d_%02d", area, block); return buf;
}

static fs::path g_exe_dir;
static std::string hex(uintptr_t v) { char b[32]; std::snprintf(b, sizeof(b), "0x%llx", (unsigned long long)v); return b; }

static fs::path log_path() {
#ifdef _WIN32
    if (const char* base = std::getenv("LOCALAPPDATA"); base && *base) {
        std::error_code ec;
        const fs::path dir = fs::path(base) / "bbport-launcher";
        fs::create_directories(dir, ec);
        if (!ec) return dir / "rpc.log";
    }
#else
    fs::path dir;
    if (const char* base = std::getenv("XDG_STATE_HOME"); base && *base)
        dir = fs::path(base) / "bbport";
    else if (const char* home = std::getenv("HOME"); home && *home)
        dir = fs::path(home) / ".local" / "state" / "bbport";
    if (!dir.empty()) {
        std::error_code ec;
        fs::create_directories(dir, ec);
        if (!ec) return dir / "rpc.log";
    }
#endif
    return g_exe_dir / "rpc.log";
}

static void log(const std::string& msg) {
    char ts[16]; std::time_t t = std::time(nullptr); std::tm tb{};
#ifdef _WIN32
    localtime_s(&tb, &t);
#else
    localtime_r(&t, &tb);
#endif
    std::strftime(ts, sizeof(ts), "%H:%M:%S", &tb);
    const std::string line = std::string("[") + ts + "] " + msg;
    std::ofstream f(log_path(), std::ios::app);
    if (f) f << line << "\n";
    std::fprintf(stderr, "%s\n", line.c_str());
}

static void fatal(const std::string& msg) {
    log("[ERROR] " + msg);
#ifdef _WIN32
    if (!std::getenv("BB_GAME_PID")) MessageBoxA(nullptr, msg.c_str(), "BloodborneRPC", MB_ICONERROR | MB_OK);
#endif
}

static fs::path exe_directory() {
#ifdef _WIN32
    wchar_t buf[MAX_PATH]; DWORD n = GetModuleFileNameW(nullptr, buf, MAX_PATH);
    if (n == 0) return fs::current_path();
    try { return fs::path(std::wstring(buf, n)).parent_path(); } catch (...) { return fs::current_path(); }
#else
    char buf[4096]; const ssize_t n = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
    if (n <= 0) return fs::current_path();
    buf[n] = 0;
    return fs::path(buf).parent_path();
#endif
}

struct Config {
    std::string client_id; std::string process_name = "bb-probe.exe"; std::vector<uintptr_t> image_bases = {0x800000000};
    int attach_delay = 5, update_interval = 15; double poll_interval = 1.0;
    std::string large_image = "bloodborne_logo", small_image; json buttons = json::array(); bool offline_only = false;
    std::string user_dir;
    bool show_level = true, show_platinum = true;
};

static Config load_config(const fs::path& path) {
    Config c; if (!fs::exists(path)) return c;
    try {
        std::ifstream f(path); json j; f >> j;
        if (j.contains("client_id")) c.client_id = j["client_id"];
        if (j.contains("process_name")) c.process_name = j["process_name"];
        if (j.contains("image_base_candidates") && j["image_base_candidates"].is_array()) {
            c.image_bases.clear(); for (const auto& v : j["image_base_candidates"]) { if (v.is_string()) c.image_bases.push_back(std::strtoull(v.get<std::string>().c_str(), nullptr, 0)); }
        }
        if (j.contains("attach_delay")) c.attach_delay = j["attach_delay"];
        if (j.contains("update_interval")) c.update_interval = j["update_interval"];
        if (j.contains("poll_interval")) c.poll_interval = j["poll_interval"];
        if (j.contains("large_image")) c.large_image = j["large_image"];
        if (j.contains("small_image")) c.small_image = j["small_image"];
        if (j.contains("buttons") && j["buttons"].is_array()) c.buttons = j["buttons"];
        if (j.contains("offline_only")) c.offline_only = j["offline_only"];
        if (j.contains("user_dir") && j["user_dir"].is_string()) c.user_dir = j["user_dir"];
        if (j.contains("show")) {
            auto& s = j["show"];
            if (s.contains("level")) c.show_level = s["level"];
            if (s.contains("platinum")) c.show_platinum = s["platinum"];
        }
    } catch (...) {} return c;
}

class Process {
#ifdef _WIN32
    HANDLE h_ = nullptr;
#else
    int fd_ = -1;
#endif
public:
    Process() = default; Process(const Process&) = delete; Process& operator=(const Process&) = delete;
    Process(Process&& o) noexcept { move_from(o); }
    Process& operator=(Process&& o) noexcept { if (this != &o) { close(); move_from(o); } return *this; }
    ~Process() { close(); }
    bool open(int pid) {
        close();
#ifdef _WIN32
        h_ = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, (DWORD)pid);
        return h_ != nullptr;
#else
        if (pid <= 0) return false;
        const std::string path = "/proc/" + std::to_string(pid) + "/mem";
        fd_ = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
        return fd_ >= 0;
#endif
    }
    void close() {
#ifdef _WIN32
        if (h_) { CloseHandle(h_); h_ = nullptr; }
#else
        if (fd_ >= 0) { ::close(fd_); fd_ = -1; }
#endif
    }
    bool read(uintptr_t addr, void* buf, size_t size) const {
#ifdef _WIN32
        if (!h_) return false; SIZE_T got = 0;
        return ReadProcessMemory(h_, (LPCVOID)addr, buf, size, &got) && got == size;
#else
        if (fd_ < 0) return false;
        size_t done = 0;
        while (done < size) {
            const ssize_t n = ::pread(fd_, static_cast<char*>(buf) + done, size - done,
                                      static_cast<off_t>(addr + done));
            if (n <= 0) return false;
            done += static_cast<size_t>(n);
        }
        return true;
#endif
    }
    template <typename T> bool read(uintptr_t addr, T& out) const { return read(addr, &out, sizeof(T)); }
private:
    void move_from(Process& o) {
#ifdef _WIN32
        h_ = o.h_; o.h_ = nullptr;
#else
        fd_ = o.fd_; o.fd_ = -1;
#endif
    }
};

static std::vector<int> find_processes(const std::string& name) {
    std::vector<int> pids;
#ifdef _WIN32
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return pids;
    PROCESSENTRY32W pe{}; pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            if (_wcsicmp(pe.szExeFile, std::wstring(name.begin(), name.end()).c_str()) == 0)
                pids.push_back(static_cast<int>(pe.th32ProcessID));
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
#else
    std::string wanted = name;
    if (wanted.size() > 4 && wanted.compare(wanted.size() - 4, 4, ".exe") == 0)
        wanted.resize(wanted.size() - 4);
    DIR* dir = opendir("/proc");
    if (!dir) return pids;
    while (const dirent* entry = readdir(dir)) {
        if (!std::isdigit(static_cast<unsigned char>(entry->d_name[0]))) continue;
        const int pid = std::atoi(entry->d_name);
        std::ifstream comm("/proc/" + std::to_string(pid) + "/comm");
        std::string running; std::getline(comm, running);
        if (running == wanted) pids.push_back(pid);
    }
    closedir(dir);
#endif
    return pids;
}

static bool pid_alive(int pid, const std::string& name_hint = "") {
    if (pid <= 0) return false;
#ifdef _WIN32
    HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, (DWORD)pid);
    if (!h) return false;
    DWORD ec = 0; bool alive = GetExitCodeProcess(h, &ec) && ec == STILL_ACTIVE;
    if (alive && !name_hint.empty()) {
        wchar_t buf[MAX_PATH]; DWORD s = MAX_PATH;
        if (QueryFullProcessImageNameW(h, 0, buf, &s)) {
            fs::path p(std::wstring(buf, s));
            if (_wcsicmp(p.filename().c_str(), std::wstring(name_hint.begin(), name_hint.end()).c_str()) != 0) alive = false;
        }
    }
    CloseHandle(h);
    return alive;
#else
    if (kill(pid, 0) != 0 && errno == ESRCH) return false;
    if (!name_hint.empty()) {
        std::string wanted = name_hint;
        if (wanted.size() > 4 && wanted.compare(wanted.size() - 4, 4, ".exe") == 0)
            wanted.resize(wanted.size() - 4);
        std::ifstream comm("/proc/" + std::to_string(pid) + "/comm");
        std::string running; std::getline(comm, running);
        return running == wanted;
    }
    return true;
#endif
}

static uintptr_t find_base(const Process& p, const std::vector<uintptr_t>& bases) {
    for (auto b : bases) { uint8_t tmp[8]; if (p.read(b + GAME_DATA_MAN, tmp, sizeof(tmp))) return b; } return 0;
}

static uint32_t ReadCurrentMapId(const Process& p, uintptr_t base) {
    // The port's own chain (src/runtime_map.c, runtime_atlas_state.c):
    // WorldChrMan -> local ChrIns -> current block/map id.
    uint64_t man = 0;
    if (!p.read(base + WORLD_CHR_MAN, man) || !man || man < 0x10000) return 0;
    uint64_t chr = 0;
    if (!p.read(man + 0x60, chr) || !chr || chr < 0x10000) return 0;
    uint32_t block = 0;
    if (!p.read(chr + CHR_BLOCK, block) || block == 0xffffffffu) return 0;
    return block;
}

struct Stats { int level, insight, echoes, hp, maxhp; uint32_t map_id; std::string area_name; std::string boss_name; std::array<int, 6> attrs; };

static std::string GetBossName(const Process& p, uintptr_t base) {
    if (!BOSS_GAUGE_ADDR) return "";
    uint64_t gauge = 0; if (!p.read(base + BOSS_GAUGE_ADDR, gauge) || !gauge || gauge < 0x10000) return "";
    for (int i = 0; i < 3; ++i) {
        int32_t handle = -1; if (p.read(gauge + 0x165C + i * 0x14, handle) && handle != -1) {
            int32_t boss_id = -1; if (p.read(gauge + 0x1658 + i * 0x14, boss_id)) { if (const char* name = FindBbscName(BbscBossNames, boss_id)) return name; return "Unknown Boss"; }
        }
    } return "";
}

static std::optional<Stats> read_stats(const Process& p, uintptr_t base) {
    uint64_t gdm = 0; if (!p.read(base + GAME_DATA_MAN, gdm) || !gdm || gdm < 0x10000) return std::nullopt;
    uint64_t pgd = 0; if (!p.read(gdm + 8, pgd) || !pgd || pgd < 0x10000) return std::nullopt;
    uint8_t blk[PGD_READ_SIZE]; if (!p.read(pgd, blk, sizeof(blk))) return std::nullopt;
    auto i32 = [&](int off) { int32_t v; std::memcpy(&v, blk + off, 4); return v; };

    Stats s{};
    for (int i = 0; i < 6; ++i) s.attrs[i] = i32(PGD_ATTR_DEFS[i].off);
    for (int a : s.attrs) if (a < 1 || a > 99) return std::nullopt;

    // Bloodborne's level is not a fixed sum of the attributes: each origin has its own
    // starting level and stat total, so only the plausible range is a safe sanity gate.
    s.level = i32(PGD_LEVEL);
    if (s.level < 1 || s.level > 999) return std::nullopt;
    s.insight = i32(PGD_INSIGHT); s.echoes = i32(PGD_ECHOES); s.hp = i32(PGD_HP); s.maxhp = i32(PGD_MAXHP);

    if (s.insight < 0 || s.insight > 999 || s.echoes < 0 || s.echoes > 999999999 || s.maxhp <= 0 || s.maxhp >= 100000 || s.hp < 0 || s.hp > s.maxhp) return std::nullopt;

    s.map_id = ReadCurrentMapId(p, base);
    if (s.map_id != 0) s.area_name = GetAreaName(s.map_id);

    s.boss_name = GetBossName(p, base);
    return s;
}

class DiscordIpc {
#ifdef _WIN32
    HANDLE pipe_ = INVALID_HANDLE_VALUE;
#else
    int fd_ = -1;
#endif
public:
    ~DiscordIpc() { close(); }
    bool connected() const {
#ifdef _WIN32
        return pipe_ != INVALID_HANDLE_VALUE;
#else
        return fd_ >= 0;
#endif
    }
    void close() {
#ifdef _WIN32
        if (pipe_ != INVALID_HANDLE_VALUE) { CloseHandle(pipe_); pipe_ = INVALID_HANDLE_VALUE; }
#else
        if (fd_ >= 0) { ::close(fd_); fd_ = -1; }
#endif
    }
    bool connect_pipe(const std::string& client_id) {
        close();
#ifdef _WIN32
        for (int i = 0; i < 10; ++i) {
            std::wstring name = L"\\\\.\\pipe\\discord-ipc-" + std::to_wstring(i);
            pipe_ = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
            if (pipe_ != INVALID_HANDLE_VALUE) break;
        }
        if (pipe_ == INVALID_HANDLE_VALUE) return false;
#else
        std::vector<std::string> dirs;
        if (const char* runtime = std::getenv("XDG_RUNTIME_DIR"); runtime && *runtime) {
            dirs.push_back(runtime);
            dirs.push_back(std::string(runtime) + "/app/com.discordapp.Discord");
            dirs.push_back(std::string(runtime) + "/app/com.discordapp.DiscordCanary");
            dirs.push_back(std::string(runtime) + "/snap.discord");
        }
        if (const char* tmp = std::getenv("TMPDIR"); tmp && *tmp) dirs.push_back(tmp);
        dirs.push_back("/tmp");
        for (const auto& dir : dirs) {
            if (connected()) break;
            for (int i = 0; i < 10; ++i) {
                const std::string path = dir + "/discord-ipc-" + std::to_string(i);
                const int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
                if (fd < 0) continue;
                sockaddr_un addr{};
                addr.sun_family = AF_UNIX;
                if (path.size() >= sizeof(addr.sun_path)) { ::close(fd); continue; }
                std::strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
                if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0) { fd_ = fd; break; }
                ::close(fd);
            }
        }
        if (fd_ < 0) return false;
#endif
        const std::string hs = std::string("{\"v\":1,\"client_id\":\"") + client_id + "\"}";
        if (!send(0, hs)) { close(); return false; }
        return drain(true);
    }
    bool send(uint32_t opcode, const std::string& payload) {
        if (!connected()) return false;
        std::string frame(8, '\0');
        std::memcpy(&frame[0], &opcode, 4);
        const uint32_t len = static_cast<uint32_t>(payload.size());
        std::memcpy(&frame[4], &len, 4);
        frame += payload;
#ifdef _WIN32
        DWORD written = 0;
        return WriteFile(pipe_, frame.data(), static_cast<DWORD>(frame.size()), &written, nullptr)
               && written == frame.size();
#else
        size_t done = 0;
        while (done < frame.size()) {
            const ssize_t n = ::send(fd_, frame.data() + done, frame.size() - done, MSG_NOSIGNAL);
            if (n <= 0) return false;
            done += static_cast<size_t>(n);
        }
        return true;
#endif
    }
    bool drain(bool wait) {
        if (!connected()) return false;
        for (;;) {
#ifdef _WIN32
            DWORD avail = 0;
            if (!PeekNamedPipe(pipe_, nullptr, 0, nullptr, &avail, nullptr)) { close(); return false; }
            if (avail < 8 && !wait) return true;
            uint32_t hdr[2] = {0, 0}; DWORD got = 0;
            if (!ReadFile(pipe_, hdr, 8, &got, nullptr) || got != 8) { close(); return false; }
            std::string body(hdr[1], '\0');
            if (hdr[1] > 0 && (!ReadFile(pipe_, body.data(), hdr[1], &got, nullptr) || got != hdr[1])) { close(); return false; }
#else
            pollfd p{fd_, POLLIN, 0};
            const int ready = ::poll(&p, 1, wait ? 2000 : 0);
            if (ready <= 0) {
                if (!wait) return true;
                close();
                return false;
            }
            uint32_t hdr[2] = {0, 0};
            if (!recv_all(hdr, sizeof(hdr))) { close(); return false; }
            std::string body(hdr[1], '\0');
            if (hdr[1] > 0 && !recv_all(body.data(), hdr[1])) { close(); return false; }
#endif
            if (hdr[0] == 2) { close(); return false; }
            wait = false;
        }
    }
private:
#ifndef _WIN32
    bool recv_all(void* data, size_t size) {
        size_t done = 0;
        while (done < size) {
            const ssize_t n = ::recv(fd_, static_cast<char*>(data) + done, size - done, 0);
            if (n <= 0) return false;
            done += static_cast<size_t>(n);
        }
        return true;
    }
#endif
};

static fs::path trophy_user_dir(const Config& cfg) {
    if (!cfg.user_dir.empty()) return fs::path(cfg.user_dir);
    if (const char* env = std::getenv("BB_USER_DIR"); env && *env) return fs::path(env);
    return g_exe_dir / ".." / ".." / "user";
}

static bool all_trophies_earned(const Config& cfg) {
    try {
        const fs::path user = trophy_user_dir(cfg);
        std::ifstream meta_file(user / "trophy_cache" / "metadata.json");
        if (!meta_file) return false;
        json meta; meta_file >> meta;
        if (!meta.value("complete", false) || !meta.contains("entries") ||
            !meta["entries"].is_array() || meta["entries"].empty()) return false;
        std::set<int> earned;
        std::ifstream history(user / "trophies.txt");
        std::string line;
        while (std::getline(history, line)) {
            std::istringstream in(line);
            long long id = 0, stamp = 0;
            if (!(in >> id >> stamp)) continue;
            if (id >= 0 && id < 128 && stamp > 0) earned.insert(static_cast<int>(id));
        }
        bool any = false;
        for (const auto& entry : meta["entries"]) {
            if (!entry.is_object()) continue;
            const auto id = entry.find("id");
            if (id == entry.end() || !id->is_number_integer()) continue;
            any = true;
            if (!earned.count(id->get<int>())) return false;
        }
        return any;
    } catch (...) {
        return false;
    }
}

static bool platinum_earned(const Config& cfg) {
    static bool initialized = false, value = false;
    static clk::time_point checked{};
    const auto now = clk::now();
    if (initialized && now - checked < std::chrono::seconds(15)) return value;
    initialized = true;
    checked = now;
    value = all_trophies_earned(cfg);
    return value;
}

static json build_presence(const std::optional<Stats>& stats, const Config& cfg,
                           int64_t session_start_s) {
    json data; data["large_image"] = cfg.large_image; data["start"] = session_start_s;
    if (!cfg.small_image.empty()) data["small_image"] = cfg.small_image;
    if (cfg.buttons.is_array() && !cfg.buttons.empty()) { json btns = json::array(); int n = 0; for (const auto& b : cfg.buttons) { if (n++ >= 2) break; btns.push_back(b); } data["buttons"] = std::move(btns); }
    data["details"] = "Bloodborne";
    data["large_text"] = "Bloodborne";
    if (!stats) { data["state"] = "In the menus"; return data; }

    if (cfg.show_platinum && platinum_earned(cfg)) data["state"] = "Platinum Trophy Earned";
    else if (cfg.show_level) data["state"] = "Hunter Level " + std::to_string(stats->level);
    else data["state"] = "";
    return data;
}

static json to_discord_activity(const json& flat) {
    json a = json::object(); if (flat.contains("details")) a["details"] = flat["details"]; if (flat.contains("state")) a["state"] = flat["state"]; if (flat.contains("start")) a["timestamps"] = {{"start", (int64_t)flat["start"] * 1000}};
    json assets = json::object(); if (flat.contains("large_image")) assets["large_image"] = flat["large_image"]; if (flat.contains("large_text")) assets["large_text"] = flat["large_text"]; if (!assets.empty()) a["assets"] = std::move(assets); return a;
}

static void probe_mode(const Config& cfg) {
    auto pids = find_processes(cfg.process_name);
    if (pids.empty()) { log("Process " + cfg.process_name + " is not running."); return; }
    log("Found " + std::to_string(pids.size()) + " process(es) named " + cfg.process_name);
    for (int pid : pids) {
        Process p; if (!p.open(pid)) { log("PID " + std::to_string(pid) + ": Access denied."); continue; }
        uintptr_t base = find_base(p, cfg.image_bases);
        if (!base) { log("PID " + std::to_string(pid) + ": Base not found."); continue; }
        log("PID " + std::to_string(pid) + ": Base found at " + hex(base) + " (MATCH!)");

        auto stats = read_stats(p, base);
        if (!stats) { log("  -> Stats: null (Menus)."); continue; }
        log("  -> Level: " + std::to_string(stats->level) + " | Echoes: " + std::to_string(stats->echoes));
        log("  -> Map ID: " + hex(stats->map_id) + " (" + stats->area_name + ")");
        log("  -> Boss: " + (stats->boss_name.empty() ? "None" : stats->boss_name));
    }
}

static void run(const Config& cfg) {
    if (cfg.client_id.empty() || !std::all_of(cfg.client_id.begin(), cfg.client_id.end(), ::isdigit)) { fatal("Config Error: client_id missing."); return; }
    const bool companion = [] { const char* pid = std::getenv("BB_GAME_PID"); return pid && *pid && std::all_of(pid, pid + std::strlen(pid), ::isdigit); }();
    const int companion_pid = companion ? (int)std::strtol(std::getenv("BB_GAME_PID"), nullptr, 10) : 0;
    if (companion) log("Companion Mode: Watching game PID " + std::to_string(companion_pid)); else log("Standalone Mode: Waiting for " + cfg.process_name + " ...");
    const auto poll = std::chrono::milliseconds((int)(std::max(0.25, std::min(5.0, cfg.poll_interval)) * 1000));
    const int update_interval = std::max(15, cfg.update_interval); const std::string check_name = companion ? "" : cfg.process_name;

    while (true) {
        int pid = companion_pid;
        if (!companion) {
            auto pids = find_processes(cfg.process_name);
            pid = 0;
            for (int candidate : pids) { Process tp; if (tp.open(candidate) && find_base(tp, cfg.image_bases)) { pid = candidate; break; } }
        }
        if (companion && !pid_alive(pid)) { log("Game process closed, exiting."); return; }
        if (!pid) { std::this_thread::sleep_for(std::chrono::seconds(3)); continue; }
        std::this_thread::sleep_for(std::chrono::seconds(cfg.attach_delay));
        if (companion && !pid_alive(pid)) { log("Game closed before attachment, exiting."); return; }
        Process proc; if (!proc.open(pid)) { log("Failed to open process memory. Retrying..."); std::this_thread::sleep_for(std::chrono::seconds(10)); continue; }
        uintptr_t base = find_base(proc, cfg.image_bases); if (!base) { log("Game memory not ready. Retrying..."); std::this_thread::sleep_for(std::chrono::seconds(5)); continue; }
        DiscordIpc discord;
        int failures = 0;
        while (pid_alive(pid, check_name)) {
            if (discord.connect_pipe(cfg.client_id)) break;
            if (failures++ % 12 == 0) log("Failed to connect to Discord. Retrying in 5s...");
            std::this_thread::sleep_for(std::chrono::seconds(5));
        }
        log("Attached to PID " + std::to_string(pid) + " (Base: " + hex(base) + ")");
        const int64_t start_s = (int64_t)std::time(nullptr); json last_payload; auto last_sent = clk::time_point{};
        while (pid_alive(pid, check_name)) {
            if (!discord.connected()) { if (!discord.connect_pipe(cfg.client_id)) { std::this_thread::sleep_for(std::chrono::seconds(5)); continue; } }
            discord.drain(false); if (!discord.connected()) continue;
            auto stats = read_stats(proc, base); json payload = build_presence(stats, cfg, start_s); auto now = clk::now();
            if (payload != last_payload && (now - last_sent) >= std::chrono::seconds(update_interval)) {
                json cmd = { {"cmd", "SET_ACTIVITY"}, {"args", {{"pid", pid}, {"activity", to_discord_activity(payload)}}}, {"nonce", std::to_string((uint64_t)now.time_since_epoch().count())} };
                if (discord.send(1, cmd.dump())) { last_payload = payload; last_sent = now; log("Presence Updated: " + payload.value("details", std::string()) + " | " + payload.value("state", std::string())); } else discord.close();
            }
            std::this_thread::sleep_for(poll);
        }
        if (discord.connected()) { json cmd = {{"cmd", "SET_ACTIVITY"}, {"args", {{"pid", pid}}}, {"nonce", "0"}}; discord.send(1, cmd.dump()); }
        log("Game closed. Cleaning up presence."); if (companion) return; log("Waiting for game again...");
    }
}

static bool has_flag(int argc, char** argv) {
#ifdef _WIN32
    (void)argc; (void)argv;
    return wcsstr(GetCommandLineW(), L"--probe") != nullptr;
#else
    for (int i = 1; i < argc; ++i) if (std::strcmp(argv[i], "--probe") == 0) return true;
    return false;
#endif
}

static int app_main(int argc, char** argv) {
    g_exe_dir = exe_directory();
    const Config cfg = load_config(g_exe_dir / "config.json");
    if (has_flag(argc, argv)) { probe_mode(cfg); return 0; }
    run(cfg);
    return 0;
}

#ifdef _WIN32
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) { return app_main(0, nullptr); }
#else
int main(int argc, char** argv) { return app_main(argc, argv); }
#endif

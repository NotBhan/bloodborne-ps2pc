// SPDX-License-Identifier: GPL-2.0-or-later
#include "bbport_trophies.h"

#include "common/aes.h"
#include <boost/property_tree/ptree.hpp>
#include <boost/property_tree/xml_parser.hpp>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <regex>
#include <sstream>

namespace BbTrophies {
namespace {
namespace fs = std::filesystem;
using json = nlohmann::json;

constexpr int kTargetScore = 1000;
constexpr int kScoreStep = 5;
constexpr int kBronzeWeight = 1;
constexpr int kSilverWeight = 3;
constexpr int kGoldWeight = 6;
constexpr int kPlatinumWeight = 12;
constexpr std::size_t kMaxEntryBytes = 2 * 1024 * 1024;
constexpr int kCacheVersion = 2;
std::mutex mutex;
std::vector<Entry> entries;
bool complete_metadata = false;
std::string game_title;
std::string game_description;
std::array<std::int64_t, 128> unlocks{};

int Weight(Grade grade) {
    switch (grade) {
    case Grade::Bronze: return kBronzeWeight;
    case Grade::Silver: return kSilverWeight;
    case Grade::Gold: return kGoldWeight;
    case Grade::Platinum: return kPlatinumWeight;
    default: return 0;
    }
}
int FixedScore(Grade grade) {
    switch (grade) {
    case Grade::Bronze: return 10;
    case Grade::Silver: return 25;
    case Grade::Gold: return 50;
    case Grade::Platinum: return 100;
    default: return -1;
    }
}
char GradeCode(Grade grade) {
    switch (grade) {
    case Grade::Bronze: return 'B';
    case Grade::Silver: return 'S';
    case Grade::Gold: return 'G';
    case Grade::Platinum: return 'P';
    default: return '?';
    }
}
Grade ParseGrade(const std::string& value) {
    if (value == "B") return Grade::Bronze;
    if (value == "S") return Grade::Silver;
    if (value == "G") return Grade::Gold;
    if (value == "P") return Grade::Platinum;
    return Grade::Unknown;
}
std::uint32_t Be32(const unsigned char* p) {
    return (std::uint32_t(p[0]) << 24) | (std::uint32_t(p[1]) << 16) |
           (std::uint32_t(p[2]) << 8) | p[3];
}
std::uint64_t Be64(const unsigned char* p) {
    return (std::uint64_t(Be32(p)) << 32) | Be32(p + 4);
}
std::string ReadFile(const fs::path& path, std::size_t max_bytes) {
    std::error_code ec;
    const auto size = fs::file_size(path, ec);
    if (ec || size > max_bytes) return {};
    std::ifstream file(path, std::ios::binary);
    if (!file) return {};
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}
bool WriteFile(const fs::path& path, const std::string& data) {
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    file.write(data.data(), std::streamsize(data.size()));
    return bool(file);
}
std::string NpCommId(const fs::path& game_dir) {
    const auto data = ReadFile(game_dir / "sce_sys" / "npbind.dat", 64 * 1024);
    const std::regex pattern("NPWR[0-9]{5}_[0-9]{2}");
    std::smatch match;
    if (std::regex_search(data, match, pattern)) return match.str();
    return {};
}
std::array<unsigned char, 16> ReadKey(const fs::path& user_dir, bool& valid) {
    valid = false;
    std::array<unsigned char, 16> result{};
    try {
        const auto data = ReadFile(user_dir / "keys.json", 64 * 1024);
        if (data.empty()) return result;
        const auto root = json::parse(data);
        const auto hex = root.at("TrophyKeySet").at("ReleaseTrophyKey").get<std::string>();
        if (hex.size() != 32) return result;
        for (std::size_t i = 0; i < 16; ++i) {
            const auto byte = hex.substr(i * 2, 2);
            if (!std::isxdigit(static_cast<unsigned char>(byte[0])) ||
                !std::isxdigit(static_cast<unsigned char>(byte[1]))) return result;
            result[i] = static_cast<unsigned char>(std::stoul(byte, nullptr, 16));
        }
        valid = true;
    } catch (...) {
        // Invalid or absent user key leaves metadata unavailable, not the game unusable.
    }
    return result;
}
struct TrpEntry {
    std::string name;
    std::uint64_t offset = 0, size = 0;
    std::uint32_t flag = 0;
};
std::vector<TrpEntry> ReadDirectory(std::ifstream& file, std::uint64_t file_size) {
    unsigned char header[96]{};
    file.seekg(0);
    if (!file.read(reinterpret_cast<char*>(header), sizeof(header)) ||
        Be32(header) != 0xDCA24D00) return {};
    const auto count = Be32(header + 16), stride = Be32(header + 20);
    if (count == 0 || count > 512 || stride < 64 || stride > 4096 ||
        std::uint64_t(count) * stride > file_size - std::min<std::uint64_t>(96, file_size)) return {};
    std::vector<TrpEntry> result;
    for (std::uint32_t i = 0; i < count; ++i) {
        unsigned char record[64]{};
        file.seekg(96 + std::uint64_t(i) * stride);
        if (!file.read(reinterpret_cast<char*>(record), sizeof(record))) return {};
        const auto end = std::find(record, record + 32, 0);
        if (end == record + 32) continue;
        TrpEntry entry{std::string(reinterpret_cast<char*>(record),
                                   std::size_t(end - record)), Be64(record + 32),
                       Be64(record + 40), Be32(record + 48)};
        if (entry.size > kMaxEntryBytes || entry.offset > file_size ||
            entry.size > file_size - entry.offset) continue;
        result.push_back(std::move(entry));
    }
    return result;
}
std::string ReadEntry(std::ifstream& file, const TrpEntry& entry) {
    std::string bytes(entry.size, '\0');
    file.clear();
    file.seekg(entry.offset);
    if (!file.read(bytes.data(), std::streamsize(bytes.size()))) return {};
    return bytes;
}
std::string DecryptXml(const std::string& data, const std::array<unsigned char, 16>& key,
                       const std::string& np_comm_id) {
    if (np_comm_id.size() != 12 || data.size() <= 16 || (data.size() - 16) % 16) return {};
    std::array<unsigned char, 16> padded_id{}, trp_key{}, zero_iv{};
    std::copy(np_comm_id.begin(), np_comm_id.end(), padded_id.begin());
    if (aes::encrypt_cbc(padded_id.data(), 16, key.data(), 16, zero_iv.data(),
                         trp_key.data(), 16, false) != aes::kErrorOk) return {};
    std::string xml(data.size() - 16, '\0');
    if (aes::decrypt_cbc(reinterpret_cast<const unsigned char*>(data.data() + 16),
                         data.size() - 16, trp_key.data(), 16,
                         reinterpret_cast<const unsigned char*>(data.data()),
                         reinterpret_cast<unsigned char*>(xml.data()), xml.size(), nullptr) !=
        aes::kErrorOk) return {};
    const auto end = xml.rfind('>');
    if (end == std::string::npos) return {};
    xml.resize(end + 1);
    return xml;
}
bool ParseXml(const std::string& xml, std::vector<Entry>& found) {
    try {
        boost::property_tree::ptree tree;
        std::istringstream stream(xml);
        boost::property_tree::read_xml(stream, tree,
                                       boost::property_tree::xml_parser::trim_whitespace);
        unsigned parsed = 0;
        const auto& conf = tree.get_child("trophyconf");
        game_title = conf.get<std::string>("title-name", "");
        game_description = conf.get<std::string>("title-detail", "");
        for (const auto& [tag, node] : conf) {
            if (tag != "trophy") continue;
            const auto id = node.get<int>("<xmlattr>.id", -1);
            if (id < 0 || id >= 128) continue;
            auto it = std::find_if(found.begin(), found.end(),
                                   [id](const Entry& entry) { return entry.id == id; });
            if (it == found.end()) { found.push_back(Entry{}); it = std::prev(found.end()); }
            it->id = id;
            it->name = node.get<std::string>("name", "Trophy #" + std::to_string(id));
            it->description = node.get<std::string>("detail", "");
            it->grade = ParseGrade(node.get<std::string>("<xmlattr>.ttype", ""));
            const auto hidden = node.get<std::string>("<xmlattr>.hidden", "false");
            it->hidden = hidden == "true" || hidden == "1";
            ++parsed;
        }
        return parsed > 0;
    } catch (...) { return false; }
}
fs::path TrpPath(const fs::path& game_dir) {
    const auto dir = game_dir / "sce_sys" / "trophy";
    for (const auto& name : {"trophy00.trp", "TROPHY.TRP"}) {
        const auto path = dir / name;
        if (fs::is_regular_file(path)) return path;
    }
    return {};
}
std::string ChosenXmlName(int language, const std::vector<TrpEntry>& directory) {
    char local[32];
    std::snprintf(local, sizeof(local), "TROP_%02d.ESFM", language);
    for (const auto& candidate : {std::string(local), std::string("TROP_01.ESFM"),
                                  std::string("TROP.ESFM")}) {
        for (const auto& entry : directory)
            if (entry.name == candidate && entry.flag == 3) return candidate;
    }
    return {};
}
void AttachUnlocks(std::vector<Entry>& found) {
    for (auto& entry : found)
        if (entry.id >= 0 && entry.id < int(unlocks.size())) entry.unlocked_at = unlocks[entry.id];
}
std::vector<Entry> Extract(std::ifstream& file, const std::vector<TrpEntry>& directory,
                           const fs::path& cache_dir, int language,
                           const std::array<unsigned char, 16>& key, bool has_key,
                           const std::string& np_comm_id, bool& complete) {
    std::vector<Entry> found;
    std::error_code ec;
    fs::create_directories(cache_dir / "icons", ec);
    const std::regex icon_name("TROP([0-9]{3})\\.PNG", std::regex::icase);
    for (const auto& item : directory) {
        std::smatch match;
        if (item.flag != 0 || !std::regex_match(item.name, match, icon_name)) continue;
        const int id = std::stoi(match[1].str());
        if (id < 0 || id >= 128) continue;
        const auto icon = cache_dir / "icons" / item.name;
        const auto bytes = ReadEntry(file, item);
        if (bytes.size() < 8 || bytes.compare(0, 8, "\x89PNG\r\n\x1a\n", 8) != 0 ||
            !WriteFile(icon, bytes)) continue;
        Entry entry;
        entry.id = id;
        entry.name = "Trophy #" + std::to_string(id);
        entry.icon = icon;
        found.push_back(std::move(entry));
    }
    if (has_key && !np_comm_id.empty()) {
        const auto selected = ChosenXmlName(language, directory);
        for (const auto& item : directory) {
            if (item.name != selected || item.flag != 3) continue;
            const auto xml = DecryptXml(ReadEntry(file, item), key, np_comm_id);
            if (!xml.empty()) complete = ParseXml(xml, found);
            break;
        }
    }
    std::sort(found.begin(), found.end(), [](const Entry& a, const Entry& b) { return a.id < b.id; });
    AssignScores(found);
    return found;
}
} // namespace

void AssignScores(std::vector<Entry>& found) {
    int weight_sum = 0, platinum_index = -1;
    bool all_known = !found.empty();
    for (std::size_t i = 0; i < found.size(); ++i) {
        const int weight = Weight(found[i].grade);
        if (!weight) all_known = false;
        weight_sum += weight;
        if (found[i].grade == Grade::Platinum) platinum_index = int(i);
    }
    if (!all_known || !weight_sum || platinum_index < 0) {
        for (auto& entry : found) entry.score = FixedScore(entry.grade);
        return;
    }
    int total = 0;
    for (auto& entry : found) {
        const double share = double(kTargetScore) * Weight(entry.grade) / weight_sum;
        entry.score = int(share / kScoreStep + 0.5) * kScoreStep;
        total += entry.score;
    }
    found[platinum_index].score += kTargetScore - total;
}

void Configure(const fs::path& game_dir, const fs::path& user_dir, int language) {
    std::scoped_lock lock{mutex};
    entries.clear();
    complete_metadata = false;
    game_title.clear();
    game_description.clear();
    try {
        const auto trp = TrpPath(game_dir);
        if (trp.empty()) {
            std::fprintf(stderr, "Trophies: no trophy pack under %s/sce_sys/trophy\n",
                         game_dir.string().c_str());
            return;
        }
        const auto size = fs::file_size(trp);
        const auto modified = fs::last_write_time(trp).time_since_epoch().count();
        const auto cache_dir = user_dir / "trophy_cache";
        const auto cache_file = cache_dir / "metadata.json";
        bool has_key = false;
        const auto key = ReadKey(user_dir, has_key);
        if (!has_key) {
            std::fprintf(stderr, "Trophies: no trophy key in %s/keys.json; showing IDs only\n",
                         user_dir.string().c_str());
        }
        const auto cached = ReadFile(cache_file, 512 * 1024);
        if (!cached.empty()) {
            try {
                const auto root = json::parse(cached);
                if (root.value("version", 0) == kCacheVersion &&
                    root.value("source_size", std::uint64_t(0)) == size &&
                    root.value("source_modified", std::int64_t(0)) == modified &&
                    root.value("language", -1) == language &&
                    (root.value("complete", false) || !has_key)) {
                    game_title = root.value("title", "");
                    game_description = root.value("description", "");
                    for (const auto& item : root.at("entries")) {
                        Entry entry;
                        entry.id = item.value("id", -1);
                        if (entry.id < 0 || entry.id >= 128) continue;
                        entry.name = item.value("name", "Trophy #" + std::to_string(entry.id));
                        entry.description = item.value("description", "");
                        entry.grade = ParseGrade(item.value("grade", "?"));
                        entry.hidden = item.value("hidden", false);
                        entry.score = item.value("score", -1);
                        auto icon_name = item.value("icon", "");
                        if (icon_name.empty()) {
                            char fallback[16];
                            std::snprintf(fallback, sizeof(fallback), "TROP%03d.PNG", entry.id);
                            icon_name = fallback;
                        }
                        const auto icon = cache_dir / "icons" / icon_name;
                        if (fs::is_regular_file(icon)) entry.icon = icon;
                        entries.push_back(std::move(entry));
                    }
                    complete_metadata = root.value("complete", false);
                    AttachUnlocks(entries);
                    return;
                }
            } catch (...) { /* Rebuild a malformed cache. */ }
        }
        std::ifstream file(trp, std::ios::binary);
        if (!file) return;
        const auto directory = ReadDirectory(file, size);
        if (directory.empty()) return;
        entries = Extract(file, directory, cache_dir, language, key, has_key,
                          NpCommId(game_dir), complete_metadata);
        AttachUnlocks(entries);
        if (!complete_metadata && has_key) {
            std::fprintf(stderr, "Trophies: could not decrypt the trophy XML; check npbind.dat "
                                 "and the ReleaseTrophyKey in keys.json\n");
        }
        std::error_code ec;
        fs::create_directories(cache_dir, ec);
        if (!ec) {
            json root = {{"version", kCacheVersion}, {"source_size", size},
                         {"source_modified", modified}, {"language", language},
                         {"complete", complete_metadata}, {"title", game_title},
                         {"description", game_description}, {"entries", json::array()}};
            for (const auto& entry : entries)
                root["entries"].push_back({{"id", entry.id}, {"name", entry.name},
                    {"description", entry.description}, {"grade", std::string(1, GradeCode(entry.grade))},
                    {"hidden", entry.hidden}, {"score", entry.score},
                    {"icon", entry.icon.empty() ? "" : entry.icon.filename().string()}});
            WriteFile(cache_file, root.dump(2));
        }
    } catch (...) {
        // Corrupt packs and filesystem failures never stop gameplay.
    }
}

void LoadUnlocks(const std::int64_t* timestamps, unsigned count) {
    std::scoped_lock lock{mutex};
    unlocks.fill(0);
    if (timestamps)
        for (unsigned i = 0; i < std::min<unsigned>(count, unlocks.size()); ++i)
            unlocks[i] = timestamps[i];
    AttachUnlocks(entries);
}
void Unlock(int id, std::int64_t timestamp) {
    if (id < 0 || id >= int(unlocks.size())) return;
    std::scoped_lock lock{mutex};
    unlocks[id] = timestamp;
    AttachUnlocks(entries);
}
std::vector<Entry> Entries() {
    std::scoped_lock lock{mutex};
    return entries;
}
Entry Find(int id) {
    std::scoped_lock lock{mutex};
    for (const auto& entry : entries) if (entry.id == id) return entry;
    Entry fallback;
    fallback.id = id;
    fallback.name = "Trophy #" + std::to_string(id);
    if (id >= 0 && id < int(unlocks.size())) fallback.unlocked_at = unlocks[id];
    return fallback;
}
bool HasMetadata() { std::scoped_lock lock{mutex}; return complete_metadata; }
int EarnedScore() {
    std::scoped_lock lock{mutex};
    int score = 0;
    for (const auto& entry : entries)
        if (entry.unlocked_at && entry.score > 0) score += entry.score;
    return score;
}
int TotalScore() {
    std::scoped_lock lock{mutex};
    if (!complete_metadata) return -1;
    int score = 0;
    for (const auto& entry : entries) if (entry.score > 0) score += entry.score;
    return score;
}

Summary GetSummary() {
    std::scoped_lock lock{mutex};
    Summary summary;
    summary.title = game_title;
    summary.description = game_description;
    summary.num_trophies = int(entries.size());
    for (const auto& entry : entries) {
        switch (entry.grade) {
        case Grade::Platinum: ++summary.num_platinum; summary.platinum_id = entry.id; break;
        case Grade::Gold: ++summary.num_gold; break;
        case Grade::Silver: ++summary.num_silver; break;
        case Grade::Bronze: ++summary.num_bronze; break;
        default: break;
        }
        if (!entry.unlocked_at) {
            if (entry.grade != Grade::Platinum) ++summary.base_locked;
            continue;
        }
        ++summary.unlocked_trophies;
        switch (entry.grade) {
        case Grade::Platinum: ++summary.unlocked_platinum; break;
        case Grade::Gold: ++summary.unlocked_gold; break;
        case Grade::Silver: ++summary.unlocked_silver; break;
        case Grade::Bronze: ++summary.unlocked_bronze; break;
        default: break;
        }
    }
    if (summary.num_trophies > 0)
        summary.progress_percentage = summary.unlocked_trophies * 100 / summary.num_trophies;
    return summary;
}

bool IsUnlocked(int id) {
    std::scoped_lock lock{mutex};
    return id >= 0 && id < int(unlocks.size()) && unlocks[id] != 0;
}
} // namespace BbTrophies

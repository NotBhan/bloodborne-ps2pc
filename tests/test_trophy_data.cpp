#include "bbport_trophies.h"
#include "common/aes.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

static void Be32(std::string& data, std::size_t offset, std::uint32_t value) {
    for (int i = 3; i >= 0; --i) { data[offset + i] = char(value); value >>= 8; }
}
static void Be64(std::string& data, std::size_t offset, std::uint64_t value) {
    Be32(data, offset, std::uint32_t(value >> 32));
    Be32(data, offset + 4, std::uint32_t(value));
}
static void Write(const fs::path& path, const std::string& data) {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary);
    out.write(data.data(), std::streamsize(data.size()));
    assert(out.good());
}
static std::string EncryptXml(std::string xml, const std::array<unsigned char, 16>& key) {
    while (xml.size() % 16) xml.push_back(' ');
    std::array<unsigned char, 16> id{}, derived{}, zero{}, iv{};
    std::copy_n("NPWR05818_00", 12, id.begin());
    assert(aes::encrypt_cbc(id.data(), 16, key.data(), 16, zero.data(),
                            derived.data(), 16, false) == aes::kErrorOk);
    std::fill(iv.begin(), iv.end(), 7);
    std::string encrypted(xml.size(), '\0');
    assert(aes::encrypt_cbc(reinterpret_cast<const unsigned char*>(xml.data()), xml.size(),
                            derived.data(), 16, iv.data(),
                            reinterpret_cast<unsigned char*>(encrypted.data()),
                            encrypted.size(), false) == aes::kErrorOk);
    return std::string(reinterpret_cast<const char*>(iv.data()), iv.size()) + encrypted;
}
int main(int argc, char** argv) {
    assert(argc >= 2 && argc <= 4);
    const fs::path root = fs::path(argv[1]) / "trophy-data-fixture";
    const auto game = root / "game", user = root / "user";
    std::error_code ec;
    fs::remove_all(root, ec);
    const std::array<unsigned char, 16> key{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15};
    const std::string xml_en = "<trophyconf><trophy id=\"0\" ttype=\"B\" hidden=\"false\"><name>First</name><detail>Do it</detail></trophy><trophy id=\"1\" ttype=\"P\" hidden=\"true\"><name>Secret</name><detail>Finish it</detail></trophy></trophyconf>";
    const std::string xml_fr = "<trophyconf><trophy id=\"0\" ttype=\"B\" hidden=\"false\"><name>Premier</name><detail>Faire</detail></trophy><trophy id=\"1\" ttype=\"P\" hidden=\"true\"><name>Secret FR</name><detail>Terminer</detail></trophy></trophyconf>";
    const std::string png = "\x89PNG\r\n\x1a\n";
    const std::vector<std::pair<std::string, std::string>> files{
        {"TROP000.PNG", png}, {"TROP001.PNG", png},
        {"TROP_01.ESFM", EncryptXml(xml_en, key)},
        {"TROP_02.ESFM", EncryptXml(xml_fr, key)}};
    std::string trp(96 + files.size() * 64, '\0');
    Be32(trp, 0, 0xDCA24D00);
    Be32(trp, 4, 3);
    Be32(trp, 16, std::uint32_t(files.size()));
    Be32(trp, 20, 64);
    for (std::size_t i = 0; i < files.size(); ++i) {
        const auto at = 96 + i * 64;
        std::copy(files[i].first.begin(), files[i].first.end(), trp.begin() + at);
        Be64(trp, at + 32, trp.size());
        Be64(trp, at + 40, files[i].second.size());
        Be32(trp, at + 48, i < 2 ? 0 : 3);
        trp += files[i].second;
    }
    Be64(trp, 8, trp.size());
    Write(game / "sce_sys/trophy/trophy00.trp", trp);
    Write(game / "sce_sys/npbind.dat", "NPWR05818_00");
    Write(user / "keys.json",
          R"({"TrophyKeySet":{"ReleaseTrophyKey":"000102030405060708090a0b0c0d0e0f"}})");

    BbTrophies::Configure(game, user, 1);
    assert(BbTrophies::HasMetadata());
    auto first = BbTrophies::Find(0), platinum = BbTrophies::Find(1);
    assert(first.name == "First" && first.description == "Do it");
    assert(first.grade == BbTrophies::Grade::Bronze && first.score == 75);
    assert(platinum.hidden && platinum.score == 925 && BbTrophies::TotalScore() == 1000);
    assert(fs::is_regular_file(first.icon));
    auto summary = BbTrophies::GetSummary();
    assert(summary.num_trophies == 2 && summary.num_bronze == 1 && summary.num_platinum == 1);
    assert(summary.platinum_id == 1 && summary.base_locked == 1 && summary.progress_percentage == 0);
    std::array<std::int64_t, 128> timestamps{};
    timestamps[0] = 1700000000;
    BbTrophies::LoadUnlocks(timestamps.data(), timestamps.size());
    assert(BbTrophies::Find(0).unlocked_at == timestamps[0] && BbTrophies::EarnedScore() == 75);
    assert(BbTrophies::IsUnlocked(0) && !BbTrophies::IsUnlocked(1));
    summary = BbTrophies::GetSummary();
    assert(summary.unlocked_bronze == 1 && summary.base_locked == 0 && summary.progress_percentage == 50);
    BbTrophies::Unlock(1, 1700000001);
    assert(BbTrophies::EarnedScore() == 1000 && BbTrophies::GetSummary().progress_percentage == 100);
    fs::remove(user / "keys.json");
    BbTrophies::Configure(game, user, 1);
    assert(BbTrophies::HasMetadata() && BbTrophies::Find(0).name == "First");
    BbTrophies::Configure(game, user, 2);
    assert(!BbTrophies::HasMetadata() && BbTrophies::Find(0).name == "Trophy #0");
    Write(user / "keys.json",
          R"({"TrophyKeySet":{"ReleaseTrophyKey":"000102030405060708090a0b0c0d0e0f"}})");
    BbTrophies::Configure(game, user, 2);
    assert(BbTrophies::HasMetadata() && BbTrophies::Find(0).name == "Premier");
    std::vector<BbTrophies::Entry> incomplete(2);
    incomplete[0].id = 0;
    incomplete[0].grade = BbTrophies::Grade::Bronze;
    incomplete[1].id = 1;
    BbTrophies::AssignScores(incomplete);
    assert(incomplete[0].score == 10 && incomplete[1].score == -1);
    if (argc >= 3) {
        const auto actual_user = root / "actual-user";
        if (argc == 4) {
            fs::create_directories(actual_user);
            fs::copy_file(argv[3], actual_user / "keys.json",
                          fs::copy_options::overwrite_existing);
        }
        BbTrophies::Configure(argv[2], actual_user, 1);
        const auto actual = BbTrophies::Entries();
        assert(!actual.empty());
        assert(BbTrophies::HasMetadata() == (argc == 4));
        for (const auto& entry : actual) {
            assert(entry.id >= 0 && entry.id < 128);
            assert(!entry.icon.empty() && fs::is_regular_file(entry.icon));
            if (argc == 4) {
                assert(entry.grade != BbTrophies::Grade::Unknown);
                assert(entry.score >= 0 && entry.name != "Trophy #" + std::to_string(entry.id));
            } else assert(entry.score == -1);
        }
        if (argc == 4) assert(BbTrophies::TotalScore() == 1000);
        std::cout << "real pack: " << actual.size() << " icons, metadata="
                  << BbTrophies::HasMetadata() << ", total=" << BbTrophies::TotalScore() << "G\n";
    }
    fs::remove_all(root, ec);
    std::cout << "trophy data: TRP icons, decryption, language, cache, timestamps, 1000G passed\n";
}

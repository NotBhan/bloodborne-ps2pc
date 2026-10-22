// SPDX-License-Identifier: GPL-2.0-or-later
// Local trophy metadata. Game data and user keys are read only; derived data lives in user/trophy_cache.
#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace BbTrophies {

enum class Grade { Unknown, Bronze, Silver, Gold, Platinum };
struct Entry {
    int id = -1;
    std::string name;
    std::string description;
    Grade grade = Grade::Unknown;
    bool hidden = false;
    int score = -1; // -1 means the grade is not known yet.
    std::filesystem::path icon;
    std::int64_t unlocked_at = 0;
};

// Safe to call without a key or even a trophy pack. Never writes into game_dir.
void Configure(const std::filesystem::path& game_dir, const std::filesystem::path& user_dir,
               int language);
void LoadUnlocks(const std::int64_t* timestamps, unsigned count);
void Unlock(int id, std::int64_t timestamp);
std::vector<Entry> Entries();
Entry Find(int id);
bool HasMetadata();
int EarnedScore();
int TotalScore();

struct Summary {
    int num_trophies = 0;
    int num_platinum = 0;
    int num_gold = 0;
    int num_silver = 0;
    int num_bronze = 0;
    int unlocked_trophies = 0;
    int unlocked_platinum = 0;
    int unlocked_gold = 0;
    int unlocked_silver = 0;
    int unlocked_bronze = 0;
    int progress_percentage = -1;
    int platinum_id = -1;
    int base_locked = 0;
    std::string title;
    std::string description;
};
Summary GetSummary();
bool IsUnlocked(int id);

// Pure score calculation, also used by the fixture test.
void AssignScores(std::vector<Entry>& entries);

} // namespace BbTrophies

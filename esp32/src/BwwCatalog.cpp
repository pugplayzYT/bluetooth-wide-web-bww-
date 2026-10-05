#include "BwwCore.h"
#include <algorithm>
namespace bww {
namespace {
std::string pagePath(size_t page, int slot) {
    return "/bww/catalog/" + std::to_string(page) + "-" + std::to_string(slot) + ".json";
}
}
bool Core::spaceFor(uint64_t bytes) {
    uint64_t free = storage_.freeBytes();
    return free >= SD_RESERVE_BYTES && bytes <= free - SD_RESERVE_BYTES;
}
bool Core::discardFuturePages(uint64_t generation) {
    DynamicJsonDocument page(CATALOG_CAPACITY); bool good = page.capacity() == CATALOG_CAPACITY;
    if (!good) return false;
    bool scanned = storage_.visitFiles("/bww/catalog", [&](const std::string& path) {
        if (!good || path.size() < 8 || path.substr(path.size() - 8) != ".json.ok") return;
        if (!storage_.readJson(path.substr(0, path.size() - 3), page) || !page["generation"].is<uint64_t>()) { good = false; return; }
        if (page["generation"].as<uint64_t>() > generation && !storage_.remove(path)) good = false;
    });
    return scanned && good;
}
bool Core::loadPage(size_t page, uint64_t generation, JsonDocument& doc, int* selected) {
    pageReadError_ = true;
    doc.clear(); bool found = false; uint64_t best = 0;
    DynamicJsonDocument candidate(CATALOG_CAPACITY);
    if (candidate.capacity() != CATALOG_CAPACITY) return false;
    for (int slot = 0; slot < 3; ++slot) {
        auto path = pagePath(page, slot); std::string proof;
        // A missing proof marks an interrupted, uncommitted page write.
        if (!storage_.exists(path + ".ok")) continue;
        if (!storage_.readBytes(path + ".ok", 64, proof)) return false;
        if (proof.size() != 64) continue; // Interrupted proof write is not a sealed page.
        if (!storage_.readJson(path, candidate) ||
            candidate.overflowed() || !candidate["generation"].is<uint64_t>() ||
            !candidate["sites"].is<JsonArray>() || candidate["sites"].size() > CATALOG_PAGE_SITES ||
            !constantTimeEqual(proof, crypto_.jsonDigest(candidate.as<JsonVariantConst>()))) return false;
        uint64_t version = candidate["generation"];
        if (version <= generation && (!found || version > best)) {
            if (!doc.set(candidate.as<JsonVariantConst>())) return false;
            best = version; found = true; if (selected) *selected = slot;
        }
    }
    pageReadError_ = false;
    return found;
}
bool Core::writePage(size_t page, int slot, JsonDocument& doc) {
    // Account/deletion/recovery commits may use the reserved metadata space.
    // Upload admission reserves that space before accepting new site content.
    if (doc.overflowed() || storage_.freeBytes() < measureJson(doc) + 8192) return false;
    auto path = pagePath(page, slot), digest = crypto_.jsonDigest(doc.as<JsonVariantConst>());
    if (digest.size() != 64 || !storage_.remove(path + ".ok") || !storage_.writeJson(path, doc)) return false;
    {
        DynamicJsonDocument check(CATALOG_CAPACITY);
        if (check.capacity() != CATALOG_CAPACITY || !storage_.readJson(path, check) ||
            !constantTimeEqual(digest, crypto_.jsonDigest(check.as<JsonVariantConst>()))) return false;
    }
    if (!storage_.writeBytes(path + ".ok", digest)) { storage_.remove(path + ".ok"); return false; }
    for (JsonObjectConst record : doc["sites"].as<JsonArrayConst>())
        writeLookup(record["domain"].as<std::string>(), page);
    return true;
}
bool Core::writeLookup(const std::string& domain, size_t page) {
    auto path = "/bww/catalog/" + domain + ".lookup";
    StaticJsonDocument<512> link;
    if (storage_.exists(path)) {
        if (!storage_.readJson(path, link) || !link["page"].is<size_t>()) link.clear();
        if (link["page"].is<size_t>() && link["page"].as<size_t>() == page) return true;
        link["oldPage"] = link["page"];
    }
    link["domain"] = domain; link["page"] = page;
    // This is a disposable lookup accelerator; page proofs remain authoritative.
    return storage_.writeJson(path, link);
}
bool Core::lookupSite(JsonDocument& snapshot, const std::string& domain, JsonDocument& result) {
    result.clear();
    auto path = "/bww/catalog/" + domain + ".lookup";
    StaticJsonDocument<512> link;
    if (snapshot["siteCatalog"] == "paged-v1" && storage_.exists(path) && storage_.readJson(path, link) &&
        link["domain"] == domain && link["page"].is<size_t>()) {
        DynamicJsonDocument page(CATALOG_CAPACITY);
        if (page.capacity() != CATALOG_CAPACITY) return false;
        for (const char* key : {"page", "oldPage"}) {
            if (!link[key].is<size_t>() || link[key].as<size_t>() >= snapshot["catalogPages"].as<size_t>()) continue;
            if (!loadPage(link[key], snapshot["generation"], page)) return false;
            for (JsonObjectConst record : page["sites"].as<JsonArrayConst>())
                if (domain == record["domain"].as<const char*>()) return result.set(record);
        }
    }
    // Missing/interrupted accelerators can always be rebuilt by scanning pages.
    bool read = visitSites(snapshot, [&](JsonObjectConst record) {
        if (domain == record["domain"].as<const char*>()) result.set(record);
    });
    return read && !result.overflowed();
}
bool Core::visitSites(JsonDocument& snapshot, const std::function<void(JsonObjectConst)>& visitor) {
    if (snapshot["siteCatalog"] != "paged-v1") {
        for (JsonObjectConst record : snapshot["sites"].as<JsonArrayConst>()) visitor(record);
        return true;
    }
    DynamicJsonDocument page(CATALOG_CAPACITY);
    if (page.capacity() != CATALOG_CAPACITY) return false;
    for (size_t i = 0; i < snapshot["catalogPages"].as<size_t>(); ++i) {
        if (!loadPage(i, snapshot["generation"], page)) return false;
        for (JsonObjectConst record : page["sites"].as<JsonArrayConst>()) visitor(record);
    }
    return true;
}
bool Core::migrateCatalog() {
    if (state_["siteCatalog"] == "paged-v1") {
        DynamicJsonDocument page(CATALOG_CAPACITY);
        if (page.capacity() != CATALOG_CAPACITY) return false;
        for (size_t i = 0; i < state_["catalogPages"].as<size_t>(); ++i) {
            if (!loadPage(i, state_["generation"], page)) return false;
            if (spaceFor(8192)) for (JsonObjectConst record : page["sites"].as<JsonArrayConst>())
                writeLookup(record["domain"].as<std::string>(), i);
        }
        return true;
    }
    size_t pages = 0;
    {
        DynamicJsonDocument page(CATALOG_CAPACITY);
        if (page.capacity() != CATALOG_CAPACITY) return false;
        page["generation"] = state_["generation"].as<uint64_t>() + 1;
        auto records = page.createNestedArray("sites");
        for (JsonObjectConst record : state_["sites"].as<JsonArrayConst>()) {
            if (!records.add(record)) return false;
            if (records.size() == CATALOG_PAGE_SITES) {
                if (!writePage(pages++, 0, page)) return false;
                page.clear(); page["generation"] = state_["generation"].as<uint64_t>() + 1;
                records = page.createNestedArray("sites");
            }
        }
        if (records.size() && !writePage(pages++, 0, page)) return false;
    }
    state_.remove("sites"); state_.createNestedArray("sites"); state_["catalogRevision"] = state_["generation"].as<uint64_t>() + 1; state_["siteCatalog"] = "paged-v1"; state_["catalogPages"] = pages;
    return commit();
}
bool Core::storeSite(const std::string& domain, const std::string& owner, uint64_t revision, bool deleted) {
    size_t count = state_["catalogPages"], target = count, freePage = count;
    DynamicJsonDocument page(CATALOG_CAPACITY);
    if (page.capacity() != CATALOG_CAPACITY) return false;
    for (size_t i = 0; i < count; ++i) {
        if (!loadPage(i, state_["generation"], page)) return false;
        if (page["sites"].size() < CATALOG_PAGE_SITES && freePage == count) freePage = i;
        for (JsonObjectConst record : page["sites"].as<JsonArrayConst>())
            if (domain == record["domain"].as<const char*>()) { target = i; break; }
        if (target != count) break;
    }
    if (target == count) { if (deleted) return false; target = freePage; }
    writeLookup(domain, target);
    int current = -1, backup = -1;
    if (target < count) {
        if (!loadPage(target, state_["generation"], page, &current)) return false;
        // Protect both committed snapshots; a third slot receives the new page.
        {
            DynamicJsonDocument old(CATALOG_CAPACITY);
            if (!loadPage(target, backupGeneration_, old, &backup) && pageReadError_) return false;
        }
    } else { page.clear(); page.createNestedArray("sites"); }
    auto records = page["sites"].as<JsonArray>();
    for (size_t i = records.size(); i > 0; --i)
        if (domain == records[i - 1]["domain"].as<const char*>()) records.remove(i - 1);
    if (!deleted) {
        auto record = records.createNestedObject(); record["domain"] = domain;
        record["owner"] = owner; record["revision"] = revision;
    }
    page["generation"] = state_["generation"].as<uint64_t>() + 1;
    int slot = 0; while (slot == current || slot == backup) ++slot;
    if (slot >= 3 || !writePage(target, slot, page)) return false;
    state_["catalogRevision"] = state_["generation"].as<uint64_t>() + 1;
    if (target == count) state_["catalogPages"] = count + 1;
    return true;
}
}

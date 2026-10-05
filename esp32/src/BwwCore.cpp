#include "BwwCore.h"
#include <algorithm>
#include <cctype>
#include <set>
namespace bww {
namespace {
std::string slot(int number) { return "/bww/state-" + std::to_string(number) + ".json"; }
std::string trimLower(std::string value) {
    auto space = [](unsigned char c) { return std::isspace(c); };
    while (!value.empty() && space(value.front())) value.erase(value.begin());
    while (!value.empty() && space(value.back())) value.pop_back();
    for (char& c : value) if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
    return value;
}
bool asciiName(const std::string& value, size_t low, size_t high, bool user) {
    if (value.size() < low || value.size() > high) return false;
    for (char c : value) if (!(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && c != (user ? '_' : '-')) return false;
    return user || (value.front() != '-' && value.back() != '-');
}
bool field(JsonObjectConst r, const char* key, size_t max, std::string& out, JsonDocument& rpc) {
    if (!r[key].is<JsonString>()) { failure(rpc, "invalid_request", "A required string field is missing"); return false; }
    JsonString value = r[key].as<JsonString>();
    if (value.size() > max) { failure(rpc, "too_large", "Request field exceeds the device limit"); return false; }
    out.assign(value.c_str(), value.size());
    if (!validUtf8(out)) { failure(rpc, "invalid_request", "Strings must be valid UTF-8"); return false; }
    return true;
}
JsonObject success(JsonDocument& rpc) { rpc.clear(); rpc["ok"] = true; return rpc.createNestedObject("data"); }
JsonArray successArray(JsonDocument& rpc) { rpc.clear(); rpc["ok"] = true; return rpc.createNestedArray("data"); }
}
void failure(JsonDocument& rpc, const char* code, const char* message) {
    rpc.clear(); rpc["ok"] = false; rpc["error"] = code; rpc["message"] = message;
}
std::string hex(const uint8_t* bytes, size_t count) {
    static const char* digits = "0123456789abcdef";
    std::string result; result.reserve(count * 2);
    for (size_t i = 0; i < count; ++i) { result.push_back(digits[bytes[i] >> 4]); result.push_back(digits[bytes[i] & 15]); }
    return result;
}
bool unhex(const std::string& value, std::vector<uint8_t>& bytes) {
    if (value.size() % 2) return false;
    auto digit = [](char c) -> int { if (c >= '0' && c <= '9') return c - '0'; if (c >= 'a' && c <= 'f') return c - 'a' + 10; if (c >= 'A' && c <= 'F') return c - 'A' + 10; return -1; };
    bytes.clear();
    for (size_t i = 0; i < value.size(); i += 2) { int a = digit(value[i]), b = digit(value[i + 1]); if (a < 0 || b < 0) return false; bytes.push_back((a << 4) | b); }
    return true;
}
bool constantTimeEqual(const std::string& a, const std::string& b) {
    if (a.size() != b.size()) return false;
    unsigned difference = 0; for (size_t i = 0; i < a.size(); ++i) difference |= static_cast<unsigned char>(a[i]) ^ static_cast<unsigned char>(b[i]);
    return difference == 0;
}
bool validUtf8(const std::string& value, size_t* utf16Length) {
    size_t count = 0;
    for (size_t i = 0; i < value.size();) {
        uint8_t first = value[i++]; uint32_t code; size_t extra;
        if (first < 0x80) { code = first; extra = 0; }
        else if (first >= 0xc2 && first <= 0xdf) { code = first & 31; extra = 1; }
        else if (first >= 0xe0 && first <= 0xef) { code = first & 15; extra = 2; }
        else if (first >= 0xf0 && first <= 0xf4) { code = first & 7; extra = 3; }
        else return false;
        if (i + extra > value.size()) return false;
        for (size_t j = 0; j < extra; ++j) { uint8_t c = value[i++]; if ((c & 0xc0) != 0x80) return false; code = (code << 6) | (c & 63); }
        if ((extra == 1 && code < 0x80) || (extra == 2 && code < 0x800) || (extra == 3 && code < 0x10000) || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return false;
        count += code > 0xffff ? 2 : 1;
    }
    if (utf16Length) *utf16Length = count;
    return true;
}
bool canonicalDomain(const std::string& value, std::string& domain) {
    auto label = trimLower(value);
    if (label.size() >= 4 && label.substr(label.size() - 4) == ".bww") label.resize(label.size() - 4);
    if (!asciiName(label, 1, 63, false)) return false;
    domain = label + ".bww"; return true;
}
Core::Core(Storage& storage, Crypto& crypto) : storage_(storage), crypto_(crypto), state_(STATE_CAPACITY) {}
std::string Core::sitePath(JsonObjectConst record) const {
    return "/bww/sites/" + std::string(record["domain"].as<const char*>()) + "." + std::to_string(record["revision"].as<uint64_t>()) + ".json";
}
bool Core::validState(JsonDocument& state) {
    if (state.overflowed() || !state["generation"].is<uint64_t>() || !state["clock"].is<uint64_t>() || !state["users"].is<JsonArray>() || !state["sessions"].is<JsonArray>() || !state["sites"].is<JsonArray>() || !state["digest"].is<const char*>()) return false;
    std::string expected = state["digest"].as<std::string>(); state.remove("digest");
    auto actual = crypto_.jsonDigest(state.as<JsonVariantConst>()); state["digest"] = expected;
    if (actual.size() != 64 || !constantTimeEqual(expected, actual)) return false;
    if (state["users"].size() > MAX_USERS || state["sessions"].size() > MAX_SESSIONS || (state["siteCatalog"] != "paged-v1" && state["sites"].size() > 24)) return false;
    std::set<std::string> users;
    for (JsonObjectConst u : state["users"].as<JsonArrayConst>()) {
        std::string name = u["name"] | ""; std::vector<uint8_t> bytes;
        if (!asciiName(name, 3, 32, true) || !users.insert(name).second || !unhex(u["salt"] | "", bytes) || bytes.size() != 16 || !unhex(u["hash"] | "", bytes) || bytes.size() != 32) return false;
    }
    for (JsonObjectConst s : state["sessions"].as<JsonArrayConst>()) {
        std::vector<uint8_t> bytes;
        if (!users.count(s["user"] | "") || !s["expires"].is<uint64_t>() || !unhex(s["key"] | "", bytes) || bytes.size() != 32) return false;
    }
    if (state["siteCatalog"] == "paged-v1" && (!state["catalogPages"].is<size_t>() || state["sites"].size())) return false;
    bool good = true;
    if (!visitSites(state, [&](JsonObjectConst record) {
        std::string name = record["domain"] | "", canonical;
        if (!canonicalDomain(name, canonical) || name != canonical || !users.count(record["owner"] | "") ||
            !record["revision"].is<uint64_t>() || !storage_.exists(sitePath(record))) good = false;
    })) return false;
    if (!good) return false;
    return true;
}
bool Core::begin() {
    ready_ = false; uploads_.clear();
    if (state_.capacity() != STATE_CAPACITY || siteRecord_.capacity() != 512 || !storage_.mkdir("/bww") || !storage_.mkdir("/bww/sites") || !storage_.mkdir("/bww/catalog")) return false;
    bool any = storage_.exists(slot(0)) || storage_.exists(slot(1)), found = false; uint64_t best = 0;
    {
        DynamicJsonDocument candidate(STATE_CAPACITY);
        if (candidate.capacity() != STATE_CAPACITY) return false;
        for (int i = 0; i < 2; ++i) {
            if (storage_.readJson(slot(i), candidate) && validState(candidate) && (!found || candidate["generation"].as<uint64_t>() > best)) {
                if (!state_.set(candidate.as<JsonVariantConst>())) return false;
                active_ = i; best = candidate["generation"].as<uint64_t>(); found = true;
            }
        }
    } // Release candidate before commit/cleanup.
    if (any && !found) return false; // Never silently reset a damaged account database.
    if (!found) {
        state_.clear(); state_["generation"] = uint64_t(0); state_["clock"] = uint64_t(0);
        state_.createNestedArray("users"); state_.createNestedArray("sessions"); state_.createNestedArray("sites");
        if (!commit()) return false;
    }
    clock_ = checkpoint_ = state_["clock"].as<uint64_t>();
    backupGeneration_ = state_["generation"].as<uint64_t>() ? state_["generation"].as<uint64_t>() - 1 : 0;
    if (!discardFuturePages(state_["generation"])) return false;
    if (!migrateCatalog()) return false;
    ready_ = true; pruneSites(); return true;
}
bool Core::commit() {
    if (state_.overflowed()) {
        if (!storage_.readJson(slot(active_), state_) || !discardFuturePages(state_["generation"])) ready_ = false;
        return false;
    }
    uint64_t generation = state_["generation"].as<uint64_t>();
    state_["generation"] = generation + 1; state_["clock"] = clock_; state_.remove("digest");
    auto digest = crypto_.jsonDigest(state_.as<JsonVariantConst>()); state_["digest"] = digest;
    int next = 1 - active_;
    bool written = digest.size() == 64 && !state_.overflowed() && storage_.writeJson(slot(next), state_);
    // Read back the checksum and manifest before acknowledging durable changes.
    {
        DynamicJsonDocument check(STATE_CAPACITY);
        written = written && check.capacity() == STATE_CAPACITY && storage_.readJson(slot(next), check) && validState(check) && constantTimeEqual(digest, check["digest"].as<std::string>());
    } // Release verification buffer before cleanup.
    if (!written) {
        storage_.remove(slot(next));
        if (!discardFuturePages(generation)) ready_ = false;
        if (!storage_.readJson(slot(active_), state_) || !validState(state_)) ready_ = false;
        return false;
    }
    backupGeneration_ = generation; active_ = next; checkpoint_ = clock_; pruneSites(); return true;
}
void Core::pruneSites() {
    // Keep only the catalog coordinates from the fallback snapshot, not its
    // account/session document, while checking site metadata and deleting files.
    DynamicJsonDocument backup(CATALOG_CAPACITY);
    if (backup.capacity() != CATALOG_CAPACITY) return;
    bool hasBackup = storage_.exists(slot(1 - active_));
    if (hasBackup) {
        DynamicJsonDocument snapshot(STATE_CAPACITY);
        if (snapshot.capacity() != STATE_CAPACITY || !storage_.readJson(slot(1 - active_), snapshot) || !validState(snapshot)) return;
        backup["generation"] = snapshot["generation"];
        backup["siteCatalog"] = snapshot["siteCatalog"]; backup["catalogPages"] = snapshot["catalogPages"];
        backup["sites"] = snapshot["sites"];
        if (backup.overflowed()) return;
    }
    // Ensure all retained metadata is readable before removing any orphan.
    // This buffer is released before opening the directory.
    {
        DynamicJsonDocument metadata(INLINE_SITE_BYTES);
        if (metadata.capacity() != INLINE_SITE_BYTES) return;
        bool good = true;
        auto verify = [&](JsonObjectConst record) {
            if (!good) return;
            if (!storage_.readJson(sitePath(record), metadata) ||
                !constantTimeEqual(metadata["digest"] | "", crypto_.jsonDigest(metadata["data"]))) { good = false; return; }
            auto data = metadata["data"];
            if (data["transferMode"] == "chunk-v1") {
                if (!validChunks(data)) { good = false; return; }
                std::string ref = "/bww/sites/" + data["transfer"].as<std::string>() + ".ref";
                StaticJsonDocument<512> link;
                if (!storage_.exists(ref)) {
                    link["domain"] = record["domain"]; link["revision"] = record["revision"];
                    if (!storage_.writeJson(ref, link)) good = false;
                } else if (!storage_.readJson(ref, link) || link["domain"] != record["domain"] || link["revision"] != record["revision"]) good = false;
            }
        };
        if (!visitSites(state_, verify) || !good) return;
        if (hasBackup && (!visitSites(backup, verify) || !good)) return;
    }
    storage_.visitFiles("/bww/sites", [&](const std::string& file) {
        bool manifest = file.size() > 5 && file.substr(file.size() - 5) == ".json";
        bool chunk = file.size() > 4 && file.substr(file.size() - 4) == ".bin";
        bool reference = file.size() > 4 && file.substr(file.size() - 4) == ".ref";
        if (!manifest && !chunk && !reference) return;
        std::string domain; uint64_t revision = 0;
        if (chunk || reference) {
            auto name = file.substr(file.find_last_of('/') + 1), id = name.substr(0, name.find('.'));
            for (const auto& upload : uploads_) if (id == upload.id) return;
            auto ref = "/bww/sites/" + id + ".ref";
            if (storage_.exists(ref)) {
                StaticJsonDocument<512> link;
                if (!storage_.readJson(ref, link) || !link["domain"].is<const char*>() || !link["revision"].is<uint64_t>()) return;
                domain = link["domain"].as<std::string>(); revision = link["revision"];
            }
        }
        if (manifest) {
            auto name = file.substr(file.find_last_of('/') + 1); auto end = name.find(".bww.");
            if (end != std::string::npos) domain = name.substr(0, end + 4);
        }
        StaticJsonDocument<512> record; bool keep = false;
        auto check = [&](JsonDocument& snapshot) {
            if (!lookupSite(snapshot, domain, record)) return false;
            if (!record.isNull() && (manifest ? file == sitePath(record.as<JsonObjectConst>()) : revision == record["revision"].as<uint64_t>())) keep = true;
            return true;
        };
        if (!domain.empty() && (!check(state_) || (hasBackup && !keep && !check(backup)))) return;
        if (!keep) storage_.remove(file);
    });
}

bool Core::advance(uint32_t seconds) {
    clock_ += seconds;
    auto before = uploads_.size();
    uploads_.erase(std::remove_if(uploads_.begin(), uploads_.end(), [&](const Upload& u) { return clock_ - u.touched >= UPLOAD_IDLE_SECONDS; }), uploads_.end());
    if (before != uploads_.size()) pruneSites();
    if (ready_ && clock_ - checkpoint_ >= CLOCK_CHECKPOINT_SECONDS) return commit();
    return ready_;
}
JsonObject Core::user(const std::string& name) { for (JsonObject u : state_["users"].as<JsonArray>()) if (name == u["name"].as<const char*>()) return u; return JsonObject(); }
JsonObject Core::site(const std::string& name) {
    catalogError_ = !lookupSite(state_, name, siteRecord_);
    return siteRecord_.as<JsonObject>();
}
std::string Core::identity(JsonObjectConst r) {
    if (!r["token"].is<JsonString>()) return "";
    JsonString token = r["token"].as<JsonString>(); if (token.size() > 128) return "";
    auto key = crypto_.sha256(std::string(token.c_str(), token.size()));
    if (key.size() != 64) return "";
    for (JsonObjectConst s : state_["sessions"].as<JsonArrayConst>())
        if (s["expires"].as<uint64_t>() > clock_ && constantTimeEqual(key, s["key"].as<std::string>())) return s["user"].as<std::string>();
    return "";
}
void Core::execute(JsonDocument& rpc) {
    if (!ready_) { failure(rpc, "storage_error", "SD storage is unavailable; restart after checking the card"); return; }
    if (!rpc.is<JsonObject>()) { failure(rpc, "invalid_request", "Expected a JSON object"); return; }
    JsonObjectConst r = rpc.as<JsonObjectConst>(); std::string op;
    if (!field(r, "op", 32, op, rpc)) return;
    if (op == "hello") {
        auto d = success(rpc); d["protocol"] = 1; d["name"] = "Bluetooth-wide Web ESP32"; d["maxSiteBytes"] = MAX_SITE_BYTES;
        d["maxBtClients"] = MAX_BT_CLIENTS; d["siteTransfer"] = "chunk-v1"; d["chunkBytes"] = CHUNK_BYTES;
        d["firmwareVersion"] = FIRMWARE_VERSION; d["maxUsers"] = MAX_USERS; d["siteQuota"] = "sd-space"; d["storageBytes"] = storage_.totalBytes(); d["freeStorageBytes"] = storage_.freeBytes(); d["storageReserveBytes"] = SD_RESERVE_BYTES; d["siteListing"] = "paged-v1"; d["sessionClock"] = "powered-time"; d["siteSync"] = "account-v1"; return;
    }
    if (op == "register" || op == "login") {
        std::string name, password;
        if (!field(r, "username", 32, name, rpc) || !field(r, "password", 256, password, rpc)) return;
        name = trimLower(name);
        if (!asciiName(name, 3, 32, true)) { failure(rpc, "invalid_username", "Use 3-32 ASCII letters, numbers, or underscores"); return; }
        JsonObject account = user(name); std::string salt, hash;
        if (op == "register") {
            size_t length; validUtf8(password, &length);
            if (length < 10) { failure(rpc, "weak_password", "Use at least 10 characters"); return; }
            if (!account.isNull()) { failure(rpc, "username_taken", "Username is already registered"); return; }
            if (state_["users"].size() >= MAX_USERS) { failure(rpc, "capacity", "Device account limit reached"); return; }
            salt = crypto_.randomHex(16);
        } else salt = account.isNull() ? std::string(32, '0') : account["salt"].as<std::string>();
        hash = crypto_.passwordHash(password, salt);
        if (hash.size() != 64 || salt.size() != 32) { failure(rpc, "crypto_error", "Password hashing failed"); return; }
        if (op == "login" && (account.isNull() || !constantTimeEqual(hash, account["hash"].as<std::string>()))) { failure(rpc, "invalid_credentials", "Username or password is incorrect"); return; }
        auto token = crypto_.randomHex(32); auto key = crypto_.sha256(token);
        if (token.size() != 64 || key.size() != 64) { failure(rpc, "crypto_error", "Session creation failed"); return; }
        JsonArray sessions = state_["sessions"].as<JsonArray>();
        for (size_t i = sessions.size(); i > 0; --i) if (sessions[i - 1]["expires"].as<uint64_t>() <= clock_) sessions.remove(i - 1);
        size_t count = 0; for (JsonObjectConst s : sessions) if (name == s["user"].as<const char*>()) ++count;
        if (count >= 4) for (size_t i = 0; i < sessions.size(); ++i) if (name == sessions[i]["user"].as<const char*>()) { sessions.remove(i); break; }
        if (sessions.size() >= MAX_SESSIONS) { failure(rpc, "capacity", "Device session limit reached"); return; }
        if (op == "register") { account = state_["users"].as<JsonArray>().createNestedObject(); account["name"] = name; account["salt"] = salt; account["hash"] = hash; }
        JsonObject s = sessions.createNestedObject(); s["key"] = key; s["user"] = name; s["expires"] = clock_ + SESSION_POWERED_SECONDS;
        if (!commit()) { failure(rpc, "storage_error", "Could not save the account/session to SD"); return; }
        auto d = success(rpc); d["username"] = name; d["token"] = token; d["expires"] = nullptr; d["expiresAfterPoweredSeconds"] = SESSION_POWERED_SECONDS; return;
    }
    std::string name;
    if (op == "me" || op == "logout" || op == "mine" || op == "sync_manifest" || op == "sync_publish_begin" || op == "publish" || op == "delete" || op == "publish_begin" || op == "publish_chunk" || op == "publish_commit" || op == "publish_cancel") {
        name = identity(r); if (name.empty()) { failure(rpc, "unauthorized", "Sign in again; your session is missing or expired"); return; }
    }
    if (op == "sync_publish_begin" || op == "publish_begin" || op == "publish_chunk" || op == "publish_commit" || op == "publish_cancel" || op == "get_chunk") {
        transfer(rpc, op, name); return;
    }
    if (op == "me") { success(rpc)["username"] = name; return; }
    if (op == "logout") {
        std::string token; if (!field(r, "token", 128, token, rpc)) return;
        auto key = crypto_.sha256(token); JsonArray sessions = state_["sessions"].as<JsonArray>();
        for (size_t i = 0; i < sessions.size(); ++i) if (constantTimeEqual(key, sessions[i]["key"].as<std::string>())) { sessions.remove(i); break; }
        if (!commit()) { failure(rpc, "storage_error", "Could not save sign-out to SD"); return; }
        success(rpc)["signedOut"] = true; return;
    }
    if (op == "list" || op == "mine" || op == "sync_manifest") {
        size_t offset = 0;
        if (r.containsKey("offset")) {
            if (!r["offset"].is<size_t>()) { failure(rpc, "invalid_request", "Invalid listing offset"); return; }
            offset = r["offset"];
        }
        uint64_t generation = state_["catalogRevision"] | uint64_t(0);
        if (r.containsKey("catalogGeneration") && (!r["catalogGeneration"].is<uint64_t>() || r["catalogGeneration"].as<uint64_t>() != generation)) {
            failure(rpc, "catalog_changed", "Website list changed; load it again"); return;
        }
        struct Summary { std::string domain, owner; uint64_t revision; std::string fingerprint; };
        std::vector<Summary> summaries; size_t matched = 0; bool good = true;
        bool read = visitSites(state_, [&](JsonObjectConst record) {
            if (!good || (op != "list" && name != record["owner"].as<const char*>())) return;
            if (matched++ < offset || summaries.size() >= LIST_PAGE_SITES) return;
            Summary summary{record["domain"].as<std::string>(), record["owner"].as<std::string>(), record["revision"], ""};
            if (op == "sync_manifest") { summary.fingerprint = siteFingerprint(rpc, record); if (summary.fingerprint.empty()) { good = false; return; } }
            summaries.push_back(std::move(summary));
        });
        if (!read) { failure(rpc, "storage_error", "Could not read website catalog"); return; }
        if (!good) return;
        auto data = successArray(rpc);
        for (const auto& summary : summaries) {
            auto entry = data.createNestedObject(); entry["domain"] = summary.domain; entry["owner"] = summary.owner;
            if (op == "sync_manifest") entry["fingerprint"] = summary.fingerprint;
            else { entry["updated"] = nullptr; entry["revision"] = summary.revision; }
        }
        rpc["catalogGeneration"] = generation;
        if (matched > offset && matched - offset > summaries.size()) rpc["nextOffset"] = offset + summaries.size();
        return;
    }
    if (op != "available" && op != "get" && op != "publish" && op != "delete") { failure(rpc, "unknown_operation", "Unknown operation"); return; }
    std::string input, domain;
    if (!field(r, "domain", 128, input, rpc)) return;
    if (!canonicalDomain(input, domain)) { failure(rpc, "invalid_domain", "Use 1-63 ASCII letters, numbers, or internal hyphens"); return; }
    JsonObject record = site(domain);
    if (catalogError_) { failure(rpc, "storage_error", "Could not read website catalog"); return; }
    if (op == "available") { auto d = success(rpc); d["domain"] = domain; d["available"] = record.isNull(); return; }
    if (op == "get") {
        if (record.isNull()) { failure(rpc, "not_found", "Site not found on this server"); return; }
        readSite(rpc, record); return;
    }
    if (!record.isNull() && name != record["owner"].as<const char*>()) { failure(rpc, op == "publish" ? "domain_taken" : "forbidden", "Only the owner may change this site"); return; }
    if (op == "delete") {
        if (record.isNull()) { failure(rpc, "not_found", "Site not found"); return; }
        if (!storeSite(domain, name, 0, true)) { failure(rpc, "storage_error", "Could not save deletion to SD"); return; }
        if (!commit()) { failure(rpc, "storage_error", "Could not save deletion to SD"); return; }
        success(rpc)["deleted"] = true; return;
    }
    std::string html, css, js;
    if (!field(r, "html", INLINE_SITE_BYTES, html, rpc) || !field(r, "css", INLINE_SITE_BYTES, css, rpc) || !field(r, "js", INLINE_SITE_BYTES, js, rpc)) return;
    if (html.size() + css.size() + js.size() > INLINE_SITE_BYTES) { failure(rpc, "too_large", "Use chunk-v1 transfers for sites larger than 16 KiB; total site limit is 512 KiB"); return; }
    if (html.empty() || std::all_of(html.begin(), html.end(), [](unsigned char c) { return std::isspace(c); })) { failure(rpc, "empty_site", "HTML is required"); return; }
    if (!spaceFor(html.size() + css.size() + js.size() + 16384)) { failure(rpc, "storage_full", "SD card is full; delete websites or free space on the card"); return; }
    uint64_t revision = state_["generation"].as<uint64_t>() + 1;
    std::string path = "/bww/sites/" + domain + "." + std::to_string(revision) + ".json";
    auto d = success(rpc); d["domain"] = domain; d["owner"] = name; d["revision"] = revision; d["updated"] = nullptr;
    d["html"] = html; d["css"] = css; d["js"] = js; rpc["digest"] = crypto_.jsonDigest(d);
    if (rpc.overflowed() || !storage_.writeJson(path, rpc)) { storage_.remove(path); failure(rpc, "storage_error", "Could not write the site to SD"); return; }
    if (!storeSite(domain, name, revision)) { storage_.remove(path); failure(rpc, "storage_error", "Could not update website catalog on SD"); return; }
    if (!commit()) { storage_.remove(path); failure(rpc, "storage_error", "Could not commit the site to SD"); return; }
    auto published = success(rpc); published["domain"] = domain; published["published"] = true;
}
}

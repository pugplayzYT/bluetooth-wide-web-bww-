#include "BwwCore.h"
#include <algorithm>
#include <cctype>
namespace bww {
namespace {
const char* assets[] = {"html", "css", "js"};
int assetIndex(const std::string& asset) { for (int i = 0; i < 3; ++i) if (asset == assets[i]) return i; return -1; }
std::string chunkPath(const std::string& id, int asset, size_t index) {
    return "/bww/sites/" + id + "." + assets[asset] + "." + std::to_string(index) + ".bin";
}
JsonObject success(JsonDocument& rpc) { rpc.clear(); rpc["ok"] = true; return rpc.createNestedObject("data"); }
bool text(JsonObjectConst r, const char* key, size_t max, std::string& out, JsonDocument& rpc) {
    if (!r[key].is<JsonString>()) { failure(rpc, "invalid_request", "Required string field is missing"); return false; }
    JsonString s = r[key].as<JsonString>();
    if (s.size() > max) { failure(rpc, "too_large", "Request field exceeds the limit"); return false; }
    out.assign(s.c_str(), s.size()); return true;
}
}
bool Core::validChunks(JsonObjectConst d) {
    std::vector<uint8_t> decoded;
    if (!d["transfer"].is<const char*>() || !unhex(d["transfer"].as<std::string>(), decoded) || decoded.size() != 16 || !d["chunks"].is<JsonObjectConst>()) return false;
    size_t bytes = 0, count = 0;
    for (const char* asset : assets) {
        if (!d["chunks"][asset].is<JsonArrayConst>()) return false;
        for (JsonObjectConst c : d["chunks"][asset].as<JsonArrayConst>()) {
            if (!c["bytes"].is<size_t>() || c["bytes"].as<size_t>() == 0 || c["bytes"].as<size_t>() > CHUNK_BYTES || !unhex(c["hash"] | "", decoded) || decoded.size() != 32) return false;
            bytes += c["bytes"].as<size_t>(); ++count;
        }
    }
    return bytes <= MAX_SITE_BYTES && count <= MAX_SITE_CHUNKS;
}
bool Core::readSite(JsonDocument& rpc, JsonObjectConst record) {
    auto path = sitePath(record); std::string domain = record["domain"].as<std::string>(), owner = record["owner"].as<std::string>(); uint64_t revision = record["revision"];
    rpc.clear();
    if (!storage_.readJson(path, rpc) || rpc["ok"] != true || rpc["data"]["domain"] != domain || rpc["data"]["owner"] != owner || rpc["data"]["revision"].as<uint64_t>() != revision || !constantTimeEqual(rpc["digest"] | "", crypto_.jsonDigest(rpc["data"])) || (rpc["data"]["transferMode"] == "chunk-v1" && !validChunks(rpc["data"]))) {
        failure(rpc, "storage_error", "Published site is damaged or unreadable; restore or republish it"); return false;
    }
    rpc.remove("digest"); return true;
}
bool Core::canPublish(const std::string& domain, const std::string& owner, JsonDocument& rpc) {
    auto record = site(domain);
    if (!record.isNull() && owner != record["owner"].as<const char*>()) { failure(rpc, "domain_taken", "Only the owner may change this site"); return false; }
    if (record.isNull()) {
        size_t own = 0; for (JsonObjectConst s : state_["sites"].as<JsonArrayConst>()) if (owner == s["owner"].as<const char*>()) ++own;
        if (state_["sites"].size() >= MAX_SITES || own >= MAX_USER_SITES) { failure(rpc, "capacity", "Device or account site limit reached"); return false; }
    }
    return true;
}
std::string Core::siteFingerprint(JsonDocument& rpc, JsonObjectConst record) {
    if (!readSite(rpc, record)) return "";
    JsonObjectConst data = rpc["data"]; std::string manifest;
    std::string pending; pending.reserve(CHUNK_BYTES + 4);
    for (int a = 0; a < 3; ++a) {
        const char* asset = assets[a]; manifest += std::string(asset) + ":";
        auto emit = [&](size_t end) {
            std::string carry = pending.substr(end); pending.resize(end);
            auto hash = crypto_.sha256(pending);
            if (hash.size() != 64) return false;
            manifest += std::to_string(end) + ":" + hash + ","; pending = std::move(carry); return true;
        };
        auto feed = [&](const std::string& text) {
            for (char byte : text) {
                pending.push_back(byte);
                if (pending.size() > CHUNK_BYTES) {
                    size_t end = CHUNK_BYTES;
                    while ((static_cast<uint8_t>(pending[end]) & 0xc0) == 0x80) --end;
                    if (!emit(end)) return false;
                }
            }
            return true;
        };
        bool ok = true;
        if (data["transferMode"] == "chunk-v1") {
            std::string id = data["transfer"].as<std::string>(); size_t index = 0;
            for (JsonObjectConst c : data["chunks"][asset].as<JsonArrayConst>()) {
                std::string text;
                if (!storage_.readBytes(chunkPath(id, a, index++), CHUNK_BYTES, text) || text.size() != c["bytes"].as<size_t>() ||
                    !constantTimeEqual(crypto_.sha256(text), c["hash"].as<std::string>()) || !validUtf8(text)) {
                    failure(rpc, "storage_error", "Site chunk is damaged or unreadable"); return "";
                }
                if (!feed(text)) { ok = false; break; }
            }
        } else ok = feed(data[asset].as<std::string>());
        if (ok && !pending.empty()) ok = emit(pending.size());
        if (!ok) { failure(rpc, "crypto_error", "Could not compare site"); return ""; }
        manifest += ";";
    }
    auto hash = crypto_.sha256(manifest); if (hash.size() != 64) { failure(rpc, "crypto_error", "Could not compare site"); return ""; } return hash;
}
bool Core::syncUnchanged(const std::string& domain, const std::string& expected, JsonDocument& rpc) {
    auto record = site(domain);
    std::string actual = record.isNull() ? "missing" : siteFingerprint(rpc, record);
    if (actual.empty()) return false;
    if (actual != expected) { failure(rpc, "sync_conflict", "Destination changed since comparison; compare again"); return false; }
    return true;
}
void Core::transfer(JsonDocument& rpc, const std::string& op, const std::string& owner) {
    JsonObjectConst r = rpc.as<JsonObjectConst>();
    if (op == "get_chunk") {
        std::string domain, input, asset;
        if (!text(r, "domain", 128, input, rpc) || !text(r, "asset", 8, asset, rpc)) return;
        if (!canonicalDomain(input, domain)) { failure(rpc, "invalid_domain", "Invalid domain"); return; }
        int a = assetIndex(asset);
        if (a < 0 || !r["index"].is<size_t>() || !r["revision"].is<uint64_t>()) { failure(rpc, "invalid_request", "Invalid chunk address"); return; }
        size_t index = r["index"]; uint64_t revision = r["revision"];
        auto record = site(domain);
        if (record.isNull()) { failure(rpc, "not_found", "Site not found"); return; }
        if (record["revision"].as<uint64_t>() != revision) { failure(rpc, "site_changed", "Site changed while loading; open it again"); return; }
        if (!readSite(rpc, record)) return;
        JsonObjectConst d = rpc["data"];
        if (d["transferMode"] != "chunk-v1" || index >= d["chunks"][asset].size()) { failure(rpc, "invalid_request", "Chunk does not exist"); return; }
        auto c = d["chunks"][asset][index];
        std::string id = d["transfer"].as<std::string>(), expected = c["hash"].as<std::string>(); size_t bytes = c["bytes"];
        // Free metadata before allocating chunk and hex response.
        rpc.clear(); std::string content;
        if (!storage_.readBytes(chunkPath(id, a, index), CHUNK_BYTES, content) || content.size() != bytes || !constantTimeEqual(expected, crypto_.sha256(content))) { failure(rpc, "storage_error", "Site chunk is damaged or unreadable"); return; }
        auto result = success(rpc); result["data"] = hex(reinterpret_cast<const uint8_t*>(content.data()), content.size()); return;
    }
    std::string token;
    if (!text(r, "token", 128, token, rpc)) return;
    auto session = crypto_.sha256(token);
    if (op == "publish_begin" || op == "sync_publish_begin") {
        std::string input, domain;
        if (!text(r, "domain", 128, input, rpc)) return;
        if (!canonicalDomain(input, domain)) { failure(rpc, "invalid_domain", "Invalid domain"); return; }
        if (!canPublish(domain, owner, rpc)) return;
        std::string expected;
        if (op == "sync_publish_begin") {
            if (!text(r, "expectedFingerprint", 64, expected, rpc)) return;
            if (!syncUnchanged(domain, expected, rpc)) return;
        }
        // Starting again from the same session abandons its old incomplete upload.
        uploads_.erase(std::remove_if(uploads_.begin(), uploads_.end(), [&](const Upload& u) { return u.session == session; }), uploads_.end());
        pruneSites();
        if (uploads_.size() >= MAX_BT_CLIENTS) { failure(rpc, "capacity", "Three uploads are already in progress; retry after one finishes or expires"); return; }
        std::string id = crypto_.randomHex(16);
        if (id.size() != 32 || std::any_of(uploads_.begin(), uploads_.end(), [&](const Upload& u) { return u.id == id; })) { failure(rpc, "crypto_error", "Could not allocate upload identifier"); return; }
        Upload u; u.id = id; u.domain = domain; u.owner = owner; u.session = session; u.expectedFingerprint = expected; u.touched = clock_; uploads_.push_back(std::move(u));
        auto result = success(rpc); result["transfer"] = id; result["chunkBytes"] = CHUNK_BYTES; return;
    }
    std::string id;
    if (!text(r, "transfer", 32, id, rpc)) return;
    auto it = std::find_if(uploads_.begin(), uploads_.end(), [&](const Upload& u) { return u.id == id && u.owner == owner && constantTimeEqual(u.session, session); });
    if (it == uploads_.end()) { failure(rpc, "upload_missing", "Upload expired or belongs to another session; publish again"); return; }
    Upload& u = *it; u.touched = clock_;
    if (op == "publish_cancel") { uploads_.erase(it); pruneSites(); success(rpc)["cancelled"] = true; return; }
    if (op == "publish_chunk") {
        std::string asset, encoded;
        if (!text(r, "asset", 8, asset, rpc) || !text(r, "data", CHUNK_BYTES * 2, encoded, rpc)) return;
        int a = assetIndex(asset);
        if (a < 0 || !r["index"].is<size_t>()) { failure(rpc, "invalid_request", "Invalid chunk address"); return; }
        size_t index = r["index"]; std::vector<uint8_t> decoded;
        if (!unhex(encoded, decoded) || decoded.empty() || decoded.size() > CHUNK_BYTES) { failure(rpc, "invalid_request", "Chunk data must be hexadecimal UTF-8 bytes"); return; }
        encoded.clear(); encoded.shrink_to_fit();
        std::string content(reinterpret_cast<const char*>(decoded.data()), decoded.size()); decoded.clear(); decoded.shrink_to_fit();
        if (!validUtf8(content)) { failure(rpc, "invalid_request", "Chunks must end at a UTF-8 character boundary"); return; }
        size_t count = 0; for (const auto& chunks : u.chunks) count += chunks.size();
        if (index != u.chunks[a].size()) { failure(rpc, "invalid_request", "Chunks must be sent once in sequence"); return; }
        if (u.bytes + content.size() > MAX_SITE_BYTES) { failure(rpc, "too_large", "Site exceeds 512 KiB combined HTML/CSS/JS"); return; }
        if (count >= MAX_SITE_CHUNKS) { failure(rpc, "too_many_chunks", "Use full-sized chunks except each asset's last chunk"); return; }
        auto hash = crypto_.sha256(content);
        rpc.clear();
        if (hash.size() != 64 || !storage_.writeBytes(chunkPath(u.id, a, index), content)) { failure(rpc, "storage_error", "Could not save upload chunk"); return; }
        std::string check;
        if (!storage_.readBytes(chunkPath(u.id, a, index), CHUNK_BYTES, check) || check != content) { storage_.remove(chunkPath(u.id, a, index)); failure(rpc, "storage_error", "Upload chunk verification failed"); return; }
        u.bytes += content.size(); u.chunks[a].push_back({content.size(), hash});
        if (a == 0 && std::any_of(content.begin(), content.end(), [](unsigned char c) { return !std::isspace(c); })) u.htmlNonempty = true;
        success(rpc)["received"] = content.size(); return;
    }
    if (!u.htmlNonempty) { failure(rpc, "empty_site", "HTML is required"); return; }
    if (!canPublish(u.domain, owner, rpc)) return;
    if (!u.expectedFingerprint.empty() && !syncUnchanged(u.domain, u.expectedFingerprint, rpc)) return;
    uint64_t revision = state_["generation"].as<uint64_t>() + 1;
    auto result = success(rpc); result["domain"] = u.domain; result["owner"] = owner; result["updated"] = nullptr; result["revision"] = revision;
    result["transferMode"] = "chunk-v1"; result["transfer"] = u.id;
    auto chunks = result.createNestedObject("chunks");
    for (int a = 0; a < 3; ++a) {
        auto list = chunks.createNestedArray(assets[a]);
        for (const auto& c : u.chunks[a]) { auto entry = list.createNestedObject(); entry["bytes"] = c.bytes; entry["hash"] = c.hash; }
    }
    rpc["digest"] = crypto_.jsonDigest(result);
    std::string path = "/bww/sites/" + u.domain + "." + std::to_string(revision) + ".json";
    if (rpc.overflowed() || !storage_.writeJson(path, rpc)) { storage_.remove(path); failure(rpc, "storage_error", "Could not save site metadata"); return; }
    std::string metadataDigest = rpc["digest"].as<std::string>();
    rpc.clear();
    if (!storage_.readJson(path, rpc) || !constantTimeEqual(metadataDigest, rpc["digest"] | "") || !constantTimeEqual(metadataDigest, crypto_.jsonDigest(rpc["data"])) || !validChunks(rpc["data"])) {
        storage_.remove(path); failure(rpc, "storage_error", "Site metadata verification failed"); return;
    }
    // Check every staged chunk before publishing; reads are bounded to one chunk.
    {
        std::string content;
        for (int a = 0; a < 3; ++a) for (size_t i = 0; i < u.chunks[a].size(); ++i) {
            const auto& c = u.chunks[a][i];
            if (!storage_.readBytes(chunkPath(u.id, a, i), CHUNK_BYTES, content) || content.size() != c.bytes || !constantTimeEqual(c.hash, crypto_.sha256(content))) { storage_.remove(path); failure(rpc, "storage_error", "Upload chunk was lost or corrupted; publish again"); return; }
        }
    } // Release the chunk buffer before allocating the state commit verifier.
    rpc.clear(); // Verified site metadata is no longer needed by this request.
    auto record = site(u.domain);
    if (record.isNull()) record = state_["sites"].as<JsonArray>().createNestedObject();
    record["domain"] = u.domain; record["owner"] = owner; record["revision"] = revision;
    if (!commit()) { storage_.remove(path); failure(rpc, "storage_error", "Could not commit site to SD"); return; }
    std::string domain = u.domain; uploads_.erase(it);
    auto published = success(rpc); published["domain"] = domain; published["published"] = true;
}
}

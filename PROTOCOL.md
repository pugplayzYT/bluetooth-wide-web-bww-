# BWW protocol 1

Transport: Bluetooth Classic RFCOMM service UUID `731e9c72-48a1-4e6b-a842-d1ea7cc89010`. Windows publishes an SDP record named `Bluetooth-wide Web`; Android connects using its paired device and that UUID. The ESP32 host uses the standard SPP UUID `00001101-0000-1000-8000-00805f9b34fb`. Android tries the appropriate service and validates `hello` before account operations. Development TCP binds only `127.0.0.1`, port 8877 by default (`--port` overrides it).

Each request is one UTF-8 JSON object followed by LF (`\n`). Newlines inside strings must be JSON-escaped. A connection may send multiple requests. The server replies in the same order with one JSON object and LF per request. The Android client serializes requests; there are no request IDs. Desktop maximum incoming frame: 4 MiB; maximum JSON depth: 16. The server closes oversized/incomplete/invalid UTF-8 frames. Each request/read has a 2-minute deadline on the server; the Android client allows 20 seconds per connection attempt, 120 seconds for login/register, and 60 seconds for other responses. Reconnect after inactivity or a transport error.

Successful response: `{"ok":true,"data": ...}`. Error: `{"ok":false,"error":"domain_taken","message":"This domain belongs to another account"}`. API errors do not invalidate the transport connection. The desktop returns mutation success only after an atomic, flushed storage write. The ESP32 writes and reads back an inactive SD snapshot before acknowledging; see its guide for SD power-loss limitations.

| Operation | Request fields besides `op` | Result `data` |
| --- | --- | --- |
| `hello` | none | protocol version, name, site size limit |
| `register` | `username`, `password` | `token`, canonical username, expiry |
| `login` | `username`, `password` | `token`, canonical username, expiry |
| `me` | `token` | username |
| `logout` | `token` | signedOut |
| `available` | `domain` | canonical domain, available |
| `list` | none | array of domain/owner/updated summaries |
| `mine` | `token` | array of owned domain/updated summaries |
| `get` | `domain` | domain, owner, html, css, js, updated |
| `publish` | `token`, `domain`, `html`, `css`, `js` | domain, published |
| `delete` | `token`, `domain` | deleted |

Names are case-insensitive ASCII. Usernames use 3–32 letters/digits/underscores. Domain labels use 1–63 letters/digits/internal hyphens; optional `.bww` suffix is accepted. Publish creates a site or updates an existing site owned by that account. Availability does not reserve a name. All content is readable to connected guests.

Typical exchange:

```json
{"op":"hello"}
{"op":"register","username":"alice","password":"choose a long private password"}
{"op":"publish","token":"TOKEN_FROM_REGISTER","domain":"garden","html":"<h1>My garden</h1>","css":"h1{color:green}","js":"console.log('hello')"}
{"op":"get","domain":"garden.bww"}
```

Session tokens belong in native app storage only, never in published content or URLs. These examples contain no real credentials.

## ESP32 host differences

The firmware implements the operations above plus chunked transfers with a 512 KiB combined UTF-8 site limit, advertised in `hello.maxSiteBytes`. It handles three clients, 12 accounts, SD-space-limited website counts, and 24 sessions (4 per account). Incoming JSON uses a 24 KiB document allocation and a bounded wire frame of `6 * 16384 + 8192` bytes; nesting remains limited to 16. Malformed JSON produces an API error; oversized/incomplete frames disconnect.

No calendar clock is available: authentication returns `expires: null`, `expiresAfterPoweredSeconds: 2592000`; `hello.sessionClock` is `powered-time`. Site summaries/content use `updated: null` and an increasing `revision`. Powered time is checkpointed on mutations and every five minutes, with unplugged time excluded. Session tokens and request envelopes follow the same protocol. Storage/checksum failures return errors instead of resetting accounts or reporting successful mutations. See [esp32/README.md](esp32/README.md).

### ESP32 chunk-v1 transfers (Android 0.4+)

`hello` advertises `siteTransfer: "chunk-v1"`, `chunkBytes: 8192`, `maxSiteBytes: 524288`, and `maxBtClients: 3`. The JSON buffer remains 24 KiB. Legacy inline `publish`/`get` still support previously stored sites up to 16 KiB. Android automatically uses chunk operations when advertised; Windows keeps the original inline protocol.

| Operation | Request fields besides `op` | Result `data` |
| --- | --- | --- |
| `publish_begin` | token, domain | transfer ID, chunkBytes |
| `publish_chunk` | token, transfer, asset (`html`/`css`/`js`), index, data | received byte count |
| `publish_commit` | token, transfer | domain, published |
| `publish_cancel` | token, transfer | cancelled |
| `get_chunk` | domain, revision, asset, index | data |

Chunk `data` is hexadecimal encoding of up to 8192 raw UTF-8 bytes. Every chunk ends at a complete UTF-8 character boundary. Each asset starts at index 0 and increments without duplicates; skip empty assets. Send full-size chunks except each asset's last chunk (back off up to three bytes to avoid splitting a character); at most 67 chunks may comprise a site. The combined decoded HTML/CSS/JS limit is 524288 bytes. Nonblank HTML is required. Uploads belong to the exact session, are capped at three, and expire after 300 powered seconds of inactivity. Starting another upload from the same session cancels its previous upload. Disconnecting does not commit an upload. Tokens are required and revalidated for every publishing operation. Domain ownership and quotas are checked again at commit, so a concurrent name claim cannot overwrite another owner.

For chunked sites, `get` returns domain/owner/revision/updated metadata, `transferMode: "chunk-v1"`, a transfer ID, and `chunks` with html/css/js arrays of `{bytes,hash}`. It does not return full inline assets. Read each asset using `get_chunk` with the returned revision. The server checks each stored chunk's SHA-256 before returning its hex data. If the published revision changes during loading, `site_changed` requires reopening the site; the client cannot silently combine different versions. Cancelled/expired uploads are pruned without removing chunks referenced by either valid state snapshot.
# Account website sync (host capability `siteSync: "account-v1"`)

`sync_manifest` requires `token` and returns an array of the authenticated owner's `{domain, owner, fingerprint}` sites. It rejects unreadable/corrupted source chunks. Fingerprints ignore dates, revisions and storage segmentation: concatenate `html:` followed by each canonical UTF-8 chunk's decimal byte length, `:`, lowercase SHA-256 hex and `,`, then `;`, and repeat for `css` and `js`. Canonical chunks are at most 8192 bytes and end before a UTF-8 continuation byte; an empty asset has no chunks. Hash that ASCII manifest with SHA-256 (lowercase hex).

Desktop `sync_publish` takes the normal `publish` fields plus `expectedFingerprint` (`"missing"` or the destination's fingerprint from comparison). It checks ownership and the precondition while holding the store's transaction lock. ESP32 `sync_publish_begin` takes `token`, `domain`, and `expectedFingerprint` and returns the normal upload identifier/chunk size. Send normal `publish_chunk`, then `publish_commit` or `publish_cancel`. The ESP32 checks the expected destination both when staging begins and immediately before commit; mismatches return `sync_conflict` and do not publish staged content. Existing clients' unconditional publishing behavior is unchanged.

Sync is per account, manual and additive; no delete propagation, credential export or automatic conflict winner is defined. A host-side sync client must verify the read source fingerprint against the reviewed manifest before sending it. Each site commits individually; a multi-site batch is not a distributed transaction.

### ESP32 paged-v1 catalog (firmware 0.6.0)

`hello` advertises `siteQuota: "sd-space"`, `siteListing: "paged-v1"`, `storageBytes` (usable filesystem capacity), `freeStorageBytes` and `storageReserveBytes: 131072`. It no longer advertises a fixed `maxSites`. Per-site `maxSiteBytes: 524288`, account/session/client limits and chunk-v1 operations remain unchanged.

`list`, `mine`, and `sync_manifest` return at most 32 entries in the existing `data` array. The envelope additionally includes `catalogGeneration`; when more matching entries exist it includes `nextOffset`. Request the next page with `offset: nextOffset` and the same `catalogGeneration`. The last page omits `nextOffset`. A catalog mutation between pages returns `catalog_changed` rather than silently mixing different lists. Old Windows hosts still return an unpaged array. Negative or incorrectly typed supplied offsets are rejected (an omitted offset starts at zero).

Website indexes are stored as bounded eight-record catalog pages on SD, not in the account/session RAM document. Three checksummed slots per page preserve both committed snapshots and a staged edit. A proof file is written only after page read-back verification, and root snapshot commit makes the edit visible. Failed/power-interrupted edits are discarded before a later commit can reuse their generation. Lookup files are disposable accelerators; damaged/missing lookups fall back to scanning verified pages. Site content/chunk checksums and ownership checks are unchanged. Upload admission checks actual free card space with a 128 KiB reserve; `storage_full` reports insufficient space. Replacing sites needs space for the new content while the old recovery generation is still retained. Deleted/obsolete data is reclaimed after both snapshots no longer reference it and cleanup can verify retained metadata.

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

The firmware implements all operations above with a 16 KiB combined UTF-8 site limit, advertised in `hello.maxSiteBytes`. It handles one client, 12 accounts, 24 sites (8 per account), and 24 sessions (4 per account). Incoming JSON uses a 24 KiB document allocation and a bounded wire frame of `6 * maxSiteBytes + 8192` bytes; nesting remains limited to 16. Malformed JSON produces an API error; oversized/incomplete frames disconnect.

No calendar clock is available: authentication returns `expires: null`, `expiresAfterPoweredSeconds: 2592000`; `hello.sessionClock` is `powered-time`. Site summaries/content use `updated: null` and an increasing `revision`. Powered time is checkpointed on mutations and every five minutes, with unplugged time excluded. Session tokens and request envelopes follow the same protocol. Storage/checksum failures return errors instead of resetting accounts or reporting successful mutations. See [esp32/README.md](esp32/README.md).

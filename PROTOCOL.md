# BWW protocol 1

Transport: Bluetooth Classic RFCOMM service UUID `731e9c72-48a1-4e6b-a842-d1ea7cc89010`. Windows publishes an SDP record named `Bluetooth-wide Web`; Android connects using its paired device and that UUID. Development TCP binds only `127.0.0.1`, port 8877 by default (`--port` overrides it).

Each request is one UTF-8 JSON object followed by LF (`\n`). Newlines inside strings must be JSON-escaped. A connection may send multiple requests. The server replies in the same order with one JSON object and LF per request. The Android client serializes requests; there are no request IDs. Maximum incoming frame: 4 MiB; maximum JSON depth: 16. The server closes oversized/incomplete/invalid UTF-8 frames. Each request/read has a 2-minute deadline on the server; the Android client closes a connection after 20 seconds waiting for connect or a response. Reconnect after inactivity or a transport error.

Successful response: `{"ok":true,"data": ...}`. Error: `{"ok":false,"error":"domain_taken","message":"This domain belongs to another account"}`. API errors do not invalidate the transport connection. Mutation success is returned only after an atomic, flushed storage write.

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

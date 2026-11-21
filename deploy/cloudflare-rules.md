# KathaPulse AI — Cloudflare ingress rules

Use this when Cloudflare sits in front of the nginx config in
`deploy/nginx.kathapulse.conf` (or in front of the origin directly). Cloudflare
handles the volumetric layer; nginx still enforces the per-IP budget, so neither
is a single point of failure. Names below match the dashboard labels; nothing
here is a secret.

## 1. TLS and HSTS — SSL/TLS → Edge Certificates

| Setting | Value | Why |
|---|---|---|
| SSL mode | **Full (strict)** | Encrypts origin hop and rejects a self-signed origin |
| Always Use HTTPS | On | No plaintext path to the app |
| Minimum TLS version | 1.2 | Matches the nginx `ssl_protocols` line |
| HSTS | On, `max-age=63072000`, `includeSubDomains`, `preload` | Enable preload only once every subdomain is HTTPS |
| Opportunistic Encryption / TLS 1.3 / 0-RTT | On | Free latency win on 3G |
| Automatic HTTPS Rewrites | On | Fixes mixed-content in the shell |

Note the duplicate HSTS header: Cloudflare adds one and nginx adds one. Browsers
accept the first, but pick **one** layer if you want a clean header dump — with
Cloudflare in front, drop the nginx `add_header Strict-Transport-Security` line.

## 2. Rate limiting — Security → WAF → Rate limiting rules

Cloudflare's limiter counts requests before they reach origin, which is what
protects the vision-model budget. Characteristic: **IP**.

| Rule | Expression | Limit | Action |
|---|---|---|---|
| Scan burst | `http.request.method eq "POST" and http.request.uri.path in {"/verify-strip" "/verify-strips/batch"}` | 10 requests / 1 min | Block for 60s |
| Scan sustained | same expression | 60 requests / 10 min | Managed Challenge |
| Typed verification | `http.request.uri.path eq "/verify-medicines"` | 30 / 1 min | Block for 60s |
| Relay handshake | `http.request.uri.path matches "^/ws/relay/"` | 10 / 1 min | Block for 60s |
| Shell/assets | `http.request.uri.path matches "^/(static/|taxonomy\\.json|sw\\.js)"` | 600 / 1 min | Log only |

These are deliberately looser than nginx's 30/min: Cloudflare absorbs floods,
nginx enforces the precise application budget.

## 3. Schema occlusion — Security → WAF → Custom rules

```
(http.request.uri.path in {"/docs" "/redoc" "/openapi.json" "/docs/oauth2-redirect"})
→ Block
```

Same four paths the app now 404s by default (`KATHA_DOCS_ENABLED=0`). Three
layers — Cloudflare, nginx, app — is intentional: the app's rule is the one that
survives a proxy misconfiguration.

## 4. WAF and bots

| Setting | Value | Why |
|---|---|---|
| Managed Ruleset (Cloudflare OWASP) | On, paranoia 1 | Catches generic injection attempts before Pydantic does |
| Bot Fight Mode | On | Free tier friendly; the app has no legitimate bot traffic |
| Security Level | Medium | Raise to High only for an active incident |
| Browser Integrity Check | On | Cheap, no false positives for a static shell |
| Under Attack Mode | Off by default | **It breaks the WebSocket relay** — use a rate-limit block instead |

## 5. Cache rules — Caching → Cache rules

| Rule | Expression | Behaviour |
|---|---|---|
| Never cache scans | `http.request.method eq "POST" or http.request.uri.path matches "^/verify"` | Bypass cache |
| Never cache the worker | `http.request.uri.path eq "/sw.js"` | Bypass cache |
| Never cache the relay | `http.request.uri.path matches "^/ws/"` | Bypass cache (WS passes through) |
| Cache assets briefly | `http.request.uri.path matches "^/static/"` | Edge TTL 10 min, browser TTL 0 — the service worker owns client caching |
| Bypass health | `http.request.uri.path eq "/health"` | Bypass cache, log off |

The taxonomy feed is intentionally **not** edge-cached for long: it is versioned
with the app, and a stale drug table is a clinical risk, not a performance win.

## 6. Upload ceiling and timeouts

- **Rules → Configuration Rules**: `client_max_body_size` equivalent is not
  exposed on the free plan; rely on the 6 MiB app limit and nginx's `7m`.
- Cloudflare's own upload cap (100 MB on free) is far above this app's need.
- **Network → Timeouts**: keep the default 100s read timeout; the batch endpoint
  is capped at 45s at nginx so the user sees the app's own error, not a 524.

## 7. What is still the operator's job

- Rotate `KATHA_VISION_API_KEY` through the platform's secret store (never a
  Cloudflare variable in plaintext, never in a Build log).
- Keep `KATHA_RELAY_SECRET` in the origin environment only; the relay refuses all
  connections when it is absent.
- Alert on `429` rate from Cloudflare and on origin `5xx`; both are the earliest
  signal that the vision budget or a dependency is in trouble.
- Re-run `scripts/check_vision.py` after any key or model change.

"""Production hardening for the hosted (cloud) deployment.  INFRASTRUCTURE ONLY.

Nothing in here computes, filters, rounds or re-orders any market/engine value.  It
sits *around* the existing FastAPI app and only:

  * redacts secrets from error text before it reaches a browser or a log line,
  * builds the CORS policy from the ``ALLOWED_ORIGINS`` environment variable,
  * (production only) rate-limits and bounds the expensive endpoints, validates the
    shape of path/query/body-size input, sets security + no-store headers,
    removes the public API docs, and logs one access line per request WITHOUT the
    query string (an access key can travel there),
  * logs startup / shutdown.

Mode is chosen by the environment variable ``APEX_ENV``:

  ``production``  every guard below is active (set by render.yaml / the Dockerfile)
  anything else   ("local", unset) behaves exactly like the original app: open CORS,
                  no limits, docs available.  Only secret-redaction of error text and
                  the startup log line apply, both harmless.

Environment variables read here (all optional, all server-side):

  APEX_ENV, ALLOWED_ORIGINS, PUBLIC_API_BASE, LOG_LEVEL,
  APEX_RL_HEAVY, APEX_RL_ANALYSIS, APEX_RL_GENERAL, APEX_RL_AUTH   (requests / minute / IP)
  APEX_HEAVY_CONCURRENCY, APEX_MAX_UPLOAD_MB, APEX_MAX_BODY_MB, APEX_TRUST_PROXY_HOPS
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

log = logging.getLogger("apexinvest")
access_log = logging.getLogger("apexinvest.access")

# ------------------------------------------------------------------ settings

def is_production() -> bool:
    return (os.environ.get("APEX_ENV") or "").strip().lower() in ("production", "prod")


def _int_env(name: str, default: int, lo: int = 1, hi: int = 100000) -> int:
    try:
        return max(lo, min(hi, int(str(os.environ.get(name, "")).strip() or default)))
    except ValueError:
        return default


def allowed_origins() -> list[str]:
    """``ALLOWED_ORIGINS="https://a.example.com, https://b.example.com"`` -> cleaned list.

    Only scheme://host[:port] is meaningful for CORS; anything else is dropped (and
    reported at startup). ``*`` is honoured only if literally configured."""
    out: list[str] = []
    for part in (os.environ.get("ALLOWED_ORIGINS") or "").split(","):
        o = part.strip().rstrip("/")
        if not o:
            continue
        if o == "*":
            out.append("*")
            continue
        u = urlsplit(o)
        if u.scheme in ("http", "https") and u.netloc and not u.path and not u.query:
            out.append(f"{u.scheme}://{u.netloc}")
    return out


def public_api_base() -> str:
    """Optional absolute base URL the *mobile app* should call. Empty = same origin
    (the normal case: the app and the API are served by the same server)."""
    raw = (os.environ.get("PUBLIC_API_BASE") or "").strip().rstrip("/")
    if not raw:
        return ""
    u = urlsplit(raw)
    if u.scheme not in ("http", "https") or not u.netloc or u.path or u.query or u.fragment:
        return ""
    if is_production() and u.scheme != "https":
        return ""
    return f"{u.scheme}://{u.netloc}"


def cors_settings() -> dict:
    """kwargs for ``CORSMiddleware``.

    local:       identical to the original prototype setting (any origin).
    production:  only ``ALLOWED_ORIGINS`` (default: none, i.e. same-origin only, which
                 is all the desktop app and the /m app need because the server hosts both)."""
    if not is_production():
        return dict(allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    return dict(
        allow_origins=allowed_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-Apex-Key", "Content-Type", "Accept"],
        max_age=600,
    )

# ------------------------------------------------------------- redaction

def _access_key_values() -> list[str]:
    """The keys configured in APEX_ACCESS_KEYS (same parsing as api/main.py)."""
    out: list[str] = []
    for part in (os.environ.get("APEX_ACCESS_KEYS") or "").split(","):
        part = part.strip()
        if not part:
            continue
        sep = ":" if ":" in part else ("=" if "=" in part else None)
        key = (part.split(sep, 1)[1] if sep else part).strip()
        if key:
            out.append(key)
    return out


def _has_valid_key(scope) -> bool:
    """True if the request presents a configured access key (header X-Apex-Key or ?key=)."""
    keys = _access_key_values()
    if not keys:
        return False
    provided = dict(scope.get("headers", [])).get(b"x-apex-key", b"").decode("latin-1").strip()
    if not provided:
        q = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("key")
        provided = (q[0] if q else "").strip()
    return bool(provided) and any(hmac.compare_digest(provided.encode(), k.encode()) for k in keys)


def _secret_values() -> list[str]:
    vals = [os.environ.get("EODHD_API_KEY"), os.environ.get("APEX_EODHD_KEY")]
    for part in (os.environ.get("APEX_ACCESS_KEYS") or "").split(","):
        part = part.strip()
        if not part:
            continue
        sep = ":" if ":" in part else ("=" if "=" in part else None)
        vals.append(part.split(sep, 1)[1] if sep else part)
    return [v.strip() for v in vals if v and len(v.strip()) >= 4]


_KV_RE = re.compile(r"(?i)\b(api[_-]?token|api[_-]?key|apikey|access[_-]?token|token|key|crumb|password|secret)=([^&\s'\")]+)")
_URL_RE = re.compile(r"https?://([^/\s'\"<>)]+)[^\s'\"<>)]*")
_HDR_RE = re.compile(r"(?i)(x-apex-key|authorization)\s*[:=]\s*\S+")


def sanitize(text: str, limit: int = 400) -> str:
    """Remove anything secret-looking from an error string: configured secret values,
    ``api_token=...``-style parameters, and URL paths/queries (the host is kept so the
    message is still diagnosable)."""
    s = str(text)
    for v in _secret_values():
        s = s.replace(v, "***")
    s = _KV_RE.sub(lambda m: f"{m.group(1)}=***", s)
    s = _HDR_RE.sub(lambda m: f"{m.group(1)}: ***", s)
    s = _URL_RE.sub(lambda m: f"https://{m.group(1)}/…", s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


_TOKEN_PARAM_RE = re.compile(r"(?i)(api[_-]?token|api[_-]?key|apikey)=([^&\s'\")]+)")


def redact_bytes(body: bytes, secrets: list[str]) -> bytes:
    """Strip configured secret values and ``api_token=`` parameters out of a JSON response body.
    Some engine/feed code copies an exception message (which for a failed provider call can contain the
    provider URL incl. its token) into an otherwise-successful 200 body (scanner / portfolio / data-health
    ``error`` fields).  This guarantees a server-side secret can never reach a browser that way."""
    out = body
    for v in secrets:
        b = v.encode()
        if b in out:
            out = out.replace(b, b"***")
    if b"api_token=" in out or b"api_key=" in out or b"apikey=" in out:
        out = _TOKEN_PARAM_RE.sub(lambda m: f"{m.group(1)}=***", out.decode("utf-8", "replace")).encode()
    return out


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = sanitize(record.getMessage(), limit=2000)
            record.args = ()
            if record.exc_text:
                record.exc_text = sanitize(record.exc_text, limit=8000)
        except Exception:  # never let logging break a request
            pass
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    level = getattr(logging, (os.environ.get("LOG_LEVEL") or "INFO").upper(), logging.INFO)
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root.setLevel(level)
    for h in root.handlers:
        if not any(isinstance(f, _RedactFilter) for f in h.filters):
            h.addFilter(_RedactFilter())
    # third-party HTTP clients log full URLs (incl. api_token) at DEBUG — keep them quiet
    for noisy in ("urllib3", "requests", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

# ------------------------------------------------------------ the guard

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._\-]{1,16}$")
_HEAVY_PREFIXES = ("/v1/scan", "/v1/backtest", "/v1/portfolio")
_ANALYSIS_PREFIXES = ("/v1/analyses", "/v1/uploads", "/v1/fundamentals")
_SYMBOL_PATH_PREFIXES = ("/v1/analyses/auto/", "/v1/fundamentals/", "/v1/backtest/")
_UPLOAD_PATHS = ("/v1/uploads", "/v1/analyses/csv")
_EXEMPT = ("/v1/health", "/v1/auth/status")
_MAX_QUERY = 2048


def _bucket(path: str) -> tuple[str, str]:
    """(bucket name, env var holding its per-minute limit)"""
    if path.startswith(_HEAVY_PREFIXES):
        return "heavy", "APEX_RL_HEAVY"
    if path.startswith("/v1/auth/check"):
        return "auth", "APEX_RL_AUTH"
    if path.startswith(_ANALYSIS_PREFIXES):
        return "analysis", "APEX_RL_ANALYSIS"
    return "general", "APEX_RL_GENERAL"


_DEFAULT_LIMITS = {"heavy": 6, "analysis": 40, "auth": 10, "general": 120}


class ProductionGuard:
    """Pure-ASGI middleware (no response buffering, so streaming/gzip are unaffected)."""

    def __init__(self, app):
        self.app = app
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._fails: dict[str, deque] = defaultdict(deque)     # recent 401s per caller (key guessing)
        self._heavy_inflight = 0
        self._last_gc = time.monotonic()

    # -- helpers
    @staticmethod
    def _client_ip(scope) -> str:
        """Caller address for rate limiting.  Behind the host's load balancer the real peer is the
        address the balancer APPENDED to X-Forwarded-For (the last hop; anything to its left is
        client-supplied and spoofable).  APEX_TRUST_PROXY_HOPS = how many trusted proxies sit in front
        (1 on Render/Railway/Fly).  Without the header we fall back to the socket peer."""
        xff = dict(scope.get("headers", [])).get(b"x-forwarded-for")
        if xff:
            hops = _int_env("APEX_TRUST_PROXY_HOPS", 1)
            parts = [p.strip() for p in xff.decode("latin-1").split(",") if p.strip()]
            if parts:
                return parts[-hops] if len(parts) >= hops else parts[0]
        c = scope.get("client")
        return c[0] if c else "unknown"

    def _rate_limited(self, ip: str, path: str) -> int | None:
        """Return Retry-After seconds if the caller is over its limit, else None."""
        name, env = _bucket(path)
        limit = _int_env(env, _DEFAULT_LIMITS[name])
        now = time.monotonic()
        q = self._hits[(ip, name)]
        while q and now - q[0] > 60.0:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(60.0 - (now - q[0])) + 1)
        q.append(now)
        if now - self._last_gc > 300:                 # bound memory: drop idle callers
            self._last_gc = now
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60.0]:
                self._hits.pop(k, None)
        return None

    def _too_many_auth_failures(self, ip: str) -> bool:
        q = self._fails[ip]
        now = time.monotonic()
        while q and now - q[0] > 60.0:
            q.popleft()
        return len(q) >= _int_env("APEX_RL_AUTH", _DEFAULT_LIMITS["auth"])

    async def _reply(self, send, status: int, detail: str, extra: list[tuple[bytes, bytes]] | None = None):
        body = JSONResponse({"detail": detail}).body
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                   (b"cache-control", b"no-store")] + (extra or [])
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _security_headers(path: str) -> list[tuple[bytes, bytes]]:
        h = [(b"x-content-type-options", b"nosniff"),
             (b"referrer-policy", b"no-referrer"),
             (b"strict-transport-security", b"max-age=31536000"),
             (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")]
        if path == "/m" or path.startswith("/m/"):
            api = public_api_base()
            connect = "'self'" + (f" {api}" if api else "")
            csp = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                   f"img-src 'self' data: blob:; connect-src {connect}; manifest-src 'self'; "
                   "worker-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            h.append((b"content-security-policy", csp.encode()))
            h.append((b"x-frame-options", b"DENY"))
        else:
            h.append((b"x-frame-options", b"SAMEORIGIN"))
        return h

    # -- ASGI
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path: str = scope["path"]
        method: str = scope["method"]
        t0 = time.perf_counter()
        ip = self._client_ip(scope)
        state = {"status": 0, "started": False}

        # --- cheap input validation, before any engine work
        if method != "OPTIONS" and path.startswith("/v1/"):
            if len(scope.get("query_string", b"")) > _MAX_QUERY:
                return await self._reply(send, 414, "Query string too long.")
            for pre in _SYMBOL_PATH_PREFIXES:
                if path.startswith(pre):
                    sym = path[len(pre):]
                    if pre == "/v1/backtest/" and sym == "universe":
                        break
                    if not _SYMBOL_RE.match(sym):
                        return await self._reply(send, 422, "Enter a valid ticker (letters/digits), e.g. COMI.")
                    break

        # --- body size (Content-Length first, then a running count for chunked bodies)
        max_bytes = (_int_env("APEX_MAX_UPLOAD_MB", 15) if path in _UPLOAD_PATHS
                     else _int_env("APEX_MAX_BODY_MB", 5)) * 1024 * 1024
        if method in ("POST", "PUT", "PATCH"):
            cl = dict(scope.get("headers", [])).get(b"content-length")
            if cl is not None:
                try:
                    if int(cl) > max_bytes:
                        return await self._reply(send, 413, f"File too large (limit {max_bytes // 1048576} MB).")
                except ValueError:
                    return await self._reply(send, 400, "Bad Content-Length.")

        # --- rate limit + heavy-endpoint concurrency cap
        heavy = False
        if method != "OPTIONS" and path.startswith("/v1/") and path not in _EXEMPT:
            # A caller that has presented a VALID key is never locked out by someone else's failed guesses
            # (shared mobile-carrier addresses); wrong-key guessing from an address is what gets throttled.
            if not _has_valid_key(scope) and self._too_many_auth_failures(ip):
                return await self._reply(send, 429, "Too many failed access attempts. Wait a minute and try again.",
                                         [(b"retry-after", b"60")])
            wait = self._rate_limited(ip, path)
            if wait is not None:
                return await self._reply(send, 429, "Too many requests. Please wait a moment and try again.",
                                         [(b"retry-after", str(wait).encode())])
            if path.startswith(_HEAVY_PREFIXES):
                if self._heavy_inflight >= _int_env("APEX_HEAVY_CONCURRENCY", 2):
                    return await self._reply(send, 429, "The server is busy with another large analysis. Try again in a minute.",
                                             [(b"retry-after", b"30")])
                self._heavy_inflight += 1
                heavy = True

        received = 0

        async def recv():
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > max_bytes and not state["started"]:
                    # No Content-Length (chunked) and too big: answer 413 ourselves, then tell the app the
                    # client went away.  (Raising here would surface as a 400 — FastAPI wraps body-read errors.)
                    state["started"] = True
                    state["aborted"] = True
                    state["status"] = 413
                    await self._reply(send, 413, f"File too large (limit {max_bytes // 1048576} MB).")
                    return {"type": "http.disconnect"}
            return msg

        secrets = _secret_values()
        chunks: list[bytes] = []
        held: list = []                                   # response.start held back until the JSON body is redacted

        async def send_wrap(message):
            if state.get("aborted"):
                return                                   # 413 already sent; discard whatever the app tries to say
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["started"] = True
                if message["status"] == 401 and path.startswith("/v1/"):
                    self._fails[ip].append(time.monotonic())
                headers = list(message.get("headers", []))
                have = {k.lower() for k, _ in headers}
                for k, v in self._security_headers(path):
                    if k not in have:
                        headers.append((k, v))
                if path.startswith("/v1/") and b"cache-control" not in have:
                    headers.append((b"cache-control", b"no-store"))     # never let a browser/proxy reuse an analysis
                message = {**message, "headers": headers}
                is_json = any(k.lower() == b"content-type" and b"json" in v.lower() for k, v in headers)
                if secrets and is_json:
                    held.append(message)
                    return
            elif message["type"] == "http.response.body" and held:
                # JSON replies are small and complete; the inner BaseHTTPMiddleware streams them in pieces,
                # so gather them, redact once, fix Content-Length, then release start + body together.
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                start = held.pop()
                body = b"".join(chunks)
                new = redact_bytes(body, secrets)
                start = {**start, "headers": [(k, (str(len(new)).encode() if k.lower() == b"content-length" else v))
                                              for k, v in start["headers"]]}
                await send(start)
                message = {"type": "http.response.body", "body": new}
            await send(message)

        try:
            await self.app(scope, recv, send_wrap)
        finally:
            if heavy:
                self._heavy_inflight -= 1
            ms = (time.perf_counter() - t0) * 1000
            lvl = logging.DEBUG if path in _EXEMPT[:1] or path.startswith("/m/") else logging.INFO
            # NOTE: path only — the query string is never logged (an access key may be in it)
            access_log.log(lvl, "%s %s -> %s in %.0f ms (%s)", method, path, state["status"] or "-", ms, ip)

# ------------------------------------------------------------- install

def _log_startup() -> None:
    from ..market import eodhd_egx
    keys = [p for p in (os.environ.get("APEX_ACCESS_KEYS") or "").split(",") if p.strip()]
    origins = allowed_origins()
    log.info("ApexInvest starting: env=%s access_keys=%d eodhd=%s cors_origins=%s public_api_base=%s",
             "production" if is_production() else "local", len(keys),
             "on" if (eodhd_egx and eodhd_egx.enabled()) else "off (Yahoo only)",
             origins or "none (same-origin only)" if is_production() else "any (local)",
             public_api_base() or "same-origin")
    if is_production():
        if not keys:
            log.warning("APEX_ACCESS_KEYS is not set: anyone with the URL can use the analysis API "
                        "(and spend your data-provider quota). Set it in the hosting dashboard.")
        if "*" in origins:
            log.warning("ALLOWED_ORIGINS contains '*' — any website may call this API from a browser.")
        if (os.environ.get("ALLOWED_ORIGINS") or "").strip() and not origins:
            log.warning("ALLOWED_ORIGINS is set but no entry is a valid origin (use https://host, no path).")


def install(app: FastAPI) -> None:
    """Attach the hardening to ``app``.  Call it AFTER the access-key middleware is added
    and BEFORE the CORS middleware, so CORS stays the outermost layer (even 401/429
    replies then carry CORS headers and the browser can read them)."""
    configure_logging()

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request, exc: StarletteHTTPException):      # same JSON shape as before, secrets removed
        detail = sanitize(exc.detail) if isinstance(exc.detail, str) else exc.detail
        return JSONResponse({"detail": detail}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request, exc: Exception):                  # no stack trace / internals to the client
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        _log_startup()
        async with original(a) as state:
            yield state
        log.info("ApexInvest shutdown complete.")

    app.router.lifespan_context = lifespan

    if not is_production():
        return

    # public API docs / schema are a map of the server: off in production
    docs = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in docs]
    app.openapi_url = None
    app.add_middleware(ProductionGuard)

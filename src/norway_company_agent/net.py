"""Bounded HTTP client shared by the Signalpost agent.

Every response keeps its raw bytes, hash, redirect chain and retrieval time so it can be stored as an
immutable snapshot. Company-website requests go through the public-network guard and robots.txt.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .website import assert_public_url

AGENT_VERSION = "signalpost-agent/1.0"
USER_AGENT = "SignalpostResearchAgent/1.0 (+https://builderr.ai/signalpost; company research)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class BudgetExceeded(Exception):
    """Raised when the run deadline has passed before a request could start."""


@dataclass
class Meter:
    """Thread-safe request accounting for one company or one background lane."""

    requests: int = 0
    bytes: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, size: int, elapsed_ms: int) -> None:
        with self.lock:
            self.requests += 1
            self.bytes += size
            self.latencies_ms.append(elapsed_ms)


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int
    retrieved_at: str
    error: str | None = None
    redirect_chain: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and self.error is None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        charset = "utf-8"
        content_type = self.headers.get("content-type", "")
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip().strip('"') or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class _RecordingRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, guard: bool):
        super().__init__()
        self.guard = guard
        self.chain: list[str] = []

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if self.guard:
            assert_public_url(newurl)
        self.chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_host_slots: dict[str, threading.BoundedSemaphore] = {}
_host_slots_lock = threading.Lock()
HOST_CONCURRENCY = {
    "data.brreg.no": 12,
    "pam-stilling-feed.nav.no": 6,
    "www.wikidata.org": 3,
}


def _slot(host: str) -> threading.BoundedSemaphore:
    with _host_slots_lock:
        if host not in _host_slots:
            _host_slots[host] = threading.BoundedSemaphore(HOST_CONCURRENCY.get(host, 2))
        return _host_slots[host]


def get(
    url: str,
    *,
    meter: Meter | None = None,
    accept: str = "*/*",
    timeout: float = 10.0,
    max_bytes: int = 2_000_000,
    attempts: int = 2,
    guard: bool = False,
    deadline: float | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """GET with bounded retries. Never raises for HTTP/network errors; returns status 0 instead."""
    last: Response | None = None
    retried_429 = False
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    for attempt in range(attempts):
        if deadline is not None and time.monotonic() >= deadline:
            raise BudgetExceeded(url)
        started = time.monotonic()
        recorder = _RecordingRedirect(guard)
        opener = urllib.request.build_opener(recorder)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept, **(headers or {})})
        try:
            if guard:
                assert_public_url(url)
            with _slot(host):
                with opener.open(request, timeout=timeout) as response:
                    body = response.read(max_bytes + 1)
                    final_url = response.geturl()
                    status = response.status
                    response_headers = {key.casefold(): value for key, value in response.headers.items()}
            elapsed = int((time.monotonic() - started) * 1000)
            if meter:
                meter.add(len(body), elapsed)
            if guard:
                assert_public_url(final_url)
            if len(body) > max_bytes:
                return Response(url, final_url, status, response_headers, b"", elapsed, utc_now(), "response exceeds byte limit", recorder.chain)
            return Response(url, final_url, status, response_headers, body, elapsed, utc_now(), None, recorder.chain)
        except urllib.error.HTTPError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            try:
                body = exc.read(max_bytes) or b""
            except Exception:
                body = b""
            if meter:
                meter.add(len(body), elapsed)
            last = Response(url, exc.geturl() or url, exc.code, {k.casefold(): v for k, v in (exc.headers or {}).items()}, body, elapsed, utc_now(), f"HTTP {exc.code}", recorder.chain)
            if exc.code == 429 and not retried_429:
                retried_429 = True
                time.sleep(2.5)
                continue
            if exc.code in {400, 401, 403, 404, 410, 429, 451}:
                return last
        except ValueError as exc:  # public-network guard
            elapsed = int((time.monotonic() - started) * 1000)
            if "did not resolve" in str(exc):
                return Response(url, url, 0, {}, b"", elapsed, utc_now(), f"dns: {exc}", recorder.chain)
            return Response(url, url, -1, {}, b"", elapsed, utc_now(), f"blocked: {exc}", recorder.chain)
        except Exception as exc:  # network, TLS, timeout
            elapsed = int((time.monotonic() - started) * 1000)
            if meter:
                meter.add(0, elapsed)
            last = Response(url, url, 0, {}, b"", elapsed, utc_now(), f"{type(exc).__name__}: {str(exc)[:160]}", recorder.chain)
        if attempt + 1 < attempts:
            time.sleep(0.5 * (attempt + 1))
    assert last is not None
    return last


_robots_cache: dict[str, tuple[str, str, urllib.robotparser.RobotFileParser | None]] = {}
_robots_lock = threading.Lock()


def robots_allowed(url: str, *, meter: Meter | None = None, deadline: float | None = None) -> tuple[str, str]:
    """Return ("allowed" | "disallowed" | "unreachable", note).

    RFC 9309: a 4xx robots file allows everything; a 5xx robots file disallows. A host that cannot be
    reached at all is reported as unreachable so the caller can classify the site, not the policy.
    """
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    with _robots_lock:
        cached = _robots_cache.get(origin)
    if cached is None:
        response = get(origin + "/robots.txt", meter=meter, accept="text/plain", timeout=8, max_bytes=500_000, attempts=1, guard=True, deadline=deadline)
        parser = None
        if response.status == -1:
            outcome, note = "disallowed", response.error or "blocked host"
        elif response.status == 0:
            outcome, note = "unreachable", response.error or "host unreachable"
        elif 400 <= response.status < 500:
            outcome, note = "allowed", "robots.txt absent"
        elif response.ok:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(response.text().splitlines())
            outcome, note = "parsed", "robots.txt parsed"
        else:
            # RFC 9309: a 5xx robots file means "do not crawl"; the site is reported as failing, not as refusing.
            outcome, note = "unreachable", f"server error: robots.txt returned {response.status}"
        cached = (outcome, note, parser)
        with _robots_lock:
            _robots_cache[origin] = cached
    outcome, note, parser = cached
    if outcome == "parsed":
        return ("allowed" if parser.can_fetch(USER_AGENT, url) else "disallowed"), note
    return outcome, note

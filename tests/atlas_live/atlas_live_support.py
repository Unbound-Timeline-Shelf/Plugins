"""Support for the live Atlas contract lane: a real-HTTP gateway, an Atlas admin client and the synthetic seed.

Everything here is synthetic. Nothing talks to a service other than the Atlas container the runner started
(``tools/check_metadata_atlas_live.py``), and the plugin under test is the real ``official/metadata-atlas``
module, unmodified.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import time
import zlib
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

# --- the gateway ---------------------------------------------------------------------------------------

MAX_BYTES = 4 * 1024 * 1024
HOST_TIMEOUT_SECONDS = 8  # src/backend/src/plugin_api/outbound.py: outbound_json uses timeout=8
ALLOWED_HEADERS = {"accept", "accept-language", "authorization", "x-emby-token", "x-auth-token", "client-id",
                   "content-type", "user-agent", "referer", "origin", "cookie"}


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib callback signature
        raise ValueError("Redirect refused; configure the final server URL.")


@dataclass
class Call:
    method: str
    url: str
    path: str
    query: str
    status: int
    seconds: float
    headers: dict[str, str] = field(default_factory=dict)


class LiveGateway:
    """Stands in for the host gateway: ``sdk.metadata_provider.request`` goes to a real Atlas over real HTTP.

    ``network.request`` mirrors the host's ``outbound_json`` (plugin_api/outbound.py): URL and header allow-list
    validation, JSON bodies, no redirects, a 4 MiB cap, status 0 for an unreachable server, ``Retry-After``
    mapping and, importantly, the same shape of result. It does NOT mirror the host's egress policy (which
    destinations are reachable); the host grants and egress rules are outside this lane. If the host's
    ``outbound_json`` changes, update this class (the check_host_contract job is the drift guard for schemas only).
    """

    def __init__(self, base_url: str, token: str, *, public_base_url: str | None = None,
                 timeout: float = HOST_TIMEOUT_SECONDS) -> None:
        self.config: dict[str, str] = {"base_url": base_url, "api_token": token}
        if public_base_url:
            self.config["public_base_url"] = public_base_url
        self.timeout = timeout
        self.calls: list[Call] = []
        self.before_request = None  # optional hook: called with the 1-based request number

    # -- sdk.request replacement
    def __call__(self, method: str, capability: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "metadata_providers.configuration":
            assert capability == "metadata_providers.configuration"
            return {"values": dict(self.config)}
        assert method == "network.request" and capability == "network.outbound", (method, capability)
        return self._network(payload or {})

    def _network(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = payload.get("url")
        parts = urlsplit(url) if isinstance(url, str) else None
        assert parts and parts.scheme in {"http", "https"} and parts.hostname and not parts.username \
            and not parts.password and not parts.fragment and not any(c.isspace() for c in url), \
            f"the plugin sent a URL the host would refuse: {url!r}"
        headers = payload.get("headers", {})
        assert isinstance(headers, dict) and len(headers) <= 16, headers
        for key, value in headers.items():
            assert isinstance(value, str) and key.lower() in ALLOWED_HEADERS and "\n" not in key + value, \
                f"the plugin sent a header the host would refuse: {key!r}"
        method = payload.get("method", "GET")
        assert method in {"GET", "POST", "PATCH"}, method
        data = None
        if "body" in payload:
            assert method in {"POST", "PATCH"} and isinstance(payload["body"], dict), payload
            data = json.dumps(payload["body"], allow_nan=False).encode()
            assert len(data) <= 64 * 1024
        request = Request(url, data=data, method=method, headers={
            "Accept": "application/json", **headers, **({"Content-Type": "application/json"} if data else {})})
        number = len(self.calls) + 1
        if self.before_request:
            self.before_request(number)
        started = time.monotonic()
        status, result = 0, {}
        try:
            with build_opener(_NoRedirects()).open(request, timeout=self.timeout) as response:
                body, status = response.read(MAX_BYTES + 1), response.status
            assert len(body) <= MAX_BYTES
            if payload.get("response_format") == "text":
                result = {"status": status, "text": body.decode("utf-8")}
            else:
                result = {"status": status, "data": json.loads(body)}
        except HTTPError as exc:
            status = exc.code
            result = {"status": status, "error": "Remote server rejected the request."}
            retry = exc.headers.get("Retry-After", "")
            if retry.isdecimal():
                result["retry_after_seconds"] = min(int(retry), 3600)
            exc.close()
        except (URLError, OSError, TimeoutError):
            result = {"status": 0, "code": "unreachable", "error": "Cannot reach the remote server; check TLS and egress."}
        self.calls.append(Call(method, url, parts.path, parts.query, status, time.monotonic() - started,
                               {k.lower(): v for k, v in headers.items()}))
        return result

    # -- helpers for assertions
    def paths(self) -> list[str]:
        return [call.path.removeprefix("/api/v2") for call in self.calls]

    def reset(self) -> None:
        self.calls.clear()


# --- the Atlas admin client (seeding only; never used by the plugin) ------------------------------------

class Atlas:
    def __init__(self, base_url: str, container: str) -> None:
        self.base = base_url.rstrip("/")
        self.container = container

    def request(self, method: str, path: str, token: str, body: Any = None, *, root: bool = False,
                raw: bool = False) -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self.base + ("" if root else "/api/v2") + path, data=data, method=method, headers=headers)
        try:
            with build_opener().open(request, timeout=30) as response:
                payload = response.read()
                return response.status, payload if raw else (json.loads(payload) if payload else None)
        except HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(text)
            except ValueError:
                return exc.code, text

    def ok(self, method: str, path: str, token: str, body: Any = None) -> Any:
        status, payload = self.request(method, path, token, body)
        assert 200 <= status < 300, f"{method} {path} -> {status} {str(payload)[:300]}"
        return payload

    def token(self, bootstrap: str, name: str, scopes: list[str]) -> dict[str, Any]:
        return self.ok("POST", "/tokens", bootstrap, {"name": name, "scopes": scopes})

    def observe(self, token: str, source: str, external_id: str, title: str, release_date: str | None, *,
                media_type: str = "game", **fields: Any) -> str:
        observation = {"external_id": external_id, "title": title, **fields}
        if release_date:
            observation["release_date"] = release_date
        result = self.ok("POST", "/observations", token, {
            "connection": {"source_kind": "plugin", "source": source, "source_scope": "live-contract"},
            "media_type": media_type, "observations": [observation]})
        return result["results"][0]["atlas"]["canonical_id"]

    def store_blob(self, data: bytes) -> str:
        """Put an image into the node's media store (as an upload would) and return its sha256 digest."""
        name = hashlib.sha256(data).hexdigest()[:16] + ".png"
        subprocess.run(["docker", "cp", "-", f"{self.container}:/tmp"], input=_tar(name, data),
                       check=True, capture_output=True)
        script = ("from atlas.settings import Settings;from atlas import media;"
                  f"print(media.store(Settings(),open('/tmp/{name}','rb').read(),'png'))")
        done = subprocess.run(["docker", "exec", self.container, "python", "-c", script],
                              check=True, capture_output=True, text=True)
        digest = done.stdout.strip()
        assert digest == hashlib.sha256(data).hexdigest(), done
        return digest


def _tar(name: str, data: bytes) -> bytes:
    import io
    import tarfile
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def png(colour: tuple[int, int, int] = (200, 40, 40)) -> bytes:
    """A valid 1x1 PNG, built with the standard library."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(colour))) + chunk(b"IEND", b""))


def pause(container: str) -> None:
    subprocess.run(["docker", "pause", container], check=True, capture_output=True)


def unpause(container: str) -> None:
    subprocess.run(["docker", "unpause", container], check=False, capture_output=True)


# --- the synthetic seed ---------------------------------------------------------------------------------

def achievements(count: int, *, prefix: str = "Ach", description: str = "", hidden: tuple[int, ...] = (),
                 icon_url: str | None = None) -> list[dict[str, Any]]:
    items = []
    for k in range(count):
        item = {"name": f"{prefix} {k:04d}", "description": f"{description or 'Synthetic achievement'} #{k}",
                "tier": ("bronze", "silver", "gold")[k % 3], "points": 5 * (k % 6 + 1),
                "global_percent": round(90 / (k + 1), 2), "hidden": k in hidden, "external_id": f"src-{k}"}
        if k % 2 == 0:
            item["kind"] = ("progression", "missable", "win_condition")[k % 3]
        if icon_url and k % 4 == 0:
            item["icon_url"] = icon_url
        items.append(item)
    return items


@dataclass
class Seed:
    admin_token: str
    read_token: str
    digest: str
    public: str
    digest_logo: str = ""
    digest_movie: str = ""
    ids: dict[str, str] = field(default_factory=dict)
    steam: dict[str, str] = field(default_factory=dict)
    big_count: int = 450
    heavy_count: int = 120
    hidden_index: int = 4


def seed(atlas: Atlas, bootstrap: str, public: str) -> Seed:
    """Synthetic games with achievements, artwork, an edition set, a DLC-style sibling and conflicting ids."""
    admin = atlas.token(bootstrap, "live-contract-curator", ["read", "contribute", "curate"])["token"]
    reader = atlas.token(bootstrap, "live-contract-reader", ["read"])["token"]
    digest = atlas.store_blob(png())
    logo, poster = atlas.store_blob(png((40, 200, 40))), atlas.store_blob(png((40, 40, 200)))
    icon = f"{public}/media/{digest}"
    out = Seed(admin, reader, digest, public, digest_logo=logo, digest_movie=poster)

    def put(key: str, cid: str) -> str:
        out.ids[key] = cid
        return cid

    # 1. A rich game: metadata, multiplayer facts, cached and uncached artwork, 450 achievements (3 pages).
    out.steam["starlight"] = "5001"
    cid = put("starlight", atlas.observe(
        admin, "steamlike", "S-1", "Starlight Harbor", "2021-03-12", platforms=["PC", "Switch"],
        provider_ids={"steam": "5001"},
        facts={"developer": "Lantern Forge", "publisher": "Open Tide", "series": "Harbor",
               "description": "An exploration game about restoring a lighthouse town.",
               "tags": ["exploration", "cozy"], "genres": ["adventure"], "features": ["Co-op"],
               "critic_score": 82, "user_score": 77, "website": "https://example.invalid/starlight",
               "age_rating": "E10+", "languages": ["English", "French"], "aliases": ["Starlight Harbour"]}))
    atlas.ok("PUT", f"/games/{cid}/custom", admin, {"values": {"players_min": 1, "players_max": 4, "crossplay": "partial"}})
    atlas.ok("PUT", f"/games/{cid}/artwork", admin, {"items": [
        {"kind": "key_art", "url": icon, "width": 1, "height": 1, "priority": 10},
        {"kind": "logo", "url": f"{public}/media/{logo}", "priority": 20},
        {"kind": "banner", "url": "https://example.invalid/never-downloaded.png", "priority": 30}]})
    atlas.ok("PUT", f"/games/{cid}/achievements", admin, {"items": achievements(
        out.big_count, prefix="Harbor", hidden=(out.hidden_index,), icon_url=icon)})

    # 2. Heavy descriptions: one Atlas page is more than the plugin's 56 KiB host page, so it must split mid-page.
    put("cinder", atlas.observe(admin, "gogish", "C-1", "Cinder Circuit", "2019-10-04", platforms=["PC"],
                                provider_ids={"gog": "7002"}, facts={"developer": "Bytewright"}))
    atlas.ok("PUT", f"/games/{out.ids['cinder']}/achievements", admin, {"items": achievements(
        out.heavy_count, prefix="Circuit", description="Heavy description " + "x" * 1800)})

    # 3. Editions: two sources observe one game, one as "Deluxe Edition"; a separate DLC-style record shares a title prefix.
    put("orbit", atlas.observe(admin, "steamlike", "O-1", "Orbit Garden", "2020-05-14", provider_ids={"steam": "5003"}))
    atlas.observe(admin, "gogish", "O-2", "Orbit Garden: Deluxe Edition", "2020-05-14", edition="Deluxe Edition")
    put("orbit_dlc", atlas.observe(admin, "steamlike", "O-3", "Orbit Garden - Night Expansion", "2021-02-02",
                                   provider_ids={"steam": "5004"}))

    # 4. Other media types.
    put("movie", atlas.observe(admin, "manual-film", "M-1", "Midnight Lanterns", "2019-11-02", media_type="movie",
                               facts={"developer": "A. Director", "publisher": "Lantern Pictures"}))
    atlas.ok("PUT", f"/games/{out.ids['movie']}/artwork", admin, {"items": [{"kind": "key_art", "url": f"{public}/media/{poster}"}]})
    put("anime", atlas.observe(admin, "manual-anime", "A-1", "Clockwork Tide", "2020-04-05", media_type="anime"))

    # 5. Two games whose provider ids will collide in one lookup.
    put("twin_a", atlas.observe(admin, "steamlike", "T-1", "Twin Signal", "2018-01-01", provider_ids={"steam": "5101"}))
    put("twin_b", atlas.observe(admin, "gogish", "T-2", "Twin Beacon", "2018-02-02", provider_ids={"gog": "5102"}))

    # 6. No achievements at all.
    put("bare", atlas.observe(admin, "steamlike", "B-1", "Bare Meridian", "2022-06-06", provider_ids={"steam": "5201"}))
    return out

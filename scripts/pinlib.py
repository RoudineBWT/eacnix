"""Helpers shared by the pin automation (standard library only).

Nothing here talks to the Nix store: the scripts read and rewrite the pinned
sources in pkgs/<vendor>/sources.nix as plain text, and the workflows run Nix
afterwards (vendored kernel config refresh, flake check).
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "eacnix-pins/1.0"


# ── HTTP ────────────────────────────────────────────────────────────────────

def http_open(url: str, headers: dict | None = None, retries: int = 3, timeout: int = 120, opener=None):
    """urlopen with a few retries on transient errors. 401/403/404 are raised at once."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            return (opener.open if opener else urllib.request.urlopen)(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise
            last = e
        except urllib.error.URLError as e:
            last = e
        time.sleep(2 ** attempt)
    assert last is not None
    raise last


def http_get(url: str, headers: dict | None = None, opener=None) -> bytes:
    with http_open(url, headers, opener=opener) as resp:
        return resp.read()


def hex_to_sri(hexdigest: str) -> str:
    return "sha256-" + base64.b64encode(bytes.fromhex(hexdigest)).decode()


def sri_of_url(url: str) -> str:
    """Download `url` (streamed) and return its sha256 as an SRI string."""
    h = hashlib.sha256()
    with http_open(url) as resp:
        while chunk := resp.read(1 << 20):
            h.update(chunk)
    return "sha256-" + base64.b64encode(h.digest()).decode()


# ── Apache-style directory listings (Koji, Fedora mirrors) ──────────────────

_HREF = re.compile(r'href="([^"?#]+)"')


def parse_listing(html: str) -> list[str]:
    out = []
    for href in _HREF.findall(html):
        if href.startswith(("/", "..", "http")):
            continue
        out.append(urllib.parse.unquote(href))
    return out


def list_entries(url: str) -> list[str]:
    return parse_listing(http_get(url).decode("utf-8", "replace"))


def list_dirs(url: str) -> list[str]:
    return [e.rstrip("/") for e in list_entries(url) if e.endswith("/")]


def list_files(url: str) -> list[str]:
    return [e for e in list_entries(url) if not e.endswith("/")]


# ── versions ────────────────────────────────────────────────────────────────

def version_key(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def release_key(r: str) -> int:
    m = re.match(r"\d+", r)
    if not m:
        raise ValueError(f"no leading number in release {r!r}")
    return int(m.group())


# ── reading and rewriting the pinned Nix files ──────────────────────────────

def find_block(text: str, path: list[str]) -> tuple[int, int]:
    """Span (inside the braces) of the attribute set at `path`, e.g. ["kernel", "upstream"].

    Braces are counted over the raw text; the pinned files only contain balanced
    ones (including inside "${...}" interpolations).
    """
    lo, hi = 0, len(text)
    for name in path:
        header = re.compile(rf"(?<![\w-]){re.escape(name)} = (?:rec )?\{{")
        m = header.search(text, lo, hi)
        if not m:
            raise KeyError(".".join(path))
        depth, i = 1, m.end()
        while depth and i < hi:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        lo, hi = m.end(), i - 1
    return lo, hi


def _field_re(field: str) -> re.Pattern:
    return re.compile(rf'(?<![\w-]){re.escape(field)} = "([^"]*)";')


def get_field(text: str, path: list[str], field: str) -> str:
    lo, hi = find_block(text, path)
    m = _field_re(field).search(text, lo, hi)
    if not m:
        raise KeyError(f"{'.'.join(path)}.{field}")
    return m.group(1)


def set_field(text: str, path: list[str], field: str, value: str) -> str:
    lo, hi = find_block(text, path)
    m = _field_re(field).search(text, lo, hi)
    if not m:
        raise KeyError(f"{'.'.join(path)}.{field}")
    return text[: m.start(1)] + value + text[m.end(1):]


_LAYER = re.compile(r'akmods = layer "([^"]+)" "([0-9a-f]{64})";')


def get_layer(text: str, path: list[str]) -> tuple[str, str]:
    """(repo, digest) of the `akmods = layer "<repo>" "<digest>";` pin inside `path`."""
    lo, hi = find_block(text, path)
    m = _LAYER.search(text, lo, hi)
    if not m:
        raise KeyError(f"{'.'.join(path)}.akmods")
    return m.group(1), m.group(2)


def set_layer(text: str, path: list[str], digest: str) -> str:
    """Replace the digest of the `akmods = layer "<repo>" "<digest>";` pin inside `path`."""
    lo, hi = find_block(text, path)
    m = _LAYER.search(text, lo, hi)
    if not m:
        raise KeyError(f"{'.'.join(path)}.akmods")
    return text[: m.start(2)] + digest + text[m.end(2):]

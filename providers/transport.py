"""The HTTP seam every live adapter reaches the network through.

One small interface, for two reasons.

**Tests must run with no network and no credentials.** `AGENTS.md` requires the
whole deterministic suite to pass with both absent, so the adapters cannot call
`urllib` directly or they could only ever be tested by talking to a vendor. A
transport that can be substituted lets the real adapter -- the real request
shaping, the real error mapping, the real response parsing -- run against
recorded responses in the same contract suite the fakes run in.

**Secrets must not leak into anything a human or a log will read.** Redaction
belongs here rather than in each adapter, because an adapter that forgets it
produces an error message carrying a bearer token, and that message travels
into logs, review artifacts, and bug reports.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

#: Responses larger than this are refused unread. Provider output is untrusted,
#: and a body is only bounded if it is bounded before it is buffered.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

DEFAULT_TIMEOUT_SECONDS = 60

#: Anything key-shaped, so a leaked credential never reaches a message. Matches
#: bearer headers and long opaque tokens, which is what provider keys look like.
_SECRET = re.compile(
    # The named-field branch swallows an inline scheme word too, so
    # "Authorization: Bearer <key>" redacts the key rather than the word "Bearer".
    r'("?(?:api[_-]?key|authorization|token)"?\s*[:=]\s*"?)(?:bearer\s+)?[A-Za-z0-9._\-]+'
    r"|(bearer\s+)[A-Za-z0-9._\-]+",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Strip anything key-shaped from text before it is shown or stored.

    Deliberately greedy: a false positive costs a reader some context, while a
    false negative puts a live credential in a log.
    """
    return _SECRET.sub(lambda m: f"{m.group(1) or m.group(2) or ''}[redacted]", text)


class TransportError(Exception):
    """The request could not be completed. The message is safe to display."""


@dataclass(frozen=True)
class Response:
    """What came back, with the body already bounded."""

    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError(f"response was not JSON: {redact(str(exc))}") from exc
        if not isinstance(parsed, dict):
            raise TransportError(f"expected a JSON object, got {type(parsed).__name__}")
        return parsed

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        return next((v for k, v in self.headers.items() if k.lower() == lowered), None)


@runtime_checkable
class Transport(Protocol):
    """How an adapter makes one request. Substituted wholesale in tests."""

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Response:
        """Perform the request. Non-2xx statuses are returned, not raised.

        Only a request that could not be completed at all raises
        `TransportError`; an HTTP error carries information the adapter needs in
        order to map it to the right `ProviderError`, so it comes back as a
        `Response`.
        """
        ...


@runtime_checkable
class Opener(Protocol):
    """The narrow slice of `urllib`'s opener this uses.

    Named so the redirect-refusing opener can be substituted in a test without
    reaching around the type system, and so the substitution is checked.
    """

    def open(self, fullurl: Any, data: Any = ..., timeout: float | None = ...) -> Any:
        """Positional names match `urllib.request.OpenerDirector.open`.

        A Protocol matches parameter names as well as types, so a shape that
        merely looked right would not accept the real opener.
        """
        ...


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuses every redirect instead of following it.

    `urllib` follows redirects by default and carries the original request's
    headers into the new one -- including `Authorization`. A redirect to another
    host, or to plaintext HTTP, would therefore hand the provider key to whoever
    sent the `Location`, and the HTTPS check on the original URL cannot see it
    coming.

    No endpoint this talks to redirects. If one starts, that is a change worth
    stopping for rather than following with a credential attached.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise TransportError(
            f"refusing to follow a {code} redirect to {redact(newurl)}: the request "
            f"carries a credential, and a redirect can move it to another host"
        )


@dataclass
class UrllibTransport:
    """The real one. Used by adapters in production and by nothing in tests."""

    max_response_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        self._opener: Opener = urllib.request.build_opener(_NoRedirects)

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Response:
        if not url.startswith("https://"):
            raise TransportError(f"refusing a non-HTTPS request to {redact(url)}")

        request = urllib.request.Request(  # noqa: S310 - scheme checked above
            url, data=body, method=method, headers=dict(headers)
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return Response(
                    status=response.status,
                    body=self._read_bounded(response),
                    headers=dict(response.headers),
                )
        except urllib.error.HTTPError as exc:
            # An HTTP error is a real answer. The adapter decides what it means.
            return Response(
                status=exc.code, body=self._read_bounded(exc), headers=dict(exc.headers or {})
            )
        except urllib.error.URLError as exc:
            raise TransportError(redact(f"could not reach {url}: {exc.reason}")) from exc
        except TimeoutError as exc:
            raise TransportError(redact(f"{url} timed out after {timeout}s")) from exc

    def _read_bounded(self, stream: Any) -> bytes:
        """Read at most the cap, plus one byte to know the cap was exceeded.

        Trusting `Content-Length` would let a lying header through, so the limit
        is enforced on what actually arrives.
        """
        payload = stream.read(self.max_response_bytes + 1)
        if len(payload) > self.max_response_bytes:
            raise TransportError(
                f"response exceeds the {self.max_response_bytes}-byte limit; refused unread"
            )
        return bytes(payload)

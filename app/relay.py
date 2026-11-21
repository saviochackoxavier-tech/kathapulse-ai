"""Zero-retention pharmacist relay (stub).

What this is for
----------------
A patient in a Kochi pharmacy scans two strips, the app says "do not take these
together", and a community pharmacist can be pulled into the same session to
confirm or override — without either side creating an account and without the
server keeping the conversation.

What this deliberately is **not**
---------------------------------
* No storage. Messages are forwarded to the other sockets in the same room and
  then dropped. There is no database, no queue, no transcript, no replay.
* No identifiers. A room is an opaque code handed out by the pharmacy; the
  server never learns a name, a phone number or a scan id.
* No logging. Payloads are never written to the log; only connection counts.
* No open relay. Every socket needs an HMAC ticket derived from
  ``KATHA_RELAY_SECRET``, so an unconfigured deployment refuses all traffic and
  a stranger cannot join a room by guessing its code.

The ticket is ``<unix-expiry>.<hmac-sha256(room:expiry)[:32]>``. It is
single-purpose and short-lived; issuing one belongs to the pharmacy's own
backend, not to this stub.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import defaultdict
from typing import Any

from starlette.websockets import WebSocket

TICKET_TTL_SECONDS = 120
TICKET_SKEW_SECONDS = 30
MAX_MESSAGE_BYTES = 2048
MAX_PEERS_PER_ROOM = 8
SECRET_ENV = "KATHA_RELAY_SECRET"
MIN_SECRET_CHARS = 16


def _secret() -> str:
    return os.environ.get(SECRET_ENV, "")


def configured() -> bool:
    """True only when a real secret is set; an empty secret refuses traffic."""
    return len(_secret()) >= MIN_SECRET_CHARS


def _sign(room: str, expiry: int) -> str:
    message = f"{room}:{expiry}".encode("utf-8")
    return hmac.new(_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()[:32]


def issue_ticket(room: str, ttl: int = TICKET_TTL_SECONDS, now: int | None = None) -> str:
    """Mint a short-lived ticket for one room (used by tests and the pharmacy app)."""
    expiry = int(now if now is not None else time.time()) + ttl
    return f"{expiry}.{_sign(room, expiry)}"


def verify_ticket(room: str, ticket: str, now: int | None = None) -> bool:
    """Constant-time ticket check with a small clock-skew window."""
    if not configured() or not ticket or "." not in ticket:
        return False
    expiry_text, _, signature = ticket.partition(".")
    try:
        expiry = int(expiry_text)
    except ValueError:
        return False
    current = int(now if now is not None else time.time())
    if expiry < current - TICKET_SKEW_SECONDS or expiry > current + TICKET_TTL_SECONDS * 2:
        return False
    return hmac.compare_digest(signature, _sign(room, expiry))


class RelayHub:
    """In-memory fan-out. Rooms vanish when the last socket leaves."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    def peer_count(self, room: str) -> int:
        return len(self._rooms.get(room, ()))

    def is_full(self, room: str) -> bool:
        return self.peer_count(room) >= MAX_PEERS_PER_ROOM

    async def connect(self, room: str, socket: WebSocket) -> None:
        await socket.accept()
        self._rooms[room].add(socket)

    async def disconnect(self, room: str, socket: WebSocket) -> None:
        peers = self._rooms.get(room)
        if not peers:
            return
        peers.discard(socket)
        if not peers:
            # Dropping the empty room is the retention guarantee: nothing about
            # the session survives its last participant.
            self._rooms.pop(room, None)

    async def broadcast(self, room: str, sender: WebSocket, message: str) -> int:
        """Forward one message to the room's other sockets; return how many heard it."""
        delivered = 0
        for peer in list(self._rooms.get(room, ())):
            if peer is sender:
                continue
            try:
                await peer.send_text(message)
                delivered += 1
            except Exception:  # a dead peer must not break the relay
                self._rooms.get(room, set()).discard(peer)
        return delivered

    def stats(self) -> dict[str, Any]:
        """Aggregate counts only — never room codes or messages."""
        return {
            "rooms": len(self._rooms),
            "peers": sum(len(peers) for peers in self._rooms.values()),
        }


HUB = RelayHub()

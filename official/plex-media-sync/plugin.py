"""Official Plex media sync: a personal connection with host-run, resumable sync.

Each handler is a thin binding of the shared engine to the Plex client. See README.md.
"""

from __future__ import annotations

import time

import engine
import plex


def status(values: dict) -> dict:
    return engine.status_action(values, plex)


def connect(values: dict) -> dict:
    return engine.connect_action(values, plex)


def save_libraries(values: dict) -> dict:
    return engine.save_libraries_action(values, plex)


def disconnect(values: dict) -> dict:
    return engine.disconnect_action(values, plex)


def resolve(values: dict) -> dict:
    return engine.resolve_action(values, plex)


def sync(values: dict) -> dict:
    return engine.sync_action(values, plex)


def main() -> None:
    # All work runs in bounded actions started by the page, Connections or the personal
    # schedule; the entrypoint only keeps the runtime alive.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()

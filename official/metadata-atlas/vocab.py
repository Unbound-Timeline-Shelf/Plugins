"""Closed vocabularies the Atlas plugin shares with Atlas and the host (CONTRACTS-v1 C7.4).

Every enum this plugin forwards from Atlas to the host is listed here once, and ``plugin.py`` checks
values against these tuples instead of its own literals. ``contracts/vocab-v1.json`` at the repository
root is generated from this module (``python tools/vocab_check.py generate``) and compared with the files
Atlas and the host publish (``python tools/vocab_check.py compare``). The order of the values is the order
Atlas uses; the comparison treats each vocabulary as a set.

Absent means unknown (C1 rule 1). ``not_applicable`` crossplay is derived from ``players_max == 1`` and is
never stored or sent (C7.2), so it is not a vocabulary value. Standard library only: the module is loaded
by path by the vocabulary tool and imported by the plugin at runtime.
"""

from __future__ import annotations

import json
from typing import Any, Final

VOCAB_VERSION: Final = 1
FILE: Final = "contracts/vocab-v1.json"

ACHIEVEMENT_TIERS: Final = ("bronze", "silver", "gold", "platinum")
# The tiers every Plugin API 1.1.x host accepts; ``platinum`` needs a 1.1.20 contract (C7.1).
LEGACY_ACHIEVEMENT_TIERS: Final = ("bronze", "silver", "gold")
ACHIEVEMENT_KINDS: Final = ("progression", "missable", "win_condition")
CROSSPLAY: Final = ("yes", "partial", "no")
RELATION_TYPES: Final = (
    "version_of",
    "remake_of",
    "remaster_of",
    "port_of",
    "dlc_of",
    "expansion_of",
    "standalone_expansion_of",
    "mod_of",
    "modpack_of",
    "total_conversion_of",
    "series_member",
    "collection_member",
)
DATE_PRECISIONS: Final = ("year", "month", "day")
RELEASE_CATEGORIES: Final = ("full", "early_access", "beta", "rerelease", "port", "demo")
# Books (C15 2.3, Plugin API 1.1.20): an edition's format (identical to the host's `BookFormat`, #265 3.1) and the
# part a creator played in a work.
BOOK_FORMATS: Final = ("paperback", "hardcover", "ebook", "audiobook", "other")
BOOK_CREATOR_ROLES: Final = ("author", "editor", "translator", "illustrator", "narrator", "contributor")


def export() -> dict[str, Any]:
    """The shared file's content, in Atlas's key order. ``feed_kinds`` is Atlas-only and not listed."""
    return {
        "version": VOCAB_VERSION,
        "achievement_tier": list(ACHIEVEMENT_TIERS),
        "achievement_kind": list(ACHIEVEMENT_KINDS),
        "crossplay": list(CROSSPLAY),
        "relation_type": list(RELATION_TYPES),
        "date_precision": list(DATE_PRECISIONS),
        "release_category": list(RELEASE_CATEGORIES),
        "book_format": list(BOOK_FORMATS),
        "book_creator_role": list(BOOK_CREATOR_ROLES),
    }


def render(data: dict[str, Any]) -> str:
    """Two-space indent, keys in the given order, LF and a trailing newline (as Atlas renders)."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

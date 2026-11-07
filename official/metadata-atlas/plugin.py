"""Atlas metadata provider: merged, cross-provider media records from a self-hosted Atlas node."""

import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import vocab
from sdk.metadata_provider import ProviderFailure, ProviderHttp, external_id, operation, provider_values, register

PROVIDER_ID = "official.metadata-atlas.atlas"
MEDIA_TYPES = ("game", "anime", "movie", "tv_show")
DECLARATION = {
    "provider_id": PROVIDER_ID, "name": "Atlas", "identifier_namespace": "atlas",
    "media_types": list(MEDIA_TYPES),
    "metadata_resources": ["entity", "achievements"],
    "operations": {"search": "search", "metadata": "metadata", "media": "media", "health": "health"},
    "configuration": [
        {"key": "base_url", "label": "Atlas API URL", "scope": "both", "secret": False},
        {"key": "public_base_url", "label": "Public Atlas URL (optional)", "scope": "both", "required": False, "secret": False},
        {"key": "api_token", "label": "Atlas API token (read scope)", "scope": "both"},
    ],
}
ASSET_KINDS = {"key_art", "banner", "logo", "icon", "screenshot", "hero", "poster"}
ATLAS_ID = re.compile(r"^atlas:[0-9a-z]{26}$")
# Contract C4.1: the only `/resolve` reasons a client may adopt as an identity. `conflict`, `type_mismatch`,
# `ambiguous`, `fuzzy` and `none` are never adopted.
ADOPTED_REASONS = {"id", "redirect", "crosswalk", "exact"}
# An Atlas that predates `reason` (before contract C4) only has `method`; it counts when it names a certain match
# and the answer carries no `conflict`.
CONFIDENT_MATCHES = {"crosswalk", "exact"}

# Plugin API 1.1.20 (host contract C5.3, C2.6, C7.1) added `first_release`, `releases`, achievement `aliases` and
# the `platinum` tier. The host validates a response against the contract the manifest declares and refuses the
# whole response when it carries a field or value that contract does not have.
RELEASES_CONTRACT = (1, 1, 20)


def declared_contract():
    """The Plugin API contract this package declares in its own manifest, or None when it cannot be read.

    It is the version the host validates our responses against, and a host older than it refuses to install
    the package, so it is the feature switch: nothing newer is sent under an older declaration."""
    try:
        manifest = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
        parts = manifest["api_contract_version"].split(".")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


API_CONTRACT = declared_contract()


def sends_releases():
    """Whether the 1.1.20 fields and values may be sent. An unreadable declaration counts as older."""
    return API_CONTRACT is not None and API_CONTRACT >= RELEASES_CONTRACT


# C5.1 dates: "YYYY", "YYYY-MM" or "YYYY-MM-DD" (ASCII digits); the precision always equals the shape.
PARTIAL_DATE = re.compile(r"\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?", re.ASCII)
DATE_SHAPES = {4: "year", 7: "month", 10: "day"}
# The years the host accepts: year and month values follow C5.1 (1950-2100); a day keeps the host's general
# range (1800-3000), which is also the range of the legacy `year` field.
PARTIAL_YEARS = (1950, 2100)
DAY_YEARS = (1800, 3000)
MAX_RELEASES = 5
RELEASE_REGION = re.compile(r"(ww|eu|na|asia|oce|latam|[a-z]{2})", re.ASCII)
MAX_RELEASE_PLATFORM, MAX_RELEASE_EDITION = 128, 100


def base_url(values):
    """The configured server root. Only a plain http(s) origin plus optional path prefix is accepted."""
    raw = (values.get("base_url") or "").strip().rstrip("/")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password \
            or parts.query or parts.fragment:
        raise ProviderFailure("invalid_configuration")
    return raw


def public_base_url():
    """A browser-reachable Atlas root for artwork and links, defaulting to the API URL."""
    values = provider_values(PROVIDER_ID, ("base_url",))
    return base_url({"base_url": values.get("public_base_url") or values.get("base_url")})


def call(values, path, **options):
    credentials = provider_values(PROVIDER_ID, ("base_url", "api_token"))
    data = ProviderHttp(values["request"], "atlas")(
        base_url(credentials) + "/api/v2" + path,
        headers={"Authorization": "Bearer " + credentials["api_token"], "Accept": "application/json"},
        **options,
    )
    if not isinstance(data, dict):
        raise ProviderFailure("invalid_response")
    return data


def partial_date(value, precision=None):
    """``(value, precision)`` for a C5.1 date the host accepts, else None. Nothing is guessed or padded:
    "2011" stays a year and is never sent as 1 January."""
    if not isinstance(value, str) or not PARTIAL_DATE.fullmatch(value):
        return None
    shape = DATE_SHAPES[len(value)]
    if shape not in vocab.DATE_PRECISIONS or precision not in (None, shape):
        return None
    if shape == "day":
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
    low, high = DAY_YEARS if shape == "day" else PARTIAL_YEARS
    return (value, shape) if low <= int(value[:4]) <= high else None


def legacy_day(record):
    """Atlas's legacy `release_date` when it is a real calendar day, else None.

    The key is day-only from Atlas contract C5.2 on, but an older Atlas can serve a curator lock in it ("2011",
    "2011-04", "TBA"). The host's `release_date` is a date, so anything else would fail the whole response."""
    value = record.get("release_date")
    if not isinstance(value, str) or len(value) != 10 or not PARTIAL_DATE.fullmatch(value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def first_release(record):
    """The record's first release as ``{"date", "precision"}`` (Atlas view key `first_release`), or None.

    An Atlas that predates partial dates has no `first_release`; a partial value it serves in the legacy
    `release_date` key (a curator lock such as "2011") is used instead. A malformed value is ignored."""
    first = record.get("first_release")
    if isinstance(first, dict):
        found = partial_date(first.get("date"), first.get("precision"))
    elif first is None and legacy_day(record) is None:
        found = partial_date(record.get("release_date"))
    else:
        found = None
    return {"date": found[0], "precision": found[1]} if found else None


def release_year(record):
    """The year of the first release (at any precision), else of the legacy day, inside the host's year range."""
    first = first_release(record)
    value = first["date"] if first else legacy_day(record)
    year = int(value[:4]) if value else None
    return year if year is not None and DAY_YEARS[0] <= year <= DAY_YEARS[1] else None


def _release_text(value, limit):
    """An optional one-line release field: None when absent, False when present but unusable."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return False
    text = " ".join(value.split())
    return text if 0 < len(text) <= limit and text.isprintable() else False


def releases(record):
    """Atlas's release entries (view key `releases`, C5.1) that the host accepts, in Atlas's order, at most five.

    An entry with an unusable field is left out rather than altered (a shortened platform or edition would name a
    different entry). Entries are unique on (platform, region, edition, category), compared as Atlas compares them
    (platform and edition case-insensitively), which is stricter than the host's exact comparison."""
    raw = record.get("releases")
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        found = partial_date(item.get("date"), item.get("precision"))
        category = item.get("category", "full")
        platform = _release_text(item.get("platform"), MAX_RELEASE_PLATFORM)
        edition = _release_text(item.get("edition"), MAX_RELEASE_EDITION)
        region = item.get("region")
        if not found or category not in vocab.RELEASE_CATEGORIES or platform is False or edition is False:
            continue
        if region not in (None, "") and not (isinstance(region, str) and RELEASE_REGION.fullmatch(region)):
            continue
        key = ((platform or "").casefold(), region or "", (edition or "").casefold(), category)
        if key in seen:
            continue
        seen.add(key)
        entry = {"date": found[0], "precision": found[1]}
        entry.update({name: value for name, value in (("platform", platform), ("region", region or None),
                                                      ("edition", edition)) if value})
        entry["category"] = category
        out.append(entry)
        if len(out) == MAX_RELEASES:
            break
    return out


def release_fields(record):
    """`release_date`, `year` and, under Plugin API 1.1.20, `first_release` and `releases` for one record.

    `release_date` keeps its day-only meaning. The host refuses a day `first_release` that names another day than
    `release_date`, so such a pair keeps only the legacy day."""
    day, first = legacy_day(record), first_release(record)
    out = {"release_date": day, "year": release_year(record)}
    if not sends_releases():
        return out
    if first and first["precision"] == "day":
        if day is None:
            out["release_date"] = first["date"]
        elif day != first["date"]:
            first = None
    out["first_release"] = first
    out["releases"] = releases(record)
    return out


# The host's `provider_ids` (MetadataCandidate and MetadataPatch): at most 32 keys that start with a letter or digit,
# values of 1-512 characters. Atlas lists every namespace its sources claim, so one record can hold more, and its
# own namespace rule also allows a leading ".", "-" or "_".
HOST_ID_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}", re.ASCII)
HOST_ID_LIMIT, HOST_ID_LENGTH = 32, 512
# Store and catalogue namespaces that name a game (or show) for the host and the person, in the order they are kept
# when a record claims more namespaces than the host's 32: Atlas's own store list (`integrations.STORES`), the
# console stores it scopes by platform, then the anime, film and TV catalogues. Everything else follows, sorted.
WELL_KNOWN_NAMESPACES = ("steam", "igdb", "gog", "epic", "rawg", "itch", "tgdb", "psn", "playstation", "xbox",
                         "microsoft", "nintendo", "anilist", "mal", "kitsu", "anidb", "tmdb", "imdb", "tvdb",
                         "tvmaze")
NAMESPACE_RANK = {name: index for index, name in enumerate(WELL_KNOWN_NAMESPACES)}


def _namespace_order(key):
    return (NAMESPACE_RANK.get(key, len(NAMESPACE_RANK)), key)


def record_provider_ids(record):
    """The record's provider ids as the host accepts them, at most 32 in all: `atlas` first, then the well-known
    store and catalogue namespaces (WELL_KNOWN_NAMESPACES order), then the others in sorted order, so a record whose
    sources claim many obscure namespaces never loses its Steam or IGDB id to the cut. A value that is not a string
    or an integer, or does not fit, is left out (it was sent as ``str(value)`` before, so ``None`` became the id
    "None" and one bad value made the whole response invalid)."""
    ids = {"atlas": record["id"]}
    raw = record.get("provider_ids")
    for key in sorted((key for key in raw if isinstance(key, str)), key=_namespace_order) \
            if isinstance(raw, dict) else []:
        value = raw[key]
        if key == "atlas" or not HOST_ID_KEY.fullmatch(key) or isinstance(value, bool) \
                or not isinstance(value, (str, int)):
            continue
        value = str(value)
        if 0 < len(value) <= HOST_ID_LENGTH:
            ids[key] = value
            if len(ids) == HOST_ID_LIMIT:
                break
    return ids


def candidate(record, media_type="game"):
    media_type = record.get("media_type") if record.get("media_type") in MEDIA_TYPES else media_type
    return {"provider": PROVIDER_ID, "external_id": record["id"], "title": record["title"],
            "media_type": media_type, "provider_ids": record_provider_ids(record), "year": release_year(record)}


# Contract C6.2/C6.4: Atlas's relations block (GET /games/{id}, Atlas A15) as MetadataPatch.relations for a game.
# `parents` and `members_of` are this record's own edges (this -> parent, series or collection); `children` and
# `members` are other records' edges to this one and reach the host with those records' refreshes.
OUTGOING_RELATIONS = ("parents", "members_of")
# A host refresh considers at most 64 relations per result; Atlas allows 200 outgoing relations per record.
RELATION_LIMIT = 64
RELATION_ORDER = {kind: index for index, kind in enumerate(vocab.RELATION_TYPES)}
# What an unknown relation type may look like in the log (no titles, nothing else from the server).
LOGGED_TYPE = re.compile(r"[a-z][a-z0-9_]{0,31}", re.ASCII)
MAX_TITLE = 512


def game_relations(record):
    """The record's outgoing relations in the shared vocabulary, ordered by type (vocabulary order) then Atlas id.

    Only under Plugin API 1.1.20: before it a vocabulary relation had no defined direction and the host does not
    ingest it. The target is named by its Atlas id (the host resolves it through the game that holds that id, or
    keeps it waiting). An unknown type (`edition_of`, `bundle_contains`, anything newer) is left out and logged;
    a malformed entry is left out. An Atlas without relations (before A15) sends none."""
    block = record.get("relations")
    if not sends_releases() or not isinstance(block, dict):
        return []
    own = record.get("id")
    found, unknown = {}, set()
    for name in OUTGOING_RELATIONS:
        items = block.get(name)
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            kind, target, title = item.get("type"), item.get("id"), item.get("title")
            if not isinstance(kind, str) or kind not in RELATION_ORDER:
                if isinstance(kind, str):
                    unknown.add(kind if LOGGED_TYPE.fullmatch(kind) else "?")
                continue
            title = " ".join(title.split()) if isinstance(title, str) else ""
            if not (isinstance(target, str) and ATLAS_ID.fullmatch(target)) or target == own \
                    or not 0 < len(title) <= MAX_TITLE:
                continue
            found.setdefault((kind, target), title)
    if unknown:
        print("Atlas reported relation types this plugin does not know (" + ", ".join(sorted(unknown)[:8])
              + "); they were not sent.", file=sys.stderr, flush=True)
    ordered = sorted(found, key=lambda key: (RELATION_ORDER[key[0]], key[1]))
    if len(ordered) > RELATION_LIMIT:
        print(f"Atlas reported {len(ordered)} relations for one record; the first {RELATION_LIMIT} were sent.",
              file=sys.stderr, flush=True)
    return [{"candidate": {"provider": PROVIDER_ID, "external_id": target, "title": found[(kind, target)],
                           "media_type": "game", "provider_ids": {"atlas": target}},
             "relation": kind, "group": "related"} for kind, target in ordered[:RELATION_LIMIT]]


@operation
def search(values):
    work = values["request"]
    media_type = work.get("media_type", "game")
    if media_type not in MEDIA_TYPES:
        raise ProviderFailure("invalid_response")
    query = urlencode({"q": work["query"], "limit": min(int(work.get("limit", 20)), 50), "type": media_type})
    data = call(values, "/games?" + query)
    return {"candidates": [candidate(record, media_type) for record in data.get("results", [])
                            if record.get("id") and record.get("title")
                            and record.get("media_type", media_type) == media_type]}


def texts(value, limit, size):
    """Up to `limit` distinct short strings; anything else from the server is ignored."""
    seen, out = set(), []
    for item in value if isinstance(value, list) else []:
        text = item.strip() if isinstance(item, str) else ""
        if text and len(text) <= size and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return out[:limit]


def group_play(game):
    """Atlas's standard multiplayer fields (players_min, players_max, crossplay), only when valid.

    Atlas allows larger player counts than the host stores (1-32): anything outside is dropped, and
    an inconsistent range is dropped as a whole. Unknown stays unset; nothing is guessed."""
    values = game.get("custom") if isinstance(game.get("custom"), dict) else {}

    def count(key):
        value = values.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 32 else None

    low, high = count("players_min"), count("players_max")
    if low is not None and high is not None and low > high:
        low = high = None
    out = {"players_min": low, "players_max": high}
    # C7.2: only the shared vocabulary. `not_applicable` is derived by the host and never sent; absent is unknown.
    if values.get("crossplay") in vocab.CROSSPLAY:
        out["crossplay"] = values["crossplay"]
    return out


def _custom(record):
    value = record.get("custom")
    return value if isinstance(value, dict) else {}


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100_000 else None


def _join_texts(value, limit, size, total):
    values = texts(value if isinstance(value, list) else [value], limit, size)
    out = []
    length = 0
    for item in values:
        addition = len(item) + (2 if out else 0)
        if length + addition > total:
            break
        out.append(item)
        length += addition
    return ", ".join(out)


def patch(record):
    """Map Atlas's type-labelled fields to the app's provider-neutral media contract."""
    media_type = record.get("media_type", "game")
    if media_type not in MEDIA_TYPES:
        return {}
    custom = _custom(record)
    title = record.get("title")
    age_rating = record.get("age_rating") if isinstance(record.get("age_rating"), str) else None
    website = record.get("website") if isinstance(record.get("website"), str) else ""
    scores = {name: record[key] for name, key in (("critic", "critic_score"), ("user", "user_score"))
              if isinstance(record.get(key), int) and not isinstance(record.get(key), bool)
              and 0 <= record[key] <= 100}
    tags = (record.get("tags") if isinstance(record.get("tags"), list) else []) + (
        record.get("themes") if isinstance(record.get("themes"), list) else [])
    out = {
        "title": title,
        **release_fields(record),
        "description": record.get("description"),
        "tags": texts(tags, 128, 128),
        "genres": texts(record.get("genres"), 128, 128),
        "languages": texts(record.get("languages"), 64, 128),
        "alternate_titles": [name for name in texts(record.get("aliases"), 21, 512) if name != title][:20],
        "age_rating": age_rating.strip()[:64] if age_rating else None,
        "links": [{"label": "Website", "url": website}] if website.startswith("https://") and len(website) <= 500
        and not any(c.isspace() for c in website) else [],
        "scores": scores,
        "custom": custom_values(record, media_type),
        "provider_ids": record_provider_ids(record),
    }
    if media_type == "game":
        out.update({
            "developer": record.get("developer"), "publisher": record.get("publisher"),
            "series": record.get("series"), "features": record.get("features") or [],
            "platforms": record.get("platforms") or [], **group_play(record),
            "relations": game_relations(record),
        })
    elif media_type == "movie":
        out["director"] = record.get("developer")
        out["studios"] = texts([record.get("publisher")], 64, 256)
        out["runtime_minutes"] = _count(custom.get("runtime_minutes"))
        out["writer"] = _join_texts(custom.get("writer"), 16, 512, 512) or None
        out["countries"] = texts(custom.get("production_countries"), 64, 128)
    elif media_type == "anime":
        out["studios"] = texts([record.get("developer")], 64, 256)
        custom_format = custom.get("format")
        out["format"] = (custom_format.strip() if isinstance(custom_format, str) and 0 < len(custom_format.strip()) <= 64
                         else (texts(record.get("platforms"), 1, 64) or [None])[0])
        out["episode_count"] = _count(custom.get("episode_count"))
        out["tags"] = texts(tags + (record.get("features") or []), 128, 128)
        if record.get("series"):
            out["custom"] = {**out["custom"], "franchise": record["series"]}
    else:  # tv_show
        out["creators"] = texts([record.get("developer")], 64, 512)
        network = texts([record.get("publisher")], 1, 256)
        out["episode_count"] = _count(custom.get("episode_count"))
        out["episode_runtime_minutes"] = _count(custom.get("episode_runtime_minutes"))
        if network:
            out["custom"] = {**out["custom"], "network": network[0]}
        if record.get("series"):
            out["custom"] = {**out["custom"], "franchise": record["series"]}
    return {key: value for key, value in out.items() if value not in (None, "", [], {})}


def custom_values(record, media_type="game"):
    """Forward bounded fields Atlas exposes that have no typed app equivalent for this media type."""
    values = _custom(record)
    promoted = {
        "game": {"players_min", "players_max", "crossplay"},
        "movie": {"runtime_minutes", "writer", "production_countries"},
        "anime": {"format", "episode_count"},
        "tv_show": {"episode_count", "episode_runtime_minutes"},
    }.get(media_type, set())
    out = {}
    for key, value in values.items():
        if key in promoted or len(out) >= 32:
            continue
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", key):
            continue
        if isinstance(value, (bool, int)) or (isinstance(value, float) and value == value and abs(value) != float("inf")):
            out[key] = value
        elif isinstance(value, str) and 0 < len(value) <= 500:
            out[key] = value
        elif isinstance(value, list) and 0 < len(value) <= 50 and all(
                isinstance(item, str) and 0 < len(item) <= 200 for item in value):
            out[key] = value
    return out


def adopted(result):
    """Whether one `/resolve` result identifies the game with certainty (contract C4.1/C4.3).

    With `reason` (Atlas from contract C4): only `id`, `redirect`, `crosswalk` and `exact`, and only when no
    `conflict` is reported and the answer names a live record. Without `reason` (an older Atlas): the previous
    rule, `method` in CONFIDENT_MATCHES with no `conflict` key. An unknown future reason is not adopted."""
    if not isinstance(result, dict) or result.get("conflict"):
        return False
    reason = result.get("reason")
    if reason is None:
        return result.get("method") in CONFIDENT_MATCHES
    if reason not in ADOPTED_REASONS:
        return False
    game = result.get("game")
    if not isinstance(game, dict) or not isinstance(game.get("id"), str) or not ATLAS_ID.fullmatch(game["id"]):
        return False
    # the record must be the live one Atlas named: a redirect answers with the id it ended on, not the requested one
    return result.get("canonical_id") in (None, game["id"])


def report_conflict(result):
    """No diagnostic channel exists under Plugin API 1.1.19, so a conflict is logged and nothing is adopted.

    Only Atlas ids and a count are written: no titles, no token, no remote body."""
    conflict = result.get("conflict") if isinstance(result.get("conflict"), dict) else {}
    ids = [item for item in conflict.get("canonical_ids", []) if isinstance(item, str) and ATLAS_ID.fullmatch(item)][:8]
    print("Atlas /resolve reported conflicting identifiers (" + ", ".join(ids or ["?"]) + "); no Atlas identity "
          "was adopted. A curator can settle it in the Atlas review queue.", file=sys.stderr, flush=True)


# What Atlas's `POST /resolve` validates (`ResolveItem`): namespaces `[a-z0-9._-]{1,50}`, ids of 1-256 characters,
# at most 32 of them, and a title of at most 500 characters. Anything larger is answered 422 for the whole request.
RESOLVE_KEY = re.compile(r"[a-z0-9._-]{1,50}", re.ASCII)
RESOLVE_ID_LIMIT, RESOLVE_ID_LENGTH, RESOLVE_TITLE_LENGTH = 32, 256, 500


def resolve_ids(selected):
    """The candidate's identifiers that are identity evidence for Atlas, within Atlas's limits, in sorted order.

    The host lists a candidate's own identity under its *provider id* as well as under the namespace (for a library
    game that is ``local``, whose value is the title): that key is not a namespace and is left out. The Atlas id is
    looked up directly, never through /resolve."""
    raw = selected.get("provider_ids")
    own = selected.get("provider")
    ids = {}
    for key in sorted(key for key in raw if isinstance(key, str)) if isinstance(raw, dict) else []:
        value = raw[key]
        if key in {"atlas", own} or not RESOLVE_KEY.fullmatch(key) or not isinstance(value, str) \
                or not 0 < len(value) <= RESOLVE_ID_LENGTH:
            continue
        ids[key] = value
        if len(ids) == RESOLVE_ID_LIMIT:
            break
    return ids


def resolve(values, selected):
    """Find the Atlas record for a candidate that only carries other providers' identifiers.

    Contract C4.3: a conflicting, ambiguous, cross-type or fuzzy answer is not an identity, so it yields None."""
    return resolve_match(values, selected)[0]


# Contract C4.4 (Plugin API 1.1.20): the identity verdicts the plugin reports with a patch it returns. `conflict` and
# `ambiguous` answers return no patch (C4.3, P2), so they are not reported here.
IDENTITY_MATCHES = {"id", "redirect", "crosswalk", "exact"}


def identity_verdict(match, previous=None):
    """`MetadataPatch.identity` for a record the plugin adopted, or None.

    `previous` is the Atlas id the lookup named when Atlas served another, live record for it (a merge, C4.2): the
    host then rewrites the id it saved to the live one (C4.4 rule 2) instead of keeping the merged-away id and
    depending on Atlas's redirect. Only under a declared contract >= 1.1.20; an older host refuses the field."""
    if not sends_releases() or match not in IDENTITY_MATCHES:
        return None
    verdict = {"match": match}
    if isinstance(previous, str) and ATLAS_ID.fullmatch(previous):
        verdict["previous_ids"] = {"atlas": previous}
    return verdict


def resolve_match(values, selected):
    """`resolve` plus the identity verdict of the answer: ``(record, verdict)``, ``(None, None)`` when nothing was
    adopted."""
    title = selected.get("title")
    evidence = {key: value for key, value in {
        # a shortened title would name another game, so an over-long one is not sent at all
        "title": title if isinstance(title, str) and len(title) <= RESOLVE_TITLE_LENGTH else None,
        "provider_ids": resolve_ids(selected) or None,
    }.items() if value}
    if not evidence:
        return None, None
    item = {**evidence, "media_type": selected.get("media_type", "game")}
    if selected.get("year"):
        item["release_date"] = str(selected["year"])
    data = call(values, "/resolve", method="POST", body={"items": [item], "include_view": True})
    results = data.get("results")
    result = results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else {}
    if result.get("reason") == "conflict" or result.get("conflict"):
        report_conflict(result)
        return None, None
    if not adopted(result):
        return None, None
    game = result.get("game")
    # An Atlas without `reason` (before C4) names the match in `method` (`crosswalk` or `exact`).
    match = result.get("reason") or result.get("method")
    moved = result.get("redirected_from") if match == "redirect" else None
    game_id = game.get("id") if isinstance(game, dict) else None
    return game, identity_verdict(match, moved if moved != game_id else None)


def locate(values, selected):
    """The matching Atlas record, constrained to the selected media type.

    An Atlas id that was merged into another record is served as the live record with `redirected_from` set
    (contract C4.2). Everything built from the record (provider_ids.atlas, the Atlas link, artwork and
    achievement requests) uses the record's own, live id, so the host learns the new id. A redirect that does
    not end on a well-formed Atlas id is refused."""
    return locate_match(values, selected)[0]


def locate_match(values, selected):
    """`locate` plus the identity verdict (C4.4): ``(record, verdict)``, ``(None, None)`` when nothing matched.

    A lookup by the Atlas id the host holds is `id`, or `redirect` with that id in `previous_ids` when Atlas served
    the live record it was merged into; a `/resolve` lookup reports Atlas's own reason."""
    identity = external_id(selected, PROVIDER_ID, "atlas")
    if identity and not ATLAS_ID.match(identity):
        return None, None
    try:
        if identity:
            record = call(values, "/games/" + quote(identity, safe=":"))
            live = record.get("id")
            if live == identity:
                verdict = identity_verdict("id")
            elif record.get("redirected_from") is not None:
                verdict = identity_verdict("redirect", identity)
            else:
                # another record without a redirect: not a move Atlas vouched for, so the host is told nothing
                verdict = None
        else:
            record, verdict = resolve_match(values, selected)
        expected_type = selected.get("media_type", "game")
        if record and record.get("media_type", "game") != expected_type:
            return None, None
        if record and record.get("redirected_from") is not None and not (
                isinstance(record.get("id"), str) and ATLAS_ID.fullmatch(record["id"])):
            return None, None
        return record, verdict
    except ProviderFailure as exc:
        if exc.status == 404:
            return None, None
        raise


ACHIEVEMENT_PAGE_SIZE = 200
ACHIEVEMENT_LIMIT = 2000
# Contract C2.1: the stable per-entry key Atlas derives from the row identity ("ak1:" + 26 base32 characters).
ACHIEVEMENT_KEY = re.compile(r"ak1:[a-z2-7]{26}")
# Migration bridge (contract C2.4): the Atlas row id travels as a source id so the host can re-key a catalogue row
# that was stored under the old, churning row id. It is a valid ActionId and needs no host contract change.
ATLAS_ROW_SOURCE = "atlas.row"
# The host's bound on MetadataAchievement.aliases (Plugin API 1.1.20).
ACHIEVEMENT_ALIAS_LIMIT = 32
# Below the runtime's 64 KiB action output limit, measured as json.dumps of the whole result.
ACHIEVEMENT_PAGE_BYTES = 56 * 1024


def achievement_page(values, game, offset):
    """One Atlas page (API v2 limit/offset) as ``(results, next_offset)``.

    ``None`` when the game has no achievement catalogue (404 on the first page). A failed later page
    raises, so a catalogue is never silently truncated."""
    path = "/games/" + quote(game["id"], safe=":") + "/achievements"
    try:
        data = call(values, path + "?" + urlencode({"limit": ACHIEVEMENT_PAGE_SIZE, "offset": offset}))
    except ProviderFailure as exc:
        if exc.status == 404 and offset == 0:
            return None
        raise
    results = data.get("results", [])
    if not isinstance(results, list):
        raise ProviderFailure("invalid_response")
    following = data.get("next_offset")
    if isinstance(following, bool) or not isinstance(following, int) or following <= offset:
        following = None
    return results, following


def achievement_identity(entry):
    """The host ``external_id`` for an Atlas entry: its stable ``ak1`` key, else the row ``id`` (an older Atlas)."""
    key = entry.get("key")
    if isinstance(key, str) and ACHIEVEMENT_KEY.fullmatch(key):
        return key
    identity = entry.get("id")
    return identity if isinstance(identity, str) else None


def achievement_pages(values, game):
    """Read the whole catalogue in bounded pages.

    A server without paging ignores the parameters and returns everything in one response with no
    next_offset, which ends the loop after the first page. Entries are de-duplicated by achievement key
    (the row id against an Atlas that predates keys)."""
    entries, seen, offset = [], set(), 0
    while True:
        page = achievement_page(values, game, offset)
        if page is None:
            return None
        results, following = page
        for entry in results:
            if not isinstance(entry, dict):
                continue
            identity = achievement_identity(entry)
            if isinstance(identity, str):
                if identity in seen:
                    continue
                seen.add(identity)
            entries.append(entry)
        if following is None or len(entries) >= ACHIEVEMENT_LIMIT:
            return entries
        offset = following


def achievement_item(entry, root):
    """The host's definition for one Atlas achievement, or None when it cannot be forwarded."""
    name = entry.get("name")
    identity = achievement_identity(entry)
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 200:
        return None
    if not isinstance(identity, str) or not 0 < len(identity) <= 200:
        return None
    item = {"name": name.strip(), "external_id": identity, "hidden": entry.get("hidden") is True}
    if isinstance(entry.get("description"), str) and entry["description"].strip():
        item["description"] = entry["description"].strip()[:2000]
    percent = entry.get("global_percent")
    if isinstance(percent, (int, float)) and not isinstance(percent, bool) and 0 <= percent <= 100:
        item["global_percent"] = float(percent)
    for source, target in (("icon_url", "icon_url"), ("locked_icon_url", "locked_icon_url")):
        digest = (entry.get(source) or "").rsplit("/", 1)[-1] if isinstance(entry.get(source), str) else ""
        if re.fullmatch(r"[0-9a-f]{64}", digest):
            item[target] = f"{root}/media/{digest}"
    if entry.get("kind") in vocab.ACHIEVEMENT_KINDS:
        item["kind"] = entry["kind"]
    # C7.1: `platinum` only under Plugin API 1.1.20; an older contract refuses the value, so the tier stays unset.
    if entry.get("tier") in (vocab.ACHIEVEMENT_TIERS if sends_releases() else vocab.LEGACY_ACHIEVEMENT_TIERS):
        item["tier"] = entry["tier"]
    points = entry.get("points")
    if isinstance(points, int) and not isinstance(points, bool) and 0 <= points <= 100_000:
        item["points"] = points
    ids = entry.get("external_ids") if isinstance(entry.get("external_ids"), dict) else {}
    source_ids = {k: v for k, v in ids.items() if isinstance(k, str) and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", k)
                  and isinstance(v, str) and 0 < len(v) <= 512}
    row = entry.get("id")
    if isinstance(row, str) and 0 < len(row) <= 512:
        # The bridge takes one of the eight slots; provider ids a re-key does not need give way first.
        source_ids = {ATLAS_ROW_SOURCE: row, **{k: v for k, v in source_ids.items() if k != ATLAS_ROW_SOURCE}}
    if source_ids:
        item["source_ids"] = dict(list(source_ids.items())[:8])
    aliases = achievement_aliases(entry, identity)
    if aliases:
        item["aliases"] = aliases
    return item


def achievement_aliases(entry, identity):
    """C2.4/C2.6: under Plugin API 1.1.20, the other `ak1` keys of a merged entry (Atlas `keys`), so the host keeps a
    stored definition's id when the anchor key moves. Empty under an older contract, which refuses the field."""
    keys = entry.get("keys")
    if not sends_releases() or not isinstance(keys, list):
        return []
    out = []
    for key in keys:
        if isinstance(key, str) and ACHIEVEMENT_KEY.fullmatch(key) and key != identity and key not in out:
            out.append(key)
    return out[:ACHIEVEMENT_ALIAS_LIMIT]


def achievement_catalogue(values, game, cursor=0):
    """Atlas's achievement definitions (names, descriptions, rarity); never anyone's progress.

    Icons are Atlas's own verified copies, offered through its public /media path like artwork, so the
    host downloads them itself under its public-network rules. Hidden entries arrive redacted from Atlas
    and are forwarded as they come, flagged hidden.

    One Atlas page per host page, under ACHIEVEMENT_PAGE_BYTES, so the runtime's 64 KiB action output
    limit is never reached. ``next_cursor`` is the next unsent Atlas offset; the host merges pages by
    external_id. Entries repeated across pages are de-duplicated by the host merge."""
    if cursor >= ACHIEVEMENT_LIMIT:
        return {"metadata": {"achievements": []}}
    page = achievement_page(values, game, cursor)
    if page is None:
        return {}
    results, following = page
    root = public_base_url()
    items, seen, consumed = [], set(), 0
    size = len(json.dumps({"metadata": {"achievements": []}, "next_cursor": str(ACHIEVEMENT_LIMIT)}))
    for entry in results:
        item = achievement_item(entry, root) if isinstance(entry, dict) else None
        if item is not None and item["external_id"] not in seen:
            cost = len(json.dumps(item)) + 2
            if items and size + cost > ACHIEVEMENT_PAGE_BYTES:
                break
            seen.add(item["external_id"])
            items.append(item)
            size += cost
        consumed += 1
    resume = cursor + consumed if consumed < len(results) else following
    response = {"metadata": {"achievements": items}}
    if resume is not None and resume < ACHIEVEMENT_LIMIT:
        response["next_cursor"] = str(resume)
    return response if items or "next_cursor" in response else {}


def achievement_cursor(request):
    cursor = request.get("cursor")
    if cursor in (None, ""):
        return 0
    if not isinstance(cursor, str) or not cursor.isdigit():
        raise ProviderFailure("invalid_response")
    return int(cursor)


def with_relations(values, record):
    """The record a /resolve answer named, with the relations block that only `GET /games/{id}` carries (C6.3).

    Without it a game the host knows by its Steam or IGDB id would get no relations, while the same game known by its
    Atlas id would. The block is taken only from the same live record; when the read fails, or a merge between the
    two reads answers with another record, the resolved view is used as it is (no relations, nothing else lost)."""
    identity = record.get("id")
    if not isinstance(identity, str) or not ATLAS_ID.fullmatch(identity):
        return record
    try:
        full = call(values, "/games/" + quote(identity, safe=":"))
    except ProviderFailure:
        return record
    if full.get("id") != identity or full.get("redirected_from") is not None or "relations" not in full:
        return record
    return {**record, "relations": full["relations"]}


@operation
def metadata(values):
    selected = values["candidate"]
    media_type = selected.get("media_type", "game")
    if media_type not in MEDIA_TYPES:
        return {}
    record, verdict = locate_match(values, selected)
    if not record or not record.get("title"):
        return {}
    if values["request"].get("resource") == "achievements":
        if media_type != "game":
            return {}
        return achievement_catalogue(values, record, achievement_cursor(values["request"]))
    if media_type == "game" and sends_releases() and "relations" not in record \
            and not external_id(selected, PROVIDER_ID, "atlas"):
        record = with_relations(values, record)
    result = patch(record)
    if verdict and result:
        # C4.4: how the record was found, and the merged-away id the host should follow (rule 2)
        result["identity"] = verdict
    identity = record.get("id")
    if isinstance(identity, str) and ATLAS_ID.fullmatch(identity):
        root = public_base_url()
        result["links"] = [
            {"label": "Atlas record", "url": f"{root}/game/{quote(identity, safe=':')}"},
            *result.get("links", []),
        ]
    return {"metadata": result}


@operation
def media(values):
    """Artwork Atlas has already downloaded and verified, served from its public /media path."""
    selected = values["candidate"]
    media_type = selected.get("media_type", "game")
    if media_type not in MEDIA_TYPES:
        return {"assets": []}
    record = locate(values, selected)
    identity = record and record.get("id")
    if not identity or not ATLAS_ID.match(identity):
        return {"assets": []}
    root = public_base_url()
    try:
        data = call(values, "/games/" + quote(identity, safe=":") + "/artwork")
    except ProviderFailure as exc:
        if exc.status == 404:
            return {"assets": []}
        raise
    assets = []
    for item in data.get("results", []):
        digest = (item.get("media_url") or "").rsplit("/", 1)[-1]
        if item.get("kind") in ASSET_KINDS and re.fullmatch(r"[0-9a-f]{64}", digest):
            kind = item["kind"]
            if media_type != "game" and kind == "key_art":
                kind = "poster"
            asset = {"kind": kind, "url": f"{root}/media/{digest}", "priority": min(len(assets) * 10, 10000)}
            asset.update({k: item[k] for k in ("width", "height") if isinstance(item.get(k), int) and item[k] > 0})
            assets.append(asset)
    return {"assets": assets[:200]}


def health(values):
    result = search({"request": {**values["request"], "query": "portal", "limit": 1}})
    return result if result.get("failure") else {"health": "healthy"}


def main():
    register(DECLARATION)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()

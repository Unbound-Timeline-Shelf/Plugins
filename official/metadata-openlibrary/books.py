"""Open Library responses as the host's book contract (Plugin API 1.1.20, CONTRACT-C15 §3, §6.3).

Pure functions only: no gateway, network or storage. Every value is bounded the way the host's
`MetadataBook`, `MetadataCandidate` and book forms bound it, and nothing is guessed: an unreadable
date, ISBN or format is left out rather than repaired.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# Open Library work and edition ids (C15 §3.3). An author id (`…A`) is not a fetchable record.
WORK_ID = re.compile(r"OL[1-9][0-9]{0,9}W", re.ASCII)
EDITION_ID = re.compile(r"OL[1-9][0-9]{0,9}M", re.ASCII)
AUTHOR_ID = re.compile(r"OL[1-9][0-9]{0,9}A", re.ASCII)

# Host bounds (MetadataBook, MetadataCandidate, BookCreate, BookEditionCreate).
BOOK_YEARS = (1000, 2100)
CANDIDATE_YEARS = (1800, 3000)
MAX_AUTHORS, MAX_EDITIONS, MAX_PAGES = 30, 50, 100_000
MAX_AUTHOR_NAME, MAX_SUBTITLE, MAX_EDITION_TEXT, MAX_LANGUAGE, MAX_KEY = 200, 300, 200, 16, 512
MAX_TITLE = 500
MAX_DESCRIPTION = 50_000
MAX_LABEL = 128
# D15.12: subjects become genres up to ten, the rest tags; the host's book form keeps at most 50 labels each.
SUBJECT_GENRES, MAX_SUBJECT_TAGS = 10, 40
BOOK_FORMATS = ("paperback", "hardcover", "ebook", "audiobook", "other")

ISBN13 = re.compile(r"97[89]\d{10}", re.ASCII)
ISBN10 = re.compile(r"\d{9}[\dX]", re.ASCII)
ISBN_SEPARATORS = re.compile(r"[\s-]+")


# --- ISBN -----------------------------------------------------------------------------------------------------------
def _isbn13_check(first12: str) -> str:
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(first12))
    return str((10 - total % 10) % 10)


def _isbn10_check(first9: str) -> str:
    remainder = (11 - sum(int(digit) * (10 - index) for index, digit in enumerate(first9)) % 11) % 11
    return "X" if remainder == 10 else str(remainder)


def isbn13(value: Any) -> str | None:
    """A normalised ISBN-13 with a right check digit (spaces and hyphens removed), else None."""
    if not isinstance(value, str):
        return None
    value = ISBN_SEPARATORS.sub("", value)
    return value if ISBN13.fullmatch(value) and _isbn13_check(value[:12]) == value[12] else None


def isbn10(value: Any) -> str | None:
    """A normalised ISBN-10 (upper-case ``X``) with a right check digit, else None."""
    if not isinstance(value, str):
        return None
    value = ISBN_SEPARATORS.sub("", value).upper()
    return value if ISBN10.fullmatch(value) and _isbn10_check(value[:9]) == value[9] else None


def isbn10_to_13(value: str) -> str:
    body = "978" + value[:9]
    return body + _isbn13_check(body)


def lookup_isbn(value: Any) -> str | None:
    """The ISBN-13 a typed ISBN names: a valid ISBN-13 or ISBN-10 (spaces and hyphens allowed), else None."""
    found = isbn13(value)
    if found:
        return found
    found = isbn10(value)
    return isbn10_to_13(found) if found else None


def isbn_pair(raw13: list | None, raw10: list | None) -> tuple[str | None, str | None]:
    """``(isbn_13, isbn_10)`` of one edition from Open Library's ISBN lists.

    The first ISBN-13 is used; a present but invalid one leaves both out (the pair is not trusted). An ISBN-10
    alone gives its ISBN-13; an ISBN-10 that names another book than the ISBN-13 is left out."""
    first13 = next(iter(raw13), None) if isinstance(raw13, list) else None
    first10 = next(iter(raw10), None) if isinstance(raw10, list) else None
    found13, found10 = isbn13(first13), isbn10(first10)
    if first13 not in (None, "") and found13 is None:
        return None, None
    if found10 and found13 and isbn10_to_13(found10) != found13:
        found10 = None
    if found10 and not found13:
        found13 = isbn10_to_13(found10)
    return found13, found10


# --- text -----------------------------------------------------------------------------------------------------------
def line(value: Any, limit: int) -> str | None:
    """One printable line of at most `limit` characters (whitespace collapsed), else None."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text if 0 < len(text) <= limit and text.isprintable() else None


def labels(values: Any, limit: int) -> list[str]:
    """Up to `limit` distinct (casefolded) one-line labels of at most 128 characters."""
    out, seen = [], set()
    for value in values if isinstance(values, list) else []:
        text = line(value, MAX_LABEL)
        if text is None or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(text)
        if len(out) == limit:
            break
    return out


def text_value(value: Any) -> str | None:
    """Open Library text: a string or ``{"type": "/type/text", "value": ...}``, bounded for the host."""
    if isinstance(value, dict):
        value = value.get("value")
    if not isinstance(value, str):
        return None
    value = value.replace("\r\n", "\n").strip()
    if not value:
        return None
    return value[:MAX_DESCRIPTION].rstrip()


def bounded_int(value: Any, low: int, high: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None


def key_id(value: Any, pattern: re.Pattern) -> str | None:
    """``OL…W`` from ``/works/OL…W`` (or a bare id) when it matches `pattern`, else None."""
    if not isinstance(value, str):
        return None
    tail = value.rstrip("/").rsplit("/", 1)[-1]
    return tail if pattern.fullmatch(tail) else None


# --- dates ----------------------------------------------------------------------------------------------------------
MONTHS = {name: number for number, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")), start=1) for name in names}
_YEAR = r"(?P<year>\d{4})"
_MONTH = r"(?P<month>[A-Za-z]{3,9})\.?"
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
DATE_SHAPES = (
    re.compile(rf"{_YEAR}", re.ASCII),
    re.compile(rf"{_YEAR}-(?P<mnum>\d{{2}})", re.ASCII),
    re.compile(rf"{_YEAR}-(?P<mnum>\d{{2}})-(?P<day>\d{{2}})", re.ASCII),
    re.compile(rf"{_MONTH},? {_YEAR}", re.ASCII),
    re.compile(rf"{_MONTH} {_DAY},? {_YEAR}", re.ASCII),
    re.compile(rf"{_DAY} {_MONTH},? {_YEAR}", re.ASCII),
)
# "c1965", "c. 1965", "ca. 1965", "©1965", "[1965]", "1965." name a year and nothing finer.
YEAR_ONLY = re.compile(r"(?:c|ca|circa|©|p|℗)?\.?\s*\[?(?P<year>\d{4})\]?\.?", re.ASCII | re.IGNORECASE)


def parse_loose(value: Any) -> dict[str, str] | None:
    """An Open Library free-text date as ``{"date", "precision"}`` at the precision it proves (C15 §3.3).

    "1965" → year, "August 1965" → month, "Aug 01, 1965" → day, "c1965" → year. A date that cannot be read, is
    impossible, uncertain ("1965?", "196-") or outside the host's book years (1000-2100) gives None; a date is never
    invented and a year is never padded to 1 January."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    for shape in DATE_SHAPES:
        found = shape.fullmatch(text)
        if found:
            break
    else:
        found = YEAR_ONLY.fullmatch(text)
        if not found:
            return None
    parts = found.groupdict()
    year = int(parts["year"])
    if not BOOK_YEARS[0] <= year <= BOOK_YEARS[1]:
        return None
    month = None
    if parts.get("mnum"):
        month = int(parts["mnum"])
    elif parts.get("month"):
        month = MONTHS.get(parts["month"].casefold())
        if month is None:
            return None
    if month is None:
        return {"date": f"{year:04d}", "precision": "year"}
    if not 1 <= month <= 12:
        return None
    if not parts.get("day"):
        return {"date": f"{year:04d}-{month:02d}", "precision": "month"}
    try:
        day = date(year, month, int(parts["day"]))
    except ValueError:
        return None
    return {"date": day.isoformat(), "precision": "day"}


def date_key(value: dict[str, str] | None) -> str:
    """A sort key that orders partial dates by their first day; no date sorts first (oldest)."""
    return value["date"] if value else ""


# --- editions -------------------------------------------------------------------------------------------------------
FORMAT_WORDS = (
    ("audiobook", ("audio", "cassette", "mp3", "audible", "sound recording")),
    ("ebook", ("ebook", "e-book", "electronic", "kindle", "epub", "online", "digital")),
    ("hardcover", ("hardcover", "hardback", "hard cover", "library binding", "cloth")),
    ("paperback", ("paperback", "paper back", "mass market", "softcover", "soft cover", "trade paper", "pocket")),
)


def book_format(value: Any) -> str | None:
    """Open Library's free-text `physical_format` as the shared `book_format` vocabulary, else None."""
    text = line(value, MAX_EDITION_TEXT)
    if text is None:
        return None
    lowered = text.casefold()
    for kind, words in FORMAT_WORDS:
        if any(word in lowered for word in words):
            return kind
    return "other"


def language(value: Any) -> str | None:
    """``/languages/eng`` → ``eng`` (Open Library's MARC language codes), else None."""
    if isinstance(value, list):
        value = next(iter(value), None)
    if isinstance(value, dict):
        value = value.get("key")
    code = value.rstrip("/").rsplit("/", 1)[-1] if isinstance(value, str) else None
    return code if code and code.isascii() and code.isalpha() and len(code) <= MAX_LANGUAGE else None


def edition(entry: Any) -> dict[str, Any] | None:
    """One Open Library edition record as the host's `MetadataBookEdition`, or None when nothing usable is left."""
    if not isinstance(entry, dict):
        return None
    found13, found10 = isbn_pair(entry.get("isbn_13"), entry.get("isbn_10"))
    kind = book_format(entry.get("physical_format"))
    publishers = entry.get("publishers")
    publisher = line(next(iter(publishers), None), MAX_EDITION_TEXT) if isinstance(publishers, list) else None
    published = parse_loose(entry.get("publish_date"))
    name = line(entry.get("edition_name"), MAX_EDITION_TEXT)
    if name is None:
        # "<Format>, <publisher> <year>" (C15 §2.6), from whatever is known
        label = line(entry.get("physical_format"), 60)
        tail = " ".join(part for part in (publisher, published["date"][:4] if published else None) if part)
        name = line(", ".join(part for part in (label, tail) if part), MAX_EDITION_TEXT)
    out = {
        "key": key_id(entry.get("key"), EDITION_ID),
        "name": name,
        "isbn_13": found13, "isbn_10": found10,
        "format": kind,
        "publisher": publisher,
        "publish_date": published,
        "page_count": bounded_int(entry.get("number_of_pages"), 1, MAX_PAGES),
        "language": language(entry.get("languages")),
    }
    out = {field: value for field, value in out.items() if value is not None}
    return out if set(out) - {"key"} else None


def editions(entries: Any, first: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """A work's editions as the host keeps them: at most 50, editions with an ISBN first, then newest (C15 §3.1).

    `first` (the edition an ISBN lookup matched) leads the list. A repeated ISBN-13 keeps its first edition in
    that order, because the host refuses a work whose editions repeat an ISBN (#265 §3.2)."""
    mapped = [found for found in map(edition, entries) if found] if isinstance(entries, list) else []
    mapped.sort(key=lambda item: date_key(item.get("publish_date")), reverse=True)
    mapped.sort(key=lambda item: "isbn_13" not in item)
    if first is not None:
        mapped.insert(0, first)
    out, seen_isbns, seen_keys = [], set(), set()
    for item in mapped:
        if item.get("isbn_13") in seen_isbns or (item.get("key") and item["key"] in seen_keys):
            continue
        if "isbn_13" in item:
            seen_isbns.add(item["isbn_13"])
        if item.get("key"):
            seen_keys.add(item["key"])
        out.append(item)
        if len(out) == MAX_EDITIONS:
            break
    return out


# --- works ----------------------------------------------------------------------------------------------------------
def authors(names: Any) -> list[dict[str, str]]:
    """Ordered author names as `MetadataBookAuthor`s (role `author`): one line each, repeats dropped, at most 30."""
    out, seen = [], set()
    for name in names if isinstance(names, list) else []:
        text = line(name, MAX_AUTHOR_NAME)
        if text is None or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append({"name": text, "role": "author"})
        if len(out) == MAX_AUTHORS:
            break
    return out


def work_author_keys(work: dict[str, Any]) -> list[str]:
    """The author ids a work names, in its order."""
    keys = []
    for item in work.get("authors") if isinstance(work.get("authors"), list) else []:
        author = item.get("author") if isinstance(item, dict) else None
        found = key_id(author.get("key") if isinstance(author, dict) else None, AUTHOR_ID)
        if found:
            keys.append(found)
    return keys


def candidate_year(value: Any) -> int | None:
    return bounded_int(value, *CANDIDATE_YEARS)


def first_cover(covers: Any) -> int | None:
    """The first real cover id (Open Library uses -1 for a removed cover)."""
    for value in covers if isinstance(covers, list) else []:
        if bounded_int(value, 1, 10**12):
            return value
    return None


def subjects(work: dict[str, Any]) -> tuple[list[str], list[str]]:
    """``(genres, tags)``: the first ten subjects, then up to forty more (D15.12)."""
    found = labels(work.get("subjects"), SUBJECT_GENRES + MAX_SUBJECT_TAGS)
    return found[:SUBJECT_GENRES], found[SUBJECT_GENRES:]

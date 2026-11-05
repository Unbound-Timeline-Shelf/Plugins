# Media access: preview movies

## Goal

Read a bounded media preview without requesting write or network authority.

## Prerequisites

Use a complete plugin with `media.read` v1 and its permission rationale. Add the
handler to a declared action and page. Jellyfin's `list_media` is a maintained
demo; its additional sync permissions are not needed for this read action.

## Minimal code

<!-- recipe: media -->
```python
from sdk.plugin_protocol import request

def run(values: dict) -> dict:
    return request("media.list", "media.read", {"limit": 100})
```

Return the host's public response rather than depending on database model fields.
Media import is a separate `media.write` operation. Reading movies does not need
`network.outbound`; only an external integration does.

## Test command

```sh
python -m pytest tests/test_feature_tutorials.py -k media
python -m pytest tests/test_jellyfin.py
```

## Expected result

The request uses `media.list`, `media.read` and limit 100, and returns the public
response unchanged. Denied gateway replies fail. In Jellyfin, Preview your host
movies shows the signed-in user's data after the read grant is approved.

## Common mistakes

Copying every Jellyfin permission into a read-only plugin; assuming media write
includes read; accepting a caller-supplied user ID as authority; making an external
request when the host already provides the data.

## Provider sync and enrichment

The demo uses the provider-neutral `media.sync` DTO. The separate
`official/jellyfin-media-sync` preview opts into `sync_mode: "enrich"`, which
supports owned record matching, provider identities, playback percentage/counts,
bounded episode progress and truthful individual sessions. Exact provider IDs or
unique title/year matches may merge; ambiguous/incomplete matches return candidates
for review. Collection IDs do not identify individual films. Stable host links,
episode identities and atomic accepted snapshots prevent duplicate records after
restart. Local ratings fill only when absent; local watch edits require review
when Jellyfin subsequently changes watch state.

These are generic v1 additions on `media.write`; neither plugin gets extra host
access. See the host's [full public contract](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/blob/main/docs/plugin-api-v1.md)
for fields and bounds. Credentials use the private storage broker, and JSON login
POST uses `network.request` under `network.outbound` with verified TLS. A subscribed
background user may receive `notifications.send` only with that separate live grant.

```sh
python -m pytest tests/test_jellyfin_official.py
node --test tests/jellyfin_official_ui.test.mjs
```

# External links: review an explicit destination

## Goal

Let the user intentionally open a fixed HTTPS destination.

## Prerequisites

Use a declared UI action and its real Python handler. Help Button demonstrates
the existing `external_navigation` action contract. Review both the destination
and the user confirmation when adapting it.

## Minimal code and configuration

<!-- recipe: external-links -->
```python
def run(values: dict) -> dict:
    return {"redirect_url": "https://github.com/Unbound-Timeline-Shelf/Plugins"}
```

Add this action to `ui.json` and list its ID in both `manifest.ui.actions` and a page:

```json
{"id": "open-docs", "label": "Open plugin repository", "handler": "plugin:run", "external_navigation": true, "confirmation": "Open the plugin repository in a new tab?"}
```

The host validates the result for this explicitly declared action. This does not
grant arbitrary backend egress or permit silent navigation from ordinary actions.
If your native frontend opens a tab, validate the exact result, clear `opener`,
and close a placeholder tab on failure, as Help Button does.

## Test command

```sh
python -m pytest tests/test_feature_tutorials.py -k external
python -m pytest tests/test_help_button.py -k external
node --test tests/native_frontends.test.mjs
```

## Expected result

The handler returns the fixed HTTPS URL. In the host, user confirmation opens
that destination; cancel leaves the page unchanged. Native tests cover the real
module's contribution and cleanup behavior.

## Common mistakes

Returning an arbitrary URL from user input; opening `javascript:` or credentialed
URLs; leaking tokens in query parameters; leaving a blank tab open after failure;
forgetting `external_navigation` or skipping confirmation in native code.

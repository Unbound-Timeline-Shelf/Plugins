# SDK and gateway calls

The bundled `sdk.plugin_protocol.request` helper writes newline-delimited JSON
to stdout and reads one response from stdin. Each request has `api_version: v1`,
`method`, `capability` and object `payload`. Errors raise `GatewayRequestError`,
a `RuntimeError` subclass that retains the existing message and exposes the
optional public `code` from `error_detail`. Older string-only responses have
`code=None`; existing `except RuntimeError` callers continue to work.

Retry `unavailable` only when the operation is safe to repeat. For example, the
Discord provider's idempotent startup registration waits for the app callback
with bounded backoff. It does not retry `forbidden`, invalid requests or other
permanent errors, and the wait never delivers a notification. Do not blindly
retry library edits, revocations or other actions with side effects.

```python
from sdk.plugin_protocol import request

def refresh(values: dict) -> dict:
    del values
    result = request("games.list", "games.read", {"limit": 50})
    return {"games": result.get("games", result.get("items", []))}
```

## Add a gateway operation

1. Start with a documented operation demonstrated by an existing plugin.
2. Declare its capability and permission at the exact supported version.
3. Validate caller input before requesting work; set bounded limits.
4. Normalize only the fields your logic needs. Keep host data DTOs separate from
   your stored format.
5. Test a successful reply, missing/invalid fields, gateway closure and denial.

The host injects `_plugin_context` into actions; never accept browser-supplied user
or installation identity as authority. SDK requests do not bypass live grants.
`lifecycle.ready` is runtime-local and is not a manifest capability to invent.
The entrypoint stays alive; user-triggered behavior belongs in handlers.

`route_response` and `route_query_value` support the existing JSON route envelope;
see [routes](routes.md). Plugins import the SDK and standard library, never
`src.database`, `src.features` or host test fixtures. A missing public operation
must be solved at the host API boundary, not by copying its implementation here.


## Maintained password recovery (API 1.1.7)

The maintained `official.password-reset` plugin enables the host's reserved password-reset flow. It is separate from the synthetic routing demo. Installation requires the independent critical global `auth.password_reset` grant; an administrator explicitly activates it from **Settings → Administration → Password policy**. Version 1.2.0 uses the API 1.1.11 inline settings slot, with separate save, enable and disable controls and readable expiry units. The host supplies the public request/completion form and owns credentials, validation, single-use redemption and account mutations. Anonymous requests never execute arbitrary plugin code.

Configure a SECURE external recovery-capable destination and separately enable recovery delivery. Built-in SMTP stays in the host; plugin transports also need the independent high-risk provider grant. Core preferences/admin routing and final authority checks still apply. No internal inbox or browser push reset secret, raw SMTP fallback or all-user destination query is provided.

Gateway operations `auth_flows.password_reset.register` (mode/name/lifetime) and `.unregister` require an administrator and this exact installation's explicit global grant. Lifetime is 600–3600 seconds. Configuration changes/withdrawal invalidate outstanding tokens. Public request responses do not reveal account eligibility. Links use fragments, expire and are consumed only by a host POST. Reset revokes sessions, retains API keys and requires normal sign-in. Disable/uninstall/reinstall cannot reuse old credentials. See the [maintained plugin setup](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/official/password-reset).

Startup uses auth_flows.password_reset.restore to resume only an already-active matching installation and definition. Withdrawal or reinstallation requires explicit activation; regranting permission cannot revive an old reset credential.

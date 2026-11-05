# Integration access reference client

`reference-clients/integration-access/` is the packaged, non-Discord reference
consumer of the host's [user-approved integration access](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/blob/main/wiki/docs/integrations/user-delegation.md)
contract. It is for companion apps, automation tools and other independently
hosted integrations. It uses only the versioned public HTTP contract and the Python
standard library.

## Acceptance flow

1. The instance owner enables **Administration → Integration access** and approves the
   client's exact HTTPS origin, or optionally allows requests from any HTTPS origin.
   Origin policy only permits a request; it never grants data access.
2. The client calls `discover()` and shows the target instance ID, then
   `request_access([...])` with only the capabilities it needs. Read-only is the
   default; writes are requested only when the caller lists them.
3. The user signs in to their own instance, reviews the client name, origin, target
   instance and capabilities (writes start unchecked), picks a timed expiry or
   **Until revoked**, and approves a subset or denies.
4. The client polls `exchange()`; approval can be exchanged once.
5. The user can reduce or revoke the grant in **Account → Connected apps**; the owner
   can disable the client or integrations. Rotation replaces the credential without
   adding access or extending expiry.

## Evidence

Each behavior has a test in `tests/test_integration_reference_client.py` (contract
double, runs in CI) and a step in `tools/check_integration_access.py` (real host).
Live run against the host on `main`:

```text
PASS  unapproved origin cannot request
PASS  open-origin registration issues no credential; exchange stays pending until consent
PASS  denial is reported
PASS  exchange is one use
PASS  read-only timed grant sees only the consenting user's library
PASS  other user's game ID is not readable
PASS  write is blocked client-side without consent
PASS  host rejects an unconsented write
PASS  rotation replaces the credential without extending expiry or access
PASS  write to another user's game is refused
PASS  explicit write consent is limited to the consenting user's games
PASS  Until revoked grant has no expiry and survives rotation
PASS  reduced grant loses games access
PASS  grants can be reduced; another user cannot revoke them
PASS  revoked credential is rejected
PASS  disabled client blocks existing ongoing grant
PASS  disabled client blocks new requests
PASS  legacy API key keeps working but is not a delegated credential, and vice versa
```

Timed expiry and the administrator's maximum duration are covered by the contract
double and by the host's own test suite; the live run cannot wait out an expiry.

## Extension points for other identity providers

Keep provider identity and membership in a provider adapter that calls this client
(or the same HTTP contract) and passes `external_account={"provider", "subject",
"username"}` as display context. The host never trusts that label as proof of
ownership, and this package contains no provider code. Discord stays in the
Discord adapter.

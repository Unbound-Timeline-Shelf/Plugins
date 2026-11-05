# Lifecycle conformance and package handoff

Two real-host checks complement source/unit tests. Neither is a fake host and
neither requires plugins to import application internals.

| Requirement | Representative coverage |
| --- | --- |
| Data survives restart and disable/enable | UI/API, Playtime Report, Notifier, Curator through real registry/workers |
| Ordinary update preserves configuration/storage | Same reference packages, plus authenticated Jellyfin HTTP acceptance |
| New permission requires approval | Jellyfin candidate gains `games.read`; automatic checks stage it |
| Denial keeps old release active | Host acceptance adapter explicitly denies the staged scope through authenticated HTTP and checks predecessor/grants/history unchanged; reference suite also aborts a runtime transaction |
| Rollback preserves data | Host-retained predecessor, same identity/configuration/sentinel |
| Reinstall preserves data | Real retained package installed again |
| Failed update restores package | Signed reference candidate has a failing entrypoint; previous manifest and every payload byte restored; Jellyfin acceptance also tests automatic failure |
| Purge destroys data | Existing runtime storage/configuration disappear; host flow resets grants |
| Uninstall destroys plugin data | Reference suite creates fresh nonempty state after purge, then checks package/history/configuration/storage removal |
| Secrets survive retaining transitions, disappear on destructive ones | Jellyfin authenticated acceptance saves a destination-bound write-only token |

## Run and hand off packages

Build an isolated preview using the unchanged package builder:

```sh
python tools/build_packages.py
python tools/distribution.py --root .validation --check-source --include-unreleased
python tools/check_host_contract.py --host-root .validation/host --distribution-root .validation
```

The final command consumes the actual generated `.utp` files and catalogue using
the host's manifest/UI models, verifier and disabled installer. It never enables
an unsigned preview to make a check pass.

Publisher conformance requires the host's rotation policy from
[host PR #28](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/pull/28).
The adapter carries exact plugin IDs, validity windows and reviewed archive pins
alongside prefix scope and channel. Omitting those fields changes the trust policy,
including the official session manager's stable-ID exception. Historical package
bytes and release records remain immutable; the adapter never rebuilds them.

On Linux with the [host prerequisites](index.md) available:

```sh
python tools/check_reference_lifecycle.py --host-root .validation/host
python tools/check_host_lifecycle.py --host-root .validation/host --plugins-root . --work-root /tmp/plugin-acceptance-new --browser
python tools/check_jellyfin_official_lifecycle.py --host-root .validation/host --work-root /tmp/jellyfin-official-new --browser
```

Use an empty work directory and disposable migrated PostgreSQL database for the
host commands. They consume this repository's real sources and builder to create
a signed release sequence with a disposable publisher and an external-service
fixture. Gateway, authentication, permission enforcement, storage and supervised
workers remain real. No production signing key is needed.

The reference suite separately generates ordinary, permission-changing and
failing signed packages in a temporary independent checkout. It calls the actual
runtime transactions and asserts byte/data restoration. Runtime rejection does
not by itself prove the HTTP consent UI; that is the purpose of the second suite.

The adapter runs the unchanged host suite and adds explicit denial at its staged
review HTTP boundary. It sends real authenticated requests and restores its
instrumentation afterward; no response or existing assertion is replaced. The
original suite continues with approval and failed activation/recovery.

Windows can run unit/package/docs tests and disabled host contract inspection.
Real POSIX worker acceptance is the required Linux CI job. Keep failures visible;
do not replace them with skipped tests or mocked health assertions.

The official Jellyfin driver defaults to strict bubblewrap isolation. Its HTTP
fixture implements discovery, library pagination, password login, Quick Connect,
watched/progress DTOs and reported sessions; host records, grants, transactions
and plugin workers are real. It checks multiple accounts, matching, review-safe
local preservation, runtime/host restarts, credential replacement, interrupted
sync recovery, package updates and installed desktop/mobile pages. `--isolation
reduced` is an explicit diagnostic option for systems unable to create namespaces;
it must not be reported as full sandbox validation.

Optional live-server testing is read-only. Pass `--live-url` and `--live-username`
and supply a disposable test key on standard input, never a command argument or
repository file. The driver clears its broker credential even if synchronization
fails. It logs aggregate counts, not users, item titles or credential values.
Live password/Quick Connect approvals and server mutations are deliberately not
performed. Those authentication flows use the disposable HTTP fixture instead.

For a Windows worktree mounted into Linux, Git's absolute Windows metadata path
may not resolve. Set `JELLYFIN_HOST_REVISION` to the actual 40-character host HEAD
obtained on Windows for screenshot provenance; the plugin checkout still requires
working Git metadata. Normal Linux CI derives both revisions directly from Git.

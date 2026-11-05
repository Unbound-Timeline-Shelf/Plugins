# Architecture for plugin authors

The main [Unnamed Tracking application](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf)
is the host. This repository supplies independently packaged behavior, examples,
the public protocol helper and distribution tools. You do not need its database
models or frontend source to write a plugin.

```text
Plugin Manager → inspect package → review permissions → commit installation
                                                        ↓
Browser page → authenticated action → supervised Python process
                                        ↓ public SDK request
                                  Host gateway → scoped application operation
                                        ↓
                              settings / plugin-owned storage
```

| Responsibility | Owner | Author's interface |
| --- | --- | --- |
| Package selection, verification, consent and updates | Host | Manifest and immutable `.utp` |
| Runtime processes, restart and health | Host | `plugin:main`, `lifecycle.ready`, action handlers |
| Authentication, identity and live permission grants | Host | Injected context and gateway responses |
| Application calculations, presentation and integrations | Plugin | Python functions and declared UI/assets |
| Package production, release metadata and catalogue | These tools / your publisher | Existing builder and signed package inputs |

Read [gateway and runtime](runtime.md), [capabilities and permission checks](permissions.md),
and [storage and lifecycle](storage-lifecycle.md) before choosing a larger example.
The [complete author reference](../plugin-author-guide.md) documents the existing
API; tutorials show small uses of it.

Current integration CI targets the host's `plugin-manager` branch. The host's
`main` is not a promise that all these capabilities have shipped. Record the
actual tested host revision and compatibility range for your release.

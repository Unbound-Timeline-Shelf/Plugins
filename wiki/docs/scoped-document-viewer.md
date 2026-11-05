# Scoped Document Viewer: PR #241 behavior comparison

The canonical implementation, permissions, format policy, build instructions and restrictions are documented in the [plugin README](https://github.com/Unbound-Timeline-Shelf/Plugins/tree/main/examples/scoped-document-viewer/README.md). This page is suitable for linking from the plugin examples wiki. The repository's GitHub wiki was unavailable during this implementation; no independent wiki page was published.

Baseline: `Rosefall-a/unnamed_tracking_app` PR #241 head `a9b7d3102c1efec08a5bf11a919c6d2204376ebc`. Platform: `plugin-manager` head `daedc1d8125662065bf27d64ac6311380249a5e6`, including stages 1–4 and later installation/lifecycle fixes. Plugin baseline: `2293839`.

| Behavior | PR #241 actual code | Plugin implementation / regression evidence |
| --- | --- | --- |
| Storage | Existing game `doc` files; host listing synchronizes `GameFileItem` rows | Same host storage, public DTOs and opaque row IDs; game Docs listing includes IDs for direct open; no plugin filesystem access |
| Ownership | Authenticated game ownership helper | Real SQL joins restrict game owner, kind and deletion state; persisted two-user HTTP tests |
| Access boundary | Dedicated `.../files/doc/<filename>/view` | Scoped `documents.list`/`documents.read`, declared actions and authenticated plugin namespace routes; fresh grants each request |
| MIME | PDF signature; text `text/plain`; HTML header hint | Same format decisions; chunked HTML stays `text/plain` with explicit format hint |
| PDF | Native browser iframe | Bundled sandbox PDF.js canvas; actual browser pixel/page tests |
| Text | Strict UTF-8/control checks; literal `<pre>` | Same host policy plus frontend validation and literal `textContent` |
| HTML/XHTML | Plain text transport, DOMPurify HTML profile and forbidden tags/style | Same DOMPurify profile plus inert links, disabled ping and source toggle; malicious SVG/MathML/form/image/script tests |
| SVG/unsupported | Rejected inline; normal download stays separate | Explicit unsupported error; original download is available from both the game Docs row and reader through a scoped attachment API |
| Size | 5 MiB text; no PDF viewer cap | Exact text limit preserved; existing platform cap also limits PDFs; chunks avoid 64 KiB action output failure |
| Traversal | Reject raw/encoded separators; resolve against document root | Same rejection plus game-root confinement and Windows drive/NUL checks; symlink and HTTP row tests |
| Errors | Authorization/missing/oversized/unsupported/server/network | Same distinct user states plus invalid/changed; safe domain errors survive JSON transport |
| Headers | `nosniff`, private/no-store, PDF inline | JSON data/action/route responses preserve `nosniff`, private/no-store; raw uploaded content is never navigated to |
| Upload/rename | Additional host routes and multipart compatibility changes | Unavailable through read-only scoped API; explicitly outside plugin implementation |

`tools/check_document_parity.py` loads the actual baseline helper and updated host policy in external verification tooling, compares 28 format/content cases and six traversal cases, and reports intentional limitations. Plugin runtime source never imports the host. Format equivalence alone is insufficient: host SQL/HTTP authorization tests, frontend sanitizer tests and sandbox PDF tests verify the changed boundaries separately.

Large-PDF inline streaming, native PDF controls, password entry, and upload/rename remain restrictions; they have not been silently substituted with privileged calls. Version 1.5.0 uses `frontend.context.documents` to register the game Docs reader. Clicking a file opens it directly in a new tab; Browse library is optional and the mandatory sidebar section is removed. The reader stays sandboxed and does not request `frontend.native`. Office/OpenDocument support is additive to PR #241: local reading previews, bounded archive validation and inert text/images instead of active uploaded markup.

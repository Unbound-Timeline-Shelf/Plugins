# Build plugins for Unnamed Tracking

Plugins add application behavior through **Plugin API v1**. This repository is
the official collection of working examples, the SDK helper, and the existing
`.utp` build and distribution tools. You can publish your own plugin and catalogue
from an independent repository.

Start with [Create your first plugin](getting-started/first-plugin.md). In one
exercise you will create a manifest, Python entrypoint and action, build an
installable `.utp`, validate it, and try it in Plugin Manager.

| Your next task | Start here |
| --- | --- |
| Install an existing plugin | [Installation and consent](lifecycle/install.md) |
| Understand the architecture | [Host and plugin boundary](architecture/index.md) |
| Add settings, storage or a UI | [Choose a tutorial](development/index.md) |
| Publish independently | [Publishing](publishing/packages.md), then [your own catalogue](publishing/community-catalogue.md) |
| Verify compatibility | [Conformance and lifecycle tests](testing/index.md) |
| Diagnose a failed install/update | [Troubleshooting](troubleshooting/index.md) |
| Audit existing releases | [Release history audit](publishing/release-history.md) |

The **host owns runtime, lifecycle, gateway and permissions**. Plugins provide
application behavior. Declaring a capability does not grant it. A catalogue does
not establish publisher trust. A signature does not approve permissions.

The [author reference](plugin-author-guide.md) and
[catalogue v1 specification](catalogue-specification.md) retain the full contracts.
The [example map](examples/index.md) links small references and real demos.
Historical validation reports record dated evidence, not promises about future
host releases.

The main [application wiki](https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf/tree/main/wiki)
documents users, deployment and application development. This Material wiki
documents independent plugin authors: build, test, sign, publish and recover using
the public contract. Run `python -m mkdocs serve` from this repository to browse it.

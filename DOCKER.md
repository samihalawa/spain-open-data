# Run spain-open-data 0.4.0 in Docker

Build the bundled stdlib Python MCP from this repository root:

```sh
docker build -t spain-open-data:0.4.0 .
docker run --rm -i --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 32 --memory 128m spain-open-data:0.4.0
```

The image launches the existing product-scoped stdio server as UID/GID 65532.
It installs no dependencies, exposes no listening port, needs no API key, and
returns reports without writing files. The official Python base is pinned by
SHA-256 digest. Python and the Europe/Madrid timezone database are in the base.
The source adapters, saved example, product version and logos are unchanged.

An MCP client must keep stdin open and perform MCP initialization before tool
calls. After initialization, use `spain_open_data_demo` for a dated
historical example or `spain_open_data_report` with that demo operation.
For offline examples, additionally pass `--network none` to `docker run`.
Live official-source queries need outbound HTTPS; provider failures remain errors,
not empty searches. No model or account login is part of this container.

The shown `--read-only`, capability and resource restrictions are runtime flags.
The Dockerfile itself sets the nonroot default. No host volumes or secrets are
needed. See [privacy](PRIVACY.md), [security](SECURITY.md) and the product's
[sources](skills/spain-open-data/references/sources.md) before using live queries.

A local image or passing stdio check is not a Docker MCP Catalog listing.
A catalog entry must reference the exact public source commit containing this
Dockerfile, pass the current Docker catalog checks and receive maintainer review.

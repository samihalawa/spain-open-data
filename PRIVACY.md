# Data practices — local MCP skills release 0.4.0

This release contains reusable assistant instructions and one declared, bundled stdio MCP process for the local source adapters. The MCP returns data and report text and does not write report files. Authenticated proxy URLs are rejected before transport; unauthenticated system routing and TLS verification are preserved. It does not provision a publisher-operated server, user account, analytics system or payment system. The source code makes read-only requests to the official data providers listed in the product's sources document. Those requests necessarily include the search text, document identifier, date or cadastral reference needed for the task, and the provider sees the network address of the executing runtime. Do not include credentials or unrelated personal data in queries.

The adapter maintains a bounded memory-only cache for up to five minutes while its process is running. It has no disk response cache, telemetry or persistent user database. Returned results may remain in your assistant conversation, shell output or files you explicitly save, according to the host platform and your settings. The publisher does not control those platforms' retention or data policies.

Native browsing follows the host assistant's own data handling, which is separate from this code. Public source data can still carry personal information and separate reuse conditions. The BORME workflow focuses on company acts, not profiling individuals; Catastro exposes only non-protected descriptive fields.

This document describes the distributed local release. A future hosted MCP service must disclose its actual operator, hosting, logs, retention, security, processors and user-rights contact before deployment or public submission. No such hosted service is part of this release.

Publisher contact: sami@samihalawa.com. Do not send secrets or protected documents in support requests.


## Saved examples and exported reports

Small labelled snapshots of public official records enable offline demonstrations; they are not user-submitted files. The MCP returns report text without writing files; any host-side save writes only to the path selected by the user. Reports include no JavaScript, analytics or external assets. Review them before sharing. Static product pages use no account or analytics system. If served through GitHub Pages, GitHub operates the hosting and may process connection logs under its policies, separate from this software.

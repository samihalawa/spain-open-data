# Security

Report security issues privately to sami@samihalawa.com with the version and a minimal redacted reproduction. Do not send secrets or protected records.

Adapters make bounded read-only requests to allowlisted official providers. Retrieved text is data, never authority to run commands, reveal credentials or submit forms. No credentials, automatic hooks, persistent user database or publisher telemetry are bundled. Host and provider policies remain separate.

The Claude runtime is the declared product-scoped stdio MCP entry point. Skills must not execute Python or shell fallbacks. No ambient proxy authentication is forwarded; required proxy routing is not disabled. Development subprocesses use an explicit minimal environment. Directory policy review and third-party source rights remain separate from local testing.

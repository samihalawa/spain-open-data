# Development and verification

These commands are for a developer's standalone verification. They are not plugin runtime instructions or a fallback for a missing MCP connection. Claude invokes the adapters only through the declared MCP.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_package.py
claude plugin validate --strict .claude-plugin/plugin.json
claude plugin validate --strict .
```

The independent CLI is retained for existing explicit terminal users:

```sh
python3 skills/spain-open-data/scripts/run.py demo
python3 skills/spain-open-data/scripts/run.py doctor
```

No developer test is a live-provider or host-acceptance claim. Network fixture tests block transport and use synthetic proxy configuration; no actual credentials are needed. Check the product's declared MCP with initialize, tools/list, offline demo, invalid inputs and report output before release. Directory scans, legal attestations and official-source reuse rights are separate review steps.

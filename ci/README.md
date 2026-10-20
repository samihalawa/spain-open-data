# Optional CI

`validate.yml` is a ready-to-use GitHub Actions workflow template, not an active workflow. The current publishing credential lacks GitHub workflow-write scope. It was deliberately kept outside `.github/workflows/` rather than attempting to bypass that permission.

The source and installation can be tested without CI: run `python3 scripts/check_package.py`, `claude plugin validate --strict .claude-plugin/plugin.json` and `claude plugin validate --strict .`.

Activating the template requires an authorized credential with workflow-write access and placement in `.github/workflows/validate.yml`.

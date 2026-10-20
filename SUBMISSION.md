# Claude directory submission — Spain Open Data

## Identity

Publisher: **Sami Halawa**. Contact: **sami@samihalawa.com**. Plugin: `spain-open-data`. Release: `0.1.2`. Original software licence: MIT. Third-party data, service access and trademarks retain separate terms.

## Source for the reviewer

Repository: https://github.com/samihalawa/spain-open-data

Plugin folder: repository root (`.`)

Direct folder URL: https://github.com/samihalawa/spain-open-data

The plugin folder contains `.claude-plugin/plugin.json`, an actual icon, four HTTPS documentation/support/policy links, one focused skill, executable adapters and review examples. This is a standalone repository with no sibling-package dependency.

## Listing description

Find a reusable Spanish public dataset and explain its publisher, licence, freshness and practical download options.

## First run

```bash
claude plugin marketplace add samihalawa/spain-open-data
claude plugin install spain-open-data@spain-open-data
```

Prompt: **Find Spanish employment datasets with reusable formats and clear licences.**

Expected scope, sample interaction and negative scenarios are documented in the skill and `skills/spain-open-data/references/examples.md`. They are test specifications, not claims of completed user testing.

## Access and data handling

No reviewer credentials, account signup, payment or third-party API key is needed. Python 3.11+ and provider networking are required for direct adapter execution. The skill can also guide native browsing or supplied-document analysis on supported hosts. No unsupported host capability is promised. This is read-only software; it does not apply for funding, submit bids, look up protected owners or provide legal certification. Read the product's privacy, terms and source-reference files.

## Validation and submission

Run `claude plugin validate --strict .` from this folder using Claude Code 2.1.281 or newer. The optional CI template at `ci/validate.yml` is not active. Actual local Claude strict-validation results are recorded in `evidence/claude-validation.json`; public-source installation is verified separately. Neither a template nor a package manifest constitutes a completed test.

Submit this repository URL; the plugin is at its root through https://claude.ai/directory/manage under the verified publisher account. Official guidance: https://code.claude.com/docs/en/plugins/publish . Portal-specific checks, applicable publisher attestations and Anthropic review remain separate from source publication. Anthropic's directory and the separately curated `claude-plugins-official` marketplace are distinct routes. No submission, approval, official listing or adoption is claimed here.

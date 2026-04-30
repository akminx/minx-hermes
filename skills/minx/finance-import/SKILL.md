---
name: finance-import
description: Deterministic import flow for Robinhood, Discover, and DCU statements uploaded in the finance lane.
version: 4.0.0
author: Minx
metadata:
  hermes:
    tags: [finances, import, csv, pdf, transactions, robinhood, discover, dcu, minx]
---

# Finance Import (Minx)

Import supported finance statement files into Minx through `minx_finance` tools.

This skill is the canonical path for Discord uploads in the finance lane. The
current logical lane is `#finance`; older deployments may still route `#finances`
as a legacy alias. When the
message contains a supported attachment, default to import behavior instead of
making the user spell out the workflow.

## One-Step Discord Contract

If all of the following are true:
- the message is in `#finance` or a configured legacy `#finances` alias
- there is at least one supported attachment (`.csv` or `.pdf`)
- the user did not explicitly say *not* to import

then treat the message as an import request by default.

Do not wait for extra confirmation when the account/source kind is clear.

## Supported Auto-Import Paths

- `Robinhood Gold` + `robinhood_csv`
- `Discover` + `discover_pdf`
- `DCU` + `dcu_csv`
- `DCU` + `dcu_pdf`

`generic_csv` is allowed only when a saved mapping already exists. If the file
would land on `generic_csv` without a mapping, stop and ask one short
clarification.

## Rules

1. Always call `minx_finance.finance_import_preview` before final import.
2. Never use legacy scripts (`finance_import.py`) or disabled legacy MCPs.
3. Minx import only accepts files under the configured staging root. Stage files under `MINX_STAGING_PATH` (default `~/.minx/staging`) first.
4. Keep raw files out of the vault.
5. If the account or format is ambiguous, ask one short clarification instead of guessing.
6. If the message has no supported attachment, do not force an import. Answer normally or ask what file/account the user wants to import.
7. If the message has multiple supported attachments, process them sequentially and report per-file results.

## Attachment Inputs

For Discord uploads, Hermes caches document attachments locally and passes those
cached file paths into the turn context. Use those cached local paths as the
source files for staging.

Do not fetch the Discord CDN URL yourself if a cached local attachment path is
already available.

## Workflow

### 1) Inspect attachments

Look for supported attachment paths from the current message.

Supported file types:
- `.csv`
- `.pdf`

Unsupported uploads:
- images / screenshots
- `.xlsx`
- archives
- anything outside CSV/PDF

If there are no supported files, stop and say what is needed.

### 2) Infer account and source kind

Prefer deterministic signals in this order:

1. File-name pattern
2. Minx source-kind detection / preview result
3. Explicit user text in the current message

Known strong hints:
- `robinhood_transactions.csv` -> `Robinhood Gold` / `robinhood_csv`
- filename containing `discover` and ending in `.pdf` -> `Discover` / `discover_pdf`
- filename containing `free checking transactions.csv` -> `DCU` / `dcu_csv`
- filename starting `stmt_` and ending in `.pdf` -> `DCU` / `dcu_pdf`

If the file/account mapping is still ambiguous after preview, ask one short
clarification like:
`Is this Discover or DCU?`

### 3) Stage under Minx import root

For each file, stage it under:

`~/.minx/staging/discord/YYYY-MM-DD/<original-name>`

Use the staged absolute path as `source_ref`.

### 4) Preview

Call:
- `minx_finance.finance_import_preview(source_ref, account_name, source_kind?)`

Check that:
- sample rows look sane
- spending signs are sane
- detected `source_kind` matches expectation

If preview returns `result_type='clarify'`, stop and ask the single missing
question.

### 5) Import

Call:
- `minx_finance.finance_import(source_ref, account_name, source_kind?)`

If the returned status is not already terminal, poll:
- `minx_finance.finance_job_status(job_id)`

### 6) Optional checks

If the import inserted new rows, you may follow with:
- `minx_finance.safe_finance_summary()`
- `minx_finance.finance_query(...)` for a narrow read-only sanity check

Keep this lightweight. The primary job is successful import.

### 7) Respond

Reply compactly with:
- account imported
- detected source kind
- inserted/skipped counts
- whether the file was already fully duplicated
- any follow-up needed

Example:

`Imported Discover PDF: 42 inserted, 3 skipped (duplicates).`

## Failure Modes

- Unsupported attachment type -> ask for CSV or PDF only.
- Multiple files with mixed account ambiguity -> process the clear ones; ask a short clarification for the unclear ones.
- `generic_csv` without saved mapping -> stop and ask for mapping/account clarification.
- Preview sample looks wrong -> stop before import and say what looked off.
- Import tool returns `failed` -> report the failure, do not invent partial success.

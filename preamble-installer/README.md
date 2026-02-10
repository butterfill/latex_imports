# preamble-installer

YAML-driven installer for TeX Live packages used by your LaTeX preambles.

## Install / run

From repository root:

```bash
cd preamble-installer
uv run preamble-installer --dry-run
uv run preamble-installer
```

Useful options:

```bash
uv run preamble-installer --dry-run
uv run preamble-installer --timeout 120
uv run preamble-installer --config packages.yaml
```

## What it does

1. Finds TeX files from `settings.tex_globs` in `packages.yaml`.
2. Extracts package names from `\usepackage{...}` and `\RequirePackage{...}`.
3. Maps LaTeX package names to `tlmgr` package names via YAML mappings.
4. Adds configured inferred and requested extras.
5. Installs each package one-by-one with progress and per-package timeout.
6. If a `texlive.tlpdb` repository error occurs, it switches to the next configured mirror and retries.

## Edit packages (no code changes)

Open `packages.yaml` and edit:

- `mappings.latex_to_tlmgr`: map LaTeX package names to `tlmgr` names.
- `mappings.requested_aliases`: normalize requested names to actual `tlmgr` names.
- `extras.inferred`: always include these.
- `extras.requested`: your manual package list.
- `settings.install_timeout_seconds`: timeout for each `tlmgr install` call.
- `settings.tlmgr_repositories`: ordered mirror list for `tlmgr option repository`.
- `settings.auto_switch_repository_on_tlpdb_error`: enable automatic fallback mirror switching.
- `settings.repository_switch_timeout_seconds`: timeout for mirror switch command.

After edits, verify:

```bash
uv run preamble-installer --dry-run
```

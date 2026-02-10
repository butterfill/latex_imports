# latex_imports

This repo contains shared LaTeX preambles and tools to install required TeX Live packages.

## Preferred installer (Python + uv)

Use the YAML-driven tool in `preamble-installer/`.

```bash
cd preamble-installer
uv run preamble-installer --dry-run
uv run preamble-installer
```

This installer:

- parses preambles for `\usepackage` and `\RequirePackage`
- maps names via `packages.yaml`
- installs with per-package progress and timeout handling
- lets you add/remove packages by editing YAML only

## Edit package definitions

Edit:

- `preamble-installer/packages.yaml`

Key sections:

- `settings.tex_globs`
- `mappings.latex_to_tlmgr`
- `mappings.requested_aliases`
- `extras.inferred`
- `extras.requested`

Validate config without installing:

```bash
cd preamble-installer
uv run preamble-installer --dry-run
```

## Legacy script

`install-packages-preambles.sh` is still present, but the Python installer above is recommended.

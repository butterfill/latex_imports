#!/usr/bin/env bash
set -euo pipefail

# Install TeX Live packages required by the LaTeX preambles in this directory.
# It resolves \usepackage entries to owning tlmgr packages automatically.

if ! command -v tlmgr >/dev/null 2>&1; then
  echo "Error: tlmgr not found in PATH. Install MacTeX/basicTeX first." >&2
  exit 1
fi

# Find candidate preamble files plus a minimal test doc if present.
mapfile -t tex_files < <(find . -maxdepth 1 -type f \( -name 'preamble*.tex' -o -name 'minimal_doc.tex' \) | sort)
if [[ ${#tex_files[@]} -eq 0 ]]; then
  echo "Error: no preamble*.tex files found in $(pwd)" >&2
  exit 1
fi

# Extract package names from \usepackage{...} and \RequirePackage{...}.
mapfile -t latex_pkgs < <(
  perl -ne '
    s/%.*$//;
    while(/\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}/g){
      $p=$1; $p=~s/\s+//g; print join("\n", split(/,/, $p)),"\n";
    }
    while(/\\RequirePackage(?:\[[^\]]*\])?\{([^}]*)\}/g){
      $p=$1; $p=~s/\s+//g; print join("\n", split(/,/, $p)),"\n";
    }
  ' "${tex_files[@]}" | sed '/^$/d' | sort -u
)

if [[ ${#latex_pkgs[@]} -eq 0 ]]; then
  echo "Error: no \\usepackage entries found in: ${tex_files[*]}" >&2
  exit 1
fi

# Resolve a style/class filename to the owning tlmgr package.
resolve_owner_pkg() {
  local needle="$1"
  local out
  # Typical output has lines like "pkgname:" followed by file paths.
  out="$(tlmgr search --global --file "$needle" 2>/dev/null || true)"
  awk -F: '/^[[:alnum:]][^[:space:]]*:$/ {print $1}' <<<"$out" \
    | grep -Ev '^(collection-|scheme-)' \
    | head -n1
}

# Add unique values to an array by name.
add_unique() {
  local -n arr_ref="$1"
  local item="$2"
  [[ -z "$item" ]] && return 0
  local existing
  for existing in "${arr_ref[@]:-}"; do
    [[ "$existing" == "$item" ]] && return 0
  done
  arr_ref+=("$item")
}

resolved_tl_pkgs=()
unresolved_latex_pkgs=()

for lpkg in "${latex_pkgs[@]}"; do
  owner="$(resolve_owner_pkg "/${lpkg}.sty")"

  # A few entries may be classes in some setups.
  if [[ -z "$owner" ]]; then
    owner="$(resolve_owner_pkg "/${lpkg}.cls")"
  fi

  # Last resort: package name matches tlmgr package name.
  if [[ -z "$owner" ]] && tlmgr info "$lpkg" >/dev/null 2>&1; then
    owner="$lpkg"
  fi

  if [[ -n "$owner" ]]; then
    add_unique resolved_tl_pkgs "$owner"
  else
    add_unique unresolved_latex_pkgs "$lpkg"
  fi
done

# Extras inferred from your preambles:
# - biblatex-chicago is configured with backend=biber
# - fontenc uses LY1 in some preambles
add_unique resolved_tl_pkgs "biber"
ly1_owner="$(resolve_owner_pkg "/ly1enc.def")"
if [[ -n "$ly1_owner" ]]; then
  add_unique resolved_tl_pkgs "$ly1_owner"
else
  add_unique resolved_tl_pkgs "ly1"
fi

# Optional but often needed with fontspec workflows.
if tlmgr info xetex >/dev/null 2>&1; then
  add_unique resolved_tl_pkgs "xetex"
fi

if [[ ${#resolved_tl_pkgs[@]} -eq 0 ]]; then
  echo "Error: failed to resolve TeX Live package names." >&2
  exit 1
fi

# Stable install order for reproducibility.
IFS=$'\n' read -r -d '' -a resolved_tl_pkgs < <(printf '%s\n' "${resolved_tl_pkgs[@]}" | sort -u && printf '\0')

echo "Will install ${#resolved_tl_pkgs[@]} TeX Live packages:"
printf '  %s\n' "${resolved_tl_pkgs[@]}"

if [[ ${#unresolved_latex_pkgs[@]} -gt 0 ]]; then
  echo
  echo "Warning: could not auto-resolve these LaTeX package names (check manually if compile fails):" >&2
  printf '  %s\n' "${unresolved_latex_pkgs[@]}" >&2
fi

echo
echo "Running: tlmgr install ..."
tlmgr install "${resolved_tl_pkgs[@]}"

echo
echo "Done."

#!/usr/bin/env bash
set -euo pipefail

# Install TeX Live packages required by the LaTeX preambles in this directory.
# It resolves \usepackage entries to owning tlmgr packages automatically.

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

if ! command -v tlmgr >/dev/null 2>&1; then
  echo "Error: tlmgr not found in PATH. Install MacTeX/basicTeX first." >&2
  exit 1
fi
log "Found tlmgr: $(command -v tlmgr)"

# Find candidate preamble files plus a minimal test doc if present.
log "Scanning for preamble files..."
mapfile -t tex_files < <(find . -maxdepth 1 -type f \( -name 'preamble*.tex' -o -name 'minimal_doc.tex' \) | sort)
if [[ ${#tex_files[@]} -eq 0 ]]; then
  echo "Error: no preamble*.tex files found in $(pwd)" >&2
  exit 1
fi
log "Found ${#tex_files[@]} TeX file(s)"

# Extract package names from \usepackage{...} and \RequirePackage{...}.
log "Extracting \\usepackage and \\RequirePackage names..."
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
log "Found ${#latex_pkgs[@]} unique LaTeX package name(s)"

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

log "Resolving LaTeX package names to TeX Live packages..."
total_latex_pkgs=${#latex_pkgs[@]}
idx=0
for lpkg in "${latex_pkgs[@]}"; do
  idx=$((idx + 1))
  log "[resolve ${idx}/${total_latex_pkgs}] ${lpkg}"
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
    log "[resolve ${idx}/${total_latex_pkgs}] ${lpkg} -> ${owner}"
  else
    add_unique unresolved_latex_pkgs "$lpkg"
    log "[resolve ${idx}/${total_latex_pkgs}] ${lpkg} -> unresolved"
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

log "Will install ${#resolved_tl_pkgs[@]} TeX Live package(s):"
printf '  %s\n' "${resolved_tl_pkgs[@]}"

if [[ ${#unresolved_latex_pkgs[@]} -gt 0 ]]; then
  echo
  echo "Warning: could not auto-resolve these LaTeX package names (check manually if compile fails):" >&2
  printf '  %s\n' "${unresolved_latex_pkgs[@]}" >&2
fi

echo
log "Starting installation..."
total_tl_pkgs=${#resolved_tl_pkgs[@]}
i=0
failed=()
for pkg in "${resolved_tl_pkgs[@]}"; do
  i=$((i + 1))
  log "[install ${i}/${total_tl_pkgs}] ${pkg}"
  if ! tlmgr install "$pkg"; then
    failed+=("$pkg")
    log "[install ${i}/${total_tl_pkgs}] FAILED: ${pkg}"
  else
    log "[install ${i}/${total_tl_pkgs}] OK: ${pkg}"
  fi
done

echo
if [[ ${#failed[@]} -gt 0 ]]; then
  log "Finished with ${#failed[@]} failure(s):"
  printf '  %s\n' "${failed[@]}" >&2
  exit 1
fi

log "Done."

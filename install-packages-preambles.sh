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

# Map LaTeX package names used in these preambles to TeX Live package names.
# This avoids slow/hanging global tlmgr searches during resolution.
map_latex_to_tlpkg() {
  local lpkg="$1"
  case "$lpkg" in
    amsmath) echo "amsmath" ;;
    array|multicol|varioref|verbatim) echo "tools" ;;
    babel) echo "babel" ;;
    biblatex-chicago) echo "biblatex-chicago" ;;
    booktabs) echo "booktabs" ;;
    caption) echo "caption" ;;
    cleveref) echo "cleveref" ;;
    csquotes) echo "csquotes" ;;
    ctable) echo "ctable" ;;
    enumitem) echo "enumitem" ;;
    fancyhdr) echo "fancyhdr" ;;
    fontenc|inputenc) echo "latex" ;;
    fontspec) echo "fontspec" ;;
    footmisc) echo "footmisc" ;;
    geometry) echo "geometry" ;;
    grffile) echo "grffile" ;;
    hyperref) echo "hyperref" ;;
    libertine) echo "libertine" ;;
    microtype) echo "microtype" ;;
    natbib) echo "natbib" ;;
    setspace) echo "setspace" ;;
    tabu) echo "tabu" ;;
    tex4ht) echo "tex4ht" ;;
    tgpagella) echo "tgpagella" ;;
    titlesec) echo "titlesec" ;;
    titling) echo "titling" ;;
    ulem) echo "ulem" ;;
    url) echo "url" ;;
    wrapfig) echo "wrapfig" ;;
    xunicode) echo "xunicode" ;;
    *)
      # Safe fallback: many LaTeX package names equal tlmgr names.
      echo "$lpkg"
      ;;
  esac
}

resolve_tlmgr_candidate() {
  local name="$1"
  case "$name" in
    graphicx) echo "graphics" ;;
    longtable) echo "tools" ;;
    ifxetex|ifluatex) echo "iftex" ;;
    zapfding) echo "psnfss" ;;
    bibtex) echo "bibtex" ;;
    *) echo "$name" ;;
  esac
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
  owner="$(map_latex_to_tlpkg "$lpkg")"

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
add_unique resolved_tl_pkgs "ly1"

# Additional packages explicitly requested by user.
requested_candidates=(
  amsfonts amsmath
  babel
  geometry graphicx xcolor
  fancyvrb
  longtable booktabs multirow
  csquotes
  iftex ifxetex ifluatex
  lm unicode-math fontspec
  listings
  bibtex biblatex biber
  collection-xetex
  microtype parskip xurl upquote
  footnotehyper unicode-math zapfding
)

log "Resolving user-requested extra package names..."
for req in "${requested_candidates[@]}"; do
  mapped_req="$(resolve_tlmgr_candidate "$req")"
  add_unique resolved_tl_pkgs "$mapped_req"
  log "[requested] ${req} -> ${mapped_req}"
done

# Optional but often needed with fontspec workflows.
add_unique resolved_tl_pkgs "xetex"

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

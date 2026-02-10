from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False)
console = Console()

USEPACKAGE_PATTERN = re.compile(r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]*)\}")


@dataclass
class InstallResult:
    package: str
    status: str
    detail: str


def is_tlpdb_error(detail: str) -> bool:
    lowered = detail.lower()
    return "texlive.tlpdb" in lowered or "could not get texlive.tlpdb" in lowered


def strip_comments(line: str) -> str:
    return re.split(r"(?<!\\\\)%", line, maxsplit=1)[0]


def extract_latex_packages(tex_files: list[Path]) -> list[str]:
    found: set[str] = set()

    for tex_file in tex_files:
        text = tex_file.read_text(encoding="utf-8", errors="ignore")
        text = "\n".join(strip_comments(line) for line in text.splitlines())
        for match in USEPACKAGE_PATTERN.finditer(text):
            names = [part.strip() for part in match.group(1).split(",") if part.strip()]
            found.update(names)

    return sorted(found)


def load_config(config_path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise typer.BadParameter(f"Config file not found: {config_path}") from exc

    if not isinstance(raw, dict):
        raise typer.BadParameter("Config must be a YAML object at top level")
    return raw


def resolve_tex_files(project_dir: Path, tex_globs: list[str], tex_root: Path | None) -> list[Path]:
    base_dir = tex_root.resolve() if tex_root else project_dir
    tex_files: set[Path] = set()

    for pattern in tex_globs:
        for path in base_dir.glob(pattern):
            if path.is_file():
                tex_files.add(path.resolve())

    return sorted(tex_files)


def run_tlmgr_install(tlmgr_cmd: str, package: str, timeout_seconds: int) -> InstallResult:
    cmd = [tlmgr_cmd, "install", package]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return InstallResult(package=package, status="timeout", detail=f"timed out after {timeout_seconds}s")
    except FileNotFoundError:
        return InstallResult(package=package, status="error", detail=f"command not found: {tlmgr_cmd}")

    if proc.returncode == 0:
        return InstallResult(package=package, status="ok", detail="installed")

    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    msg = stderr if stderr else stdout if stdout else f"exit code {proc.returncode}"
    return InstallResult(package=package, status="failed", detail=msg)


def is_tlmgr_package_installed(tlmgr_cmd: str, package: str, timeout_seconds: int) -> tuple[bool, str]:
    cmd = [tlmgr_cmd, "info", "--only-installed", package]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"install-check timed out after {timeout_seconds}s"
    except FileNotFoundError:
        return False, f"command not found: {tlmgr_cmd}"

    if proc.returncode == 0:
        return True, "already installed"

    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    msg = stderr if stderr else stdout if stdout else f"exit code {proc.returncode}"
    return False, msg


def run_tlmgr_option_repository(tlmgr_cmd: str, repository: str, timeout_seconds: int) -> tuple[bool, str]:
    cmd = [tlmgr_cmd, "option", "repository", repository]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_seconds}s while setting repository"
    except FileNotFoundError:
        return False, f"command not found: {tlmgr_cmd}"

    if proc.returncode == 0:
        return True, "repository updated"

    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    msg = stderr if stderr else stdout if stdout else f"exit code {proc.returncode}"
    return False, msg


@app.command()
def main(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to YAML config"),
    tex_root: Path | None = typer.Option(None, help="Optional base dir for tex_globs; defaults to config dir"),
    timeout: int | None = typer.Option(None, help="Override install timeout seconds"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only print resolved package list"),
    verify_only: bool = typer.Option(
        False,
        "--verify-only",
        help="Do not install; only verify all resolved packages are installed",
    ),
) -> None:
    if config is None:
        config_path = (Path(__file__).resolve().parents[2] / "packages.yaml").resolve()
    else:
        config_path = config.resolve()
    config_data = load_config(config_path)

    settings = config_data.get("settings", {})
    mappings = config_data.get("mappings", {})
    extras = config_data.get("extras", {})

    tex_globs = settings.get("tex_globs", ["../preamble*.tex", "../minimal_doc.tex"])
    tlmgr_cmd = settings.get("tlmgr_command", "tlmgr")
    install_timeout = timeout if timeout is not None else int(settings.get("install_timeout_seconds", 180))
    installed_check_timeout = int(settings.get("installed_check_timeout_seconds", 25))
    repo_switch_timeout = int(settings.get("repository_switch_timeout_seconds", 45))
    repositories = settings.get("tlmgr_repositories", [])
    auto_switch_repo = bool(settings.get("auto_switch_repository_on_tlpdb_error", True))

    latex_to_tlmgr = mappings.get("latex_to_tlmgr", {})
    requested_aliases = mappings.get("requested_aliases", {})

    project_dir = config_path.parent
    tex_files = resolve_tex_files(project_dir, tex_globs, tex_root)

    if not tex_files:
        raise typer.BadParameter(
            "No TeX files found from tex_globs. Check settings.tex_globs and --tex-root."
        )

    console.print(f"[bold]Config:[/bold] {config_path}")
    console.print(f"[bold]TeX files:[/bold] {len(tex_files)}")
    for tex_file in tex_files:
        console.print(f"  - {tex_file}")

    latex_packages = extract_latex_packages(tex_files)
    console.print(f"\n[bold]Extracted LaTeX packages:[/bold] {len(latex_packages)}")

    resolved: set[str] = set()
    unresolved: list[str] = []

    for name in latex_packages:
        mapped = latex_to_tlmgr.get(name, name)
        if mapped:
            resolved.add(mapped)
        else:
            unresolved.append(name)

    for name in extras.get("inferred", []):
        resolved.add(name)

    for name in extras.get("requested", []):
        resolved.add(requested_aliases.get(name, name))

    ordered_packages = sorted(resolved)

    table = Table(title="Resolved tlmgr package list")
    table.add_column("#", justify="right")
    table.add_column("Package")
    for idx, pkg in enumerate(ordered_packages, start=1):
        table.add_row(str(idx), pkg)
    console.print(table)

    if unresolved:
        console.print("\n[yellow]Unresolved LaTeX package names:[/yellow]")
        for name in unresolved:
            console.print(f"  - {name}")

    if dry_run:
        console.print("\n[green]Dry run complete.[/green]")
        return

    if verify_only:
        console.print("\n[bold]Verifying installed state only...[/bold]")
        missing: list[str] = []
        for idx, pkg in enumerate(ordered_packages, start=1):
            console.print(f"[cyan][verify {idx}/{len(ordered_packages)}][/cyan] {pkg}")
            installed, detail = is_tlmgr_package_installed(tlmgr_cmd, pkg, installed_check_timeout)
            if installed:
                console.print(f"  [green]OK[/green] {pkg}")
            else:
                missing.append(pkg)
                console.print(f"  [red]MISSING[/red] {pkg}: {detail}")
        if missing:
            console.print("\n[bold red]Verification failed.[/bold red]")
            console.print("[red]Missing packages:[/red]")
            for pkg in missing:
                console.print(f"  - {pkg}")
            raise typer.Exit(code=1)
        console.print("\n[bold green]Verification successful: all packages are installed.[/bold green]")
        return

    console.print(
        f"\n[bold]Installing with:[/bold] {shlex.join([tlmgr_cmd, 'install', '<pkg>'])} (timeout {install_timeout}s/package)"
    )

    if repositories:
        primary_repo = str(repositories[0])
        console.print(f"[bold]Repository:[/bold] attempting primary mirror: {primary_repo}")
        ok, msg = run_tlmgr_option_repository(tlmgr_cmd, primary_repo, repo_switch_timeout)
        if ok:
            console.print(f"  [green]OK[/green] repository set to {primary_repo}")
        else:
            console.print(f"  [yellow]WARN[/yellow] could not set primary repository: {msg}")

    failures: list[InstallResult] = []
    timeouts: list[InstallResult] = []
    skipped: list[InstallResult] = []
    current_repo_index = 0

    total = len(ordered_packages)
    for idx, pkg in enumerate(ordered_packages, start=1):
        console.print(f"[cyan][install {idx}/{total}][/cyan] {pkg}")
        is_installed, installed_detail = is_tlmgr_package_installed(
            tlmgr_cmd, pkg, installed_check_timeout
        )
        if is_installed:
            skipped.append(InstallResult(package=pkg, status="skipped", detail=installed_detail))
            console.print(f"  [blue]SKIP[/blue] {pkg}: already installed")
            continue

        result = run_tlmgr_install(tlmgr_cmd, pkg, install_timeout)

        if (
            result.status == "failed"
            and auto_switch_repo
            and repositories
            and is_tlpdb_error(result.detail)
            and current_repo_index + 1 < len(repositories)
        ):
            switched = False
            while current_repo_index + 1 < len(repositories):
                current_repo_index += 1
                next_repo = str(repositories[current_repo_index])
                console.print(
                    f"  [yellow]Repository error detected[/yellow]; switching mirror to {next_repo} and retrying {pkg}"
                )
                ok, msg = run_tlmgr_option_repository(tlmgr_cmd, next_repo, repo_switch_timeout)
                if not ok:
                    console.print(f"  [yellow]WARN[/yellow] could not set repository {next_repo}: {msg}")
                    continue
                switched = True
                console.print(f"  [green]OK[/green] repository set to {next_repo}")
                result = run_tlmgr_install(tlmgr_cmd, pkg, install_timeout)
                break

            if not switched:
                console.print("  [yellow]WARN[/yellow] no usable fallback repositories remained")

        if result.status == "ok":
            console.print(f"  [green]OK[/green] {pkg}")
        elif result.status == "timeout":
            is_installed_after, installed_after_detail = is_tlmgr_package_installed(
                tlmgr_cmd, pkg, installed_check_timeout
            )
            if is_installed_after:
                skipped.append(
                    InstallResult(
                        package=pkg,
                        status="skipped",
                        detail=f"install timed out, but package is installed ({installed_after_detail})",
                    )
                )
                console.print(
                    "  [yellow]TIMEOUT-BUT-INSTALLED[/yellow] "
                    f"{pkg}: install timed out, but package is now installed"
                )
            else:
                timeouts.append(result)
                console.print(f"  [red]TIMEOUT[/red] {pkg}: {result.detail}")
        else:
            failures.append(result)
            console.print(f"  [red]FAILED[/red] {pkg}: {result.detail}")

    if failures or timeouts:
        console.print("\n[bold red]Install completed with issues.[/bold red]")
        if failures:
            console.print("[red]Failures:[/red]")
            for item in failures:
                console.print(f"  - {item.package}: {item.detail}")
        if timeouts:
            console.print("[red]Timeouts:[/red]")
            for item in timeouts:
                console.print(f"  - {item.package}: {item.detail}")
        if skipped:
            console.print("[blue]Skipped/already installed:[/blue]")
            for item in skipped:
                console.print(f"  - {item.package}: {item.detail}")
        raise typer.Exit(code=1)

    console.print("\n[bold]Final verification...[/bold]")
    missing_after_install: list[str] = []
    for idx, pkg in enumerate(ordered_packages, start=1):
        installed, detail = is_tlmgr_package_installed(tlmgr_cmd, pkg, installed_check_timeout)
        if not installed:
            missing_after_install.append(pkg)
            console.print(f"[red][verify {idx}/{len(ordered_packages)}] MISSING[/red] {pkg}: {detail}")
        else:
            console.print(f"[green][verify {idx}/{len(ordered_packages)}] OK[/green] {pkg}")

    if missing_after_install:
        console.print("\n[bold red]Install finished but verification failed.[/bold red]")
        console.print("[red]Still missing:[/red]")
        for pkg in missing_after_install:
            console.print(f"  - {pkg}")
        raise typer.Exit(code=1)

    if skipped:
        console.print("\n[blue]Skipped/already installed:[/blue]")
        for item in skipped:
            console.print(f"  - {item.package}: {item.detail}")

    console.print("\n[bold green]Install completed successfully.[/bold green]")


if __name__ == "__main__":
    app()

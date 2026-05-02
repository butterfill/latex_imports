from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from preamble_installer import cli


runner = CliRunner()


def completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["tlmgr"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_installed_check_requires_named_package(monkeypatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: completed(0, stdout=""),
    )

    installed, detail = cli.is_tlmgr_package_installed("tlmgr", "amsmath", 25)

    assert installed is False
    assert detail == "exit code 0"


def test_installed_check_accepts_exact_info_name(monkeypatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: completed(0, stdout="package: amsmath\ninstalled: Yes\n"),
    )

    installed, detail = cli.is_tlmgr_package_installed("tlmgr", "amsmath", 25)

    assert installed is True
    assert detail == "already installed"


def test_installed_check_rejects_mismatched_info_name(monkeypatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: completed(0, stdout="name: tools\ninstalled: Yes\n"),
    )

    installed, detail = cli.is_tlmgr_package_installed("tlmgr", "amsmath", 25)

    assert installed is False
    assert "unexpected package 'tools'" in detail


def test_installed_check_prefers_stderr_on_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: completed(
            127,
            stdout="already installed",
            stderr="zsh: command not found: tlmgr",
        ),
    )

    installed, detail = cli.is_tlmgr_package_installed("tlmgr", "amsmath", 25)

    assert installed is False
    assert detail == "zsh: command not found: tlmgr"


def test_tlmgr_command_supports_wrappers() -> None:
    assert cli.tlmgr_command("sudo tlmgr", "install", "amsmath") == [
        "sudo",
        "tlmgr",
        "install",
        "amsmath",
    ]


def test_strip_comments_preserves_escaped_percent() -> None:
    line = r"\usepackage{foo\%bar}\usepackage{baz} % real comment \usepackage{ignored}"

    assert cli.strip_comments(line) == r"\usepackage{foo\%bar}\usepackage{baz} "


def test_extract_latex_packages_after_escaped_percent(tmp_path: Path) -> None:
    tex_file = tmp_path / "doc.tex"
    tex_file.write_text(
        "\\usepackage{first}\n"
        r"\newcommand{\pct}{\%}\usepackage{second}" "\n"
        "% \\usepackage{ignored}\n",
        encoding="utf-8",
    )

    assert cli.extract_latex_packages([tex_file]) == ["first", "second"]


def test_repository_fallback_retries_each_tlpdb_failure(tmp_path: Path, monkeypatch) -> None:
    tex_file = tmp_path / "doc.tex"
    tex_file.write_text(r"\usepackage{foo}", encoding="utf-8")
    config_file = tmp_path / "packages.yaml"
    config_file.write_text(
        """
version: 1
settings:
  tex_globs:
    - "doc.tex"
  tlmgr_command: "tlmgr"
  install_timeout_seconds: 1
  installed_check_timeout_seconds: 1
  repository_switch_timeout_seconds: 1
  auto_switch_repository_on_tlpdb_error: true
  tlmgr_repositories:
    - "repo-a"
    - "repo-b"
    - "repo-c"
mappings:
  latex_to_tlmgr: {}
  requested_aliases: {}
extras:
  inferred: []
  requested: []
""".lstrip(),
        encoding="utf-8",
    )

    installs = 0
    repos: list[str] = []

    def fake_is_installed(tlmgr_cmd: str, package: str, timeout_seconds: int) -> tuple[bool, str]:
        return installs >= 3, "already installed" if installs >= 3 else "not installed"

    def fake_install(tlmgr_cmd: str, package: str, timeout_seconds: int) -> cli.InstallResult:
        nonlocal installs
        installs += 1
        if installs < 3:
            return cli.InstallResult(package, "failed", "could not get texlive.tlpdb")
        return cli.InstallResult(package, "ok", "installed")

    def fake_set_repo(tlmgr_cmd: str, repository: str, timeout_seconds: int) -> tuple[bool, str]:
        repos.append(repository)
        return True, "repository updated"

    monkeypatch.setattr(cli, "is_tlmgr_package_installed", fake_is_installed)
    monkeypatch.setattr(cli, "run_tlmgr_install", fake_install)
    monkeypatch.setattr(cli, "run_tlmgr_option_repository", fake_set_repo)

    result = runner.invoke(cli.app, ["--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert installs == 3
    assert repos == ["repo-a", "repo-b", "repo-c"]


def test_repository_fallback_retries_generic_install_failures(tmp_path: Path, monkeypatch) -> None:
    tex_file = tmp_path / "doc.tex"
    tex_file.write_text(r"\usepackage{foo}", encoding="utf-8")
    config_file = tmp_path / "packages.yaml"
    config_file.write_text(
        """
version: 1
settings:
  tex_globs:
    - "doc.tex"
  tlmgr_command: "tlmgr"
  install_timeout_seconds: 1
  installed_check_timeout_seconds: 1
  repository_switch_timeout_seconds: 1
  auto_switch_repository_on_tlpdb_error: true
  tlmgr_repositories:
    - "repo-a"
    - "repo-b"
mappings:
  latex_to_tlmgr: {}
  requested_aliases: {}
extras:
  inferred: []
  requested: []
""".lstrip(),
        encoding="utf-8",
    )

    installs = 0
    repos: list[str] = []

    def fake_is_installed(tlmgr_cmd: str, package: str, timeout_seconds: int) -> tuple[bool, str]:
        return installs >= 2, "already installed" if installs >= 2 else "not installed"

    def fake_install(tlmgr_cmd: str, package: str, timeout_seconds: int) -> cli.InstallResult:
        nonlocal installs
        installs += 1
        if installs == 1:
            return cli.InstallResult(package, "failed", "network read failed")
        return cli.InstallResult(package, "ok", "installed")

    def fake_set_repo(tlmgr_cmd: str, repository: str, timeout_seconds: int) -> tuple[bool, str]:
        repos.append(repository)
        return True, "repository updated"

    monkeypatch.setattr(cli, "is_tlmgr_package_installed", fake_is_installed)
    monkeypatch.setattr(cli, "run_tlmgr_install", fake_install)
    monkeypatch.setattr(cli, "run_tlmgr_option_repository", fake_set_repo)

    result = runner.invoke(cli.app, ["--config", str(config_file)])

    assert result.exit_code == 0, result.output
    assert installs == 2
    assert repos == ["repo-a", "repo-b"]

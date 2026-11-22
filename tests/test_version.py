import tomllib
from pathlib import Path

from fw_qna import __version__, cli


def test_the_package_and_pyproject_have_the_same_version():
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    assert __version__ == pyproject["project"]["version"]


def test_the_version_is_one_point_zero():
    assert __version__ == "1.0.0"


def test_the_command_line_reports_it(capsys):
    try:
        cli.main(["--version"])
    except SystemExit as done:
        assert done.code == 0
    assert capsys.readouterr().out.strip() == f"fw-qna {__version__}"

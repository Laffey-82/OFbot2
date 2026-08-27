from __future__ import annotations

import re
import tomllib
from pathlib import Path

import app

ROOT = Path(__file__).resolve().parents[1]


def test_version_single_source_consistent() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)
    assert pyproject["project"]["version"] == app.__version__ == "1.0.0"


def test_version_format() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", app.__version__)


def test_pypi_metadata_present() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)
    project = pyproject["project"]
    assert project.get("readme")
    assert "license" in project
    assert project.get("authors")
    assert project.get("classifiers")
    assert "build-system" in pyproject

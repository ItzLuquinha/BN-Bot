from pathlib import Path

ROOT = Path(__file__).parents[1]
CODE_SUFFIXES = {".py", ".html", ".css", ".js", ".ts", ".sql", ".toml", ".yml", ".yaml"}


def test_project_has_no_em_dash() -> None:
    offenders = []
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in CODE_SUFFIXES:
            if chr(0x2014) in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_project_has_no_css_gradients() -> None:
    offenders = []
    for path in ROOT.rglob("*.css"):
        text = path.read_text(encoding="utf-8").lower()
        if "gradient(" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_source_has_no_comments() -> None:
    offenders = []
    for path in ROOT.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []


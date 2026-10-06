from pathlib import Path
import ast

ROOT = Path(__file__).parents[1]


def python_audit() -> list[str]:
    errors = []
    for path in ROOT.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"SyntaxError {path.relative_to(ROOT)}:{exc.lineno}")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                errors.append(f"comment {path.relative_to(ROOT)}:{number}")
    return errors


def style_audit() -> list[str]:
    errors = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if chr(0x2014) in text:
            errors.append(f"em-dash {path.relative_to(ROOT)}")
        if path.suffix == ".css" and "gradient(" in text.lower():
            errors.append(f"gradient {path.relative_to(ROOT)}")
    return errors


def main() -> None:
    errors = python_audit() + style_audit()
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print("BN Bot audit passed")

if __name__ == "__main__":
    main()

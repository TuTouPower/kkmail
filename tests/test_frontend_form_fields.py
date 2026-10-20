"""Static checks for React form fields (Chrome DevTools "Issues" hygiene)."""

from pathlib import Path
import re

COMPONENTS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components"


def _jsx_tags(source: str, names: tuple[str, ...]):
    """Yield (line, full opening tag) for each JSX element, skipping '>' inside {...}."""
    for match in re.finditer(r"<(%s)\b" % "|".join(names), source):
        depth, i = 0, match.end()
        while i < len(source):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            i += 1
        yield source.count("\n", 0, match.start()) + 1, source[match.start(): i + 1]


def _top_level_attrs(tag: str) -> str:
    """Drop {...} expressions so attribute names inside callbacks are ignored."""
    out, depth = [], 0
    for ch in tag:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def test_every_form_field_has_id_or_name():
    missing = []
    for path in sorted(COMPONENTS.glob("*.tsx")):
        for line, tag in _jsx_tags(path.read_text(encoding="utf-8"), ("input", "select", "textarea")):
            if not re.search(r"\s(id|name)=", _top_level_attrs(tag)):
                missing.append(f"{path.name}:{line}")
    assert not missing, f"form fields without id/name: {missing}"


def test_password_fields_have_autocomplete():
    missing = []
    for path in sorted(COMPONENTS.glob("*.tsx")):
        for line, tag in _jsx_tags(path.read_text(encoding="utf-8"), ("input",)):
            attrs = _top_level_attrs(tag)
            if 'type="password"' in attrs and "autoComplete=" not in attrs:
                missing.append(f"{path.name}:{line}")
    assert not missing, f"password inputs without autoComplete: {missing}"

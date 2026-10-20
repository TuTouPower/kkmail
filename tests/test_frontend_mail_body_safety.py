"""Static guard: the React reader must never inject raw mail HTML into the app origin."""
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"


def test_reader_uses_sanitized_sandboxed_iframe():
    reader = (FRONTEND / "components" / "MessageReader.tsx").read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in reader
    assert "srcDoc={buildMailSrcdoc(" in reader
    assert "sandbox={MAIL_IFRAME_SANDBOX}" in reader
    assert "startsWith('<')" not in reader


def test_no_component_uses_dangerously_set_inner_html():
    offenders = [
        str(p.relative_to(FRONTEND))
        for p in FRONTEND.rglob("*.tsx")
        if "dangerouslySetInnerHTML" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_mail_iframe_sandbox_has_no_scripts():
    lib = (FRONTEND / "lib" / "mailBody.ts").read_text(encoding="utf-8")
    line = next(l for l in lib.splitlines() if l.startswith("export const MAIL_IFRAME_SANDBOX"))
    assert "allow-scripts" not in line
    assert "allow-same-origin" not in line
    assert "DOMPurify.sanitize" in lib

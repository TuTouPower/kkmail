"""R4 adoption P51 (deploy script + compose): A266/A13/A161/A72/A98/A154.

Each test targets one adoption item in
``docs/reviews/review_20261027_021416/adoption_decision.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy_mail_core.sh"
COMPOSE = ROOT / "docker-compose.mail-core.yml"


def _deploy_text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


# --- A266: OrbStack context must be env-overridable; push must be explicit ---


def test_a266_context_is_env_overridable_with_documented_default():
    text = _deploy_text()
    assert "EXPECTED_DOCKER_CONTEXT" in text
    assert "orbstack" in text
    # The expected context must come from the environment, not a bare literal
    # comparison against a hard-coded string.
    assert re.search(
        r'\$\{EXPECTED_DOCKER_CONTEXT:-orbstack\}', text
    ), "context expectation must default via EXPECTED_DOCKER_CONTEXT env var"
    assert '[[ "$(docker context show)" == "orbstack" ]]' not in text


def test_a266_push_is_opt_out_and_announced():
    text = _deploy_text()
    assert "--no-push" in text, "deploy must support an explicit --no-push switch"
    # Push must be guarded by the switch and announced before it runs.
    assert re.search(r"no_push|NO_PUSH", text)
    push_idx = text.index("git push origin main")
    announce_idx = text.rindex("printf", 0, push_idx)
    announce_chunk = text[announce_idx:push_idx]
    assert "push" in announce_chunk.lower(), (
        "the git push step must print what it is about to do before running"
    )

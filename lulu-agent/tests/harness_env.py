"""Test bootstrap — import this before any app module that touches the DB or the LLM.

Importing pins DATABASE_URL to a throwaway sqlite under target/harness and forces
AI_PROVIDER=mock, so the suite never reaches data/lulu.db or the Ark API. Reuses the
engineering harness bootstrap so tests and `python -m app.harness.runner` stay aligned.
"""

from __future__ import annotations

from app.harness.runner import build_context, configure_environment

configure_environment()

CONTEXT = build_context()
SETTINGS = CONTEXT.settings


def session():
    """A SQLAlchemy session bound to the throwaway harness database."""
    return CONTEXT.session()

"""Wiki tab — renders WIKI.md as an in-app usage guide.

Reads the WIKI.md file at repo root (the same content available on GitHub)
and renders it as Streamlit markdown so the trader never has to leave the
dashboard to learn how to use it.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st


WIKI_PATH = Path(__file__).resolve().parent.parent / "WIKI.md"


def render() -> None:
    if not WIKI_PATH.exists():
        st.warning(
            "WIKI.md not found at repo root. The wiki is shipped as part of the "
            "repository — check `~/Desktop/energy-dashboard/WIKI.md`."
        )
        return

    text = WIKI_PATH.read_text(encoding="utf-8")
    # Drop the very first H1 (the WIKI title) since the tab itself already labels it.
    if text.lstrip().startswith("# "):
        text = text.split("\n", 1)[1] if "\n" in text else text
    st.markdown(text)

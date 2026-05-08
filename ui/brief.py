"""Sidebar morning-brief panel."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from analysis.signals import cross_market_tag, morning_brief
from config import METRICS_BY_KEY


def _latest_brief_paths() -> tuple[Path | None, Path | None, str]:
    """Find today's pre-generated desk-note PDF + Markdown if they exist.

    Looks under `output/<today>/` first, then walks back up to 7 days so the
    sidebar still offers a download even on a non-cron-day (weekend / outage).
    Returns (pdf_path | None, md_path | None, date_str_used).
    """
    repo_root = Path(__file__).resolve().parent.parent
    out_root = repo_root / "output"
    today = datetime.now(timezone.utc).date()
    for delta in range(0, 8):
        d = today - pd.Timedelta(days=delta)
        date_str = d.strftime("%Y-%m-%d")
        date_dir = out_root / date_str
        pdf = date_dir / f"desk_note_{date_str}.pdf"
        md = date_dir / f"desk_note_{date_str}.md"
        if pdf.exists() or md.exists():
            return (pdf if pdf.exists() else None,
                    md if md.exists() else None,
                    date_str)
    return None, None, ""


def _download_block() -> None:
    """Offer the latest pre-generated brief as a download (PDF + Markdown).

    The recruiter's asked-for artefact is the PDF. Markdown is offered too
    so the trader can paste it into chat / Slack without re-rendering.
    Print works via the browser's PDF viewer once the PDF is downloaded.
    """
    pdf_path, md_path, date_str = _latest_brief_paths()
    if not pdf_path and not md_path:
        st.caption(
            ":orange[No pre-generated brief on disk yet. Run "
            "`python scripts/generate_brief.py --pdf` to produce one.]"
        )
        return

    st.markdown(f"### Today's brief ({date_str})")
    st.caption(
        "Download the latest pre-generated desk note. The PDF mirrors the "
        "executive summary in the AI Desk Note pane below — same two-pass "
        "extract→narrate output, plus the full 6-section structure with charts. "
        "To print, open the PDF in your viewer (Preview / Adobe / browser) "
        "and use its Print command."
    )
    cols = st.columns(2)
    with cols[0]:
        if pdf_path is not None:
            with open(pdf_path, "rb") as fh:
                st.download_button(
                    label="Download PDF",
                    data=fh.read(),
                    file_name=pdf_path.name,
                    mime="application/pdf",
                    width="stretch",
                    key="dl_brief_pdf",
                )
        else:
            st.caption(":orange[PDF not on disk — install pandoc/xelatex.]")
    with cols[1]:
        if md_path is not None:
            with open(md_path, "rb") as fh:
                st.download_button(
                    label="Download Markdown",
                    data=fh.read(),
                    file_name=md_path.name,
                    mime="text/markdown",
                    width="stretch",
                    key="dl_brief_md",
                )


def render(data: dict[str, pd.DataFrame]) -> None:
    _download_block()
    st.markdown("---")

    st.markdown("### Morning brief")
    st.write(morning_brief(data))

    tag = cross_market_tag(data)
    if tag:
        st.info(tag)

    st.markdown("---")
    st.markdown("### Data freshness")
    # Only show registered primary metrics — auxiliary derived series
    # (switching_ttf, de_gb_spread, eurusd, etc.) are internal helpers.
    for key, df in data.items():
        if key not in METRICS_BY_KEY:
            continue
        meta = METRICS_BY_KEY[key]
        if df is None or df.empty:
            st.markdown(f"- **{meta.short_name}**: :red[no data]")
            continue
        latest = df.index.max()
        stale = df.attrs.get("is_stale", False)
        badge = ":orange[snapshot]" if stale else ":green[live]"
        st.markdown(f"- **{meta.short_name}**: {latest:%Y-%m-%d} · {badge}")

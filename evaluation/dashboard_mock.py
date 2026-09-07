"""
Public-demo entrypoint for the Jira Chatbot Evaluation dashboard.

This is the version to **deploy as a portfolio piece**. It renders the exact same
dashboard as `dashboard.py` (every section, chart and helper is imported from it —
nothing is duplicated), but:

  * it reads a **fully simulated** results set from ``evaluation/mock_results/``,
    never ``evaluation/results/`` — no real Jira ticket text is ever shipped;
  * it shows a disclosure in the hero saying the ticket data is simulated and
    stating the real historical result (6.1% across 33 real tickets).

The real, private dashboard is unchanged: ``streamlit run evaluation/dashboard.py``.

    streamlit run evaluation/dashboard_mock.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation import dashboard  # noqa: E402  (its main() is __main__-guarded)

# Point the read-only view at the simulated dataset. The loader functions and the
# sidebar read this module global at call time, so reassigning it is enough.
dashboard.RESULTS_DIR = Path(__file__).resolve().parent / "mock_results"

# Hero disclosure — dashboard.py renders each entry as a plain st.caption, so the
# layout matches the real dashboard (which leaves DEMO_NOTICE empty).
dashboard.DEMO_NOTICE = [
    "**Demo dashboard.** The ticket data below is **simulated** to protect confidential "
    "information — it demonstrates the evaluation system, not real tickets.",
    "**Real historical result:** replaying 33 real historical Jira tickets gave **6.1% "
    "potential ticket deflection** — a historical estimate, not observed production automation.",
]

dashboard.main()

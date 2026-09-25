"""
Settings the REST layer needs that `config.py` (the Streamlit app's config) does
not carry. Kept here so `api/` is self-contained and config.py stays untouched.
"""

from __future__ import annotations

import os

ENV = os.environ.get("ENV", "dev")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

# Requests per minute per client IP. 0 disables the limiter.
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))

# Comma-separated origins allowed to call this API from a browser. Empty means
# no cross-origin access — never "*". Set this to your React app's origin.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

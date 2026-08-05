"""WSGI entry point.

Development:  python app.py
Production:   gunicorn --config gunicorn.conf.py app:app
"""

from __future__ import annotations

import os

from backend import create_app
from backend.config import debug_enabled

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug_enabled())

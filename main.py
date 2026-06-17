"""
Application entry point.
Run with: uvicorn main:app --reload

Equivalent to running `uvicorn backend.api.routes:app --reload` directly —
this module exists purely as a conventional top-level entry point.
.env loading and all startup logic (DB init, scheduler) live in
backend/api/routes.py itself, since it's a real entry point in its own
right when run directly.
"""
from backend.api.routes import app

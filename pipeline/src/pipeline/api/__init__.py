"""FastAPI search + browse layer over the local SQLite DB.

Everything here reads from the single SQLite file produced by the
zero-cost pipeline. No external services, no auth. Run locally with:

    uvicorn pipeline.api.app:app --reload

or in a Cloud Run free-tier container in production.
"""

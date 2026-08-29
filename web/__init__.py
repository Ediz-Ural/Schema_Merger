"""Web layer for Schema Merger.

Everything here is presentation and orchestration only: the FastAPI backend
calls the very same ``core`` functions the CLI calls, so business logic is never
written twice (spec §8/§14).
"""

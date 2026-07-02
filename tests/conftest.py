"""
conftest.py — Pytest configuration.
Sets MEDEASY_DB=:memory: before any import so every test
runs against a fresh in-memory SQLite instance.
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

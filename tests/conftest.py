"""
conftest.py — Pytest configuration.
Sets MEDISCAN_DB=:memory: before any import so every test
runs against a fresh in-memory SQLite instance.
"""
import os
os.environ["MEDISCAN_DB"] = ":memory:"

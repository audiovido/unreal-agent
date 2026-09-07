"""Aivido V2 autonomous QA bot.

A black-box QA engineer that inspects the running Aivido product, executes
black-box checks, detects defects, classifies severity, collects evidence,
distinguishes real PASS from false PASS, retries only where safe, and
produces a durable release-readiness verdict.
"""
from qa import model, verifier  # noqa: F401

__version__ = "2.0.0"
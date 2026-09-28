"""Workflow definitions. They import temporalio, Strands and pure code; worker modules through the sandbox passthrough.

Activities are called by name, except the navigation tools: agents.py imports them through the passthrough and wraps
them by reference.
"""

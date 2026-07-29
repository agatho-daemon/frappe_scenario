# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Core scenario engine.

Nothing in this package imports a provider. Providers import the core; the core
discovers providers through hooks. That direction is what keeps third-party apps
first-class rather than special-cased.
"""

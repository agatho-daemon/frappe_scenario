# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Whitelisted HTTP surface.

Every endpoint is restricted to System Manager and delegates to
:mod:`frappe_scenario.core.engine`. Nothing here talks to a model provider; the
AI endpoints exchange structured data with an external agent and record where
that data came from.
"""

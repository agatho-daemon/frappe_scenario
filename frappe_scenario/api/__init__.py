# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Whitelisted HTTP surface.

Every endpoint is restricted to System Manager. Generation delegates to
:mod:`frappe_scenario.core.engine`; AI endpoints expose safe adapter metadata or
exchange structured data with an external agent. No endpoint currently performs
an outbound model call.
"""

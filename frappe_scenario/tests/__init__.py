# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Tests for frappe_scenario.

Three tiers, selected by marker:

``pure``
        No Frappe site and no database. Fast enough to run on every save.

``frappe_site``
        Needs a connected Frappe site, but no ERPNext.

``erpnext_site``
        Needs a connected site with ERPNext installed, and writes documents.
"""

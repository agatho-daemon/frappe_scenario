# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Cross-provider integrity validators.

Provider validators check the records that provider created. The validators in
this package check the dataset as a whole: that the ledger balances, that stock
never went negative, and that the commercial shape of the data matches what the
specification asked for.

Each validator is a callable taking a :class:`ScenarioContext` and returning a
:class:`ValidationResult`. They must be read-only.
"""

from __future__ import annotations

from collections.abc import Callable

from frappe_scenario.core.context import ScenarioContext
from frappe_scenario.core.validation import ValidationResult
from frappe_scenario.validators import documents, ledger, plausibility, stock

Validator = Callable[[ScenarioContext], ValidationResult]


def core_validators() -> list[Validator]:
	"""Every core validator, in the order results should be reported."""
	return [
		ledger.validate_vouchers_balanced,
		ledger.validate_trial_balance,
		ledger.validate_control_accounts_have_parties,
		ledger.validate_posting_window,
		ledger.validate_fiscal_year_coverage,
		stock.validate_non_negative_stock,
		stock.validate_stock_valuation,
		documents.validate_no_open_drafts,
		documents.validate_manifest_records_exist,
		plausibility.validate_gross_margin,
		plausibility.validate_activity_present,
	]

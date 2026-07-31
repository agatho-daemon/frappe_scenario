# Copyright (c) 2026, Agathodaemon and contributors
# For license information, please see license.txt
"""Plausibility review scope, approval, and cache tests."""

from __future__ import annotations

import json

import pytest


@pytest.mark.pure
def test_review_scope_excludes_deterministic_numeric_and_operational_fields():
	from frappe_scenario.ai.plausibility import review_scope

	preview = {
		"representative_samples": {
			"country": "Kuwait",
			"parties": [
				{
					"name": "Al Noor Trading W.L.L",
					"contact": "Amina Hassan",
					"email": "amina@alnoor.example",
					"phone": "+965 5555 5555",
					"address": {
						"address_line1": "12 Gulf Road",
						"city": "Kuwait City",
						"country": "Kuwait",
					},
				}
			],
			"products": [
				{
					"name": "Ducted Split Unit",
					"family": "Cooling",
					"description": "Commercial cooling system",
					"cost": 120,
					"selling_price": 175,
					"currency": "KWD",
				}
			],
			"transaction_stories": [
				{
					"customer": "Al Noor Trading W.L.L",
					"item": "Ducted Split Unit",
					"quantity": 4,
					"order_value": 700,
					"posting_date": "2026-07-01",
					"lifecycle": ["Sales Order", "Delivery Note", "Sales Invoice"],
				}
			],
		}
	}
	scope = review_scope(preview)
	serialized = json.dumps(scope)
	for forbidden in (
		"email",
		"phone",
		"cost",
		"selling_price",
		"currency",
		"quantity",
		"order_value",
		"posting_date",
	):
		assert f'"{forbidden}"' not in serialized
	assert scope["products"][0]["description"] == "Commercial cooling system"


@pytest.mark.frappe_site
def test_approved_plausibility_review_is_reused_without_model_call(frappe_site, rollback):
	import frappe

	from frappe_scenario.ai.executor import AIHTTPResult
	from frappe_scenario.ai.plausibility import (
		approve_review,
		approved_artifacts,
		review_onboarding_preview,
	)

	preview = {
		"representative_samples": {
			"country": "Kuwait",
			"parties": [
				{
					"name": "Gulf Cooling W.L.L",
					"contact": "Amina Hassan",
					"address": {
						"address_line1": "12 Gulf Road",
						"address_line2": "Shuwaikh",
						"city": "Kuwait City",
						"country": "Kuwait",
					},
				}
			],
			"products": [
				{
					"name": "Ducted Split Unit",
					"family": "Cooling",
					"description": "Commercial cooling system",
					"cost": 120,
					"selling_price": 175,
				}
			],
			"transaction_stories": [
				{
					"customer": "Gulf Cooling W.L.L",
					"item": "Ducted Split Unit",
					"quantity": 4,
					"order_value": 700,
					"lifecycle": ["Sales Order", "Delivery Note", "Sales Invoice", "Payment Entry"],
				}
			],
		}
	}
	frappe.db.set_single_value("Scenario Onboarding", "preview", json.dumps(preview))
	frappe.get_doc(
		{
			"doctype": "Scenario AI Provider",
			"provider": "openai",
			"enabled": 1,
			"credential": "review-test-secret",
		}
	).insert()
	model_output = {
		"summary": "Plausible overall; one product name can be more specific.",
		"findings": [
			{
				"category": "business_plausibility",
				"severity": "note",
				"subject": "product:0",
				"message": "Capacity would make the catalogue label clearer.",
				"proposed_replacement": "12 TR Ducted Split Unit",
			}
		],
	}
	calls = 0

	def transport(endpoint, body, headers, timeout):
		nonlocal calls
		calls += 1
		review_input = json.loads(body["input"][0]["content"][0]["text"])
		assert "cost" not in json.dumps(review_input)
		assert "selling_price" not in json.dumps(review_input)
		return AIHTTPResult(
			200,
			{
				"id": "resp_review_test",
				"output": [
					{
						"type": "message",
						"content": [{"type": "output_text", "text": json.dumps(model_output)}],
					}
				],
			},
		)

	result = review_onboarding_preview(transport=transport)
	assert result["status"] == "Pending Review"
	assert result["mutated_records"] is False
	with pytest.raises(frappe.ValidationError, match="until the review is approved"):
		approved_artifacts(result["review"])
	review_doc = frappe.get_doc("Scenario AI Review", result["review"])
	changed_preview = json.loads(json.dumps(preview))
	changed_preview["representative_samples"]["products"][0]["name"] = "Changed after review"
	frappe.db.set_single_value("Scenario Onboarding", "preview", json.dumps(changed_preview))
	review_doc.status = "Approved"
	with pytest.raises(frappe.ValidationError, match="preview changed"):
		review_doc.save()
	frappe.db.set_single_value("Scenario Onboarding", "preview", json.dumps(preview))
	review_doc.reload()

	approved = approve_review(result["review"])
	assert approved["status"] == "Approved"
	artifacts = approved_artifacts(result["review"])
	assert artifacts["artifacts"][0]["replacement"] == "12 TR Ducted Split Unit"

	def must_not_run(endpoint, body, headers, timeout):
		raise AssertionError("Approved review should be served from cache")

	reused = review_onboarding_preview(transport=must_not_run)
	assert reused["review"] == result["review"]
	assert reused["reused"] is True
	assert calls == 1

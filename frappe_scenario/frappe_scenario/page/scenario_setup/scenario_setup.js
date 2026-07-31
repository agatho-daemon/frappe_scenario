frappe.pages["scenario-setup"].on_page_load = (wrapper) => {
	new ScenarioSetupWizard(wrapper);
};

class ScenarioSetupWizard {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Frappe Scenario Setup"),
			single_column: true,
		});
		this.body = $('<div class="scenario-setup-wizard">').appendTo(this.page.main);
		this.page.set_primary_action(__("Save and Preview"), () => this.save_and_preview());
		this.page.add_inner_button(__("Refresh"), () => this.load());
		this.page.add_inner_button(__("New sample variation"), () => this.save_and_preview(true));
		this.load();
	}

	async load() {
		const response = await frappe.call({
			method: "frappe_scenario.api.onboarding.get_wizard",
			freeze: true,
			freeze_message: __("Inspecting ERPNext readiness…"),
		});
		this.model = response.message;
		this.render();
	}

	render() {
		this.body.empty();
		this.controls = {};
		const onboarding = this.model.onboarding;
		$(`
			<div class="scenario-setup-intro">
				<h3>${__("Build a safe, realistic ERPNext scenario")}</h3>
				<p>${__(
					"Your choices are saved as a resumable plan. ERPNext initialization runs only after explicit confirmation and never generates scenario business data."
				)}</p>
				<span class="indicator-pill blue">${frappe.utils.escape_html(onboarding.status)}</span>
				<details class="mt-3">
					<summary>${__("What do these company strategies mean?")}</summary>
					<ul class="mt-2">
						${Object.entries(this.model.catalog.guidance)
							.map(
								([key, value]) =>
									`<li><strong>${frappe.utils.escape_html(
										key
									)}</strong>: ${frappe.utils.escape_html(value)}</li>`
							)
							.join("")}
					</ul>
				</details>
			</div>
		`).appendTo(this.body);

		this.render_section(__("Purpose and business"), [
			this.select("intent", __("Purpose"), this.model.catalog.intents),
			this.select(
				"archetype",
				__("Business archetype"),
				this.model.catalog.archetypes.map((entry) => entry.id)
			),
			this.select("depth", __("Operational depth"), this.model.catalog.depths),
			this.select(
				"company_strategy",
				__("Company strategy"),
				this.model.catalog.company_strategies,
				__("Initialize only what is missing; reuse requires stronger review.")
			),
		]);
		this.render_section(__("Locale and company"), [
			this.data("country", __("Country")),
			this.data("language", __("Language")),
			this.data("timezone", __("Timezone")),
			this.data("currency", __("Currency")),
			this.data("company_name", __("Company name")),
			this.data("company_abbr", __("Company abbreviation")),
		]);
		this.render_section(__("Accounting and stock"), [
			this.data("chart_template", __("Chart of Accounts template")),
			this.select(
				"account_numbering",
				__("Account numbering"),
				this.model.catalog.account_numbering
			),
			this.data("fiscal_year_start", __("Fiscal year start"), null, "Date"),
			this.check("perpetual_inventory", __("Enable perpetual inventory")),
			this.select(
				"valuation_method",
				__("Stock valuation"),
				this.model.catalog.valuation_methods
			),
			this.data("warehouse_name", __("Default warehouse")),
			this.data("cost_center_name", __("Default cost center")),
		]);
		this.render_section(__("Dataset"), [
			this.select("scale", __("Scale"), ["smoke", "small", "medium", "large", "custom"]),
			this.data("history_months", __("History in months"), null, "Int"),
		]);
		this.render_proposal(this.model.proposal);
	}

	render_section(title, definitions) {
		const section = $(`<section><h4>${title}</h4><div class="row"></div></section>`).appendTo(
			this.body
		);
		const row = section.find(".row");
		definitions.forEach((definition) => {
			const parent = $('<div class="col-sm-6 scenario-control">').appendTo(row);
			const control = frappe.ui.form.make_control({
				parent,
				df: definition,
				render_input: true,
			});
			control.set_value(this.model.choices[definition.fieldname]);
			this.controls[definition.fieldname] = control;
		});
	}

	render_proposal(proposal) {
		const estimate = proposal.record_estimate;
		const section = $(`
			<section class="scenario-preview">
				<h4>${__("Preview")}</h4>
				<p>${__("Approximately {0} records ({1}–{2}) across {3} months.", [
					estimate.approximate,
					estimate.minimum,
					estimate.maximum,
					estimate.history_months,
				])}</p>
				<div class="scenario-mutations"></div>
				<div class="scenario-warnings"></div>
			</section>
		`).appendTo(this.body);
		const mutations = section.find(".scenario-mutations");
		const samples = proposal.representative_samples;
		$(`
			<div class="scenario-samples mb-4">
				<h5>${__("Representative data")}</h5>
				<p><strong>${__("Parties")}:</strong> ${samples.parties
			.map((party) => frappe.utils.escape_html(party.name))
			.join(", ")}</p>
				<p><strong>${__("Products")}:</strong> ${samples.products
			.map(
				(product) =>
					`${frappe.utils.escape_html(product.name)} (${format_currency(
						product.selling_price,
						product.currency
					)})`
			)
			.join(", ")}</p>
				<p><strong>${__("Sample contact")}:</strong> ${frappe.utils.escape_html(
			`${samples.parties[0].contact}, ${samples.parties[0].email}, ${samples.parties[0].phone}`
		)}</p>
				<p><strong>${__("Sample address")}:</strong> ${frappe.utils.escape_html(
			[
				samples.parties[0].address.address_line1,
				samples.parties[0].address.address_line2,
				samples.parties[0].address.city,
				samples.parties[0].address.country,
			]
				.filter(Boolean)
				.join(", ")
		)}</p>
				<p><strong>${__("Transaction story")}:</strong> ${frappe.utils.escape_html(
			`${samples.transaction_stories[0].customer} — ${
				samples.transaction_stories[0].quantity
			} × ${samples.transaction_stories[0].item} — ${format_currency(
				samples.transaction_stories[0].order_value,
				samples.transaction_stories[0].currency
			)}`
		)}</p>
				<p class="text-muted">${__("Preview variation {0}; deterministic quality: {1}", [
					samples.variation,
					samples.quality.passed ? __("passed") : __("needs review"),
				])}</p>
				<div class="scenario-quality-scores">
					<h5>${__("Quality gates")} — ${samples.quality.overall_score}%</h5>
					<p>${Object.entries(samples.quality.scores)
						.map(
							([dimension, score]) =>
								`${frappe.utils.escape_html(
									dimension.replaceAll("_", " ")
								)}: <strong>${score}%</strong>`
						)
						.join(" · ")}</p>
				</div>
			</div>
		`).appendTo(section);
		samples.quality.findings.forEach((finding) => {
			$(
				`<div class="alert ${
					finding.severity === "error" ? "alert-danger" : "alert-warning"
				}">`
			)
				.text(`${finding.category}: ${finding.message}`)
				.appendTo(section);
		});
		if (!proposal.mutations.length) {
			mutations.append(
				`<p class="text-muted">${__("No ERPNext setup changes proposed.")}</p>`
			);
		}
		proposal.mutations.forEach((item) => {
			$("<div class='scenario-mutation'>")
				.text(
					`${item.action}: ${item.target}.${item.field} — ${JSON.stringify(
						item.current
					)} → ${JSON.stringify(item.proposed)}`
				)
				.appendTo(mutations);
		});
		[...proposal.warnings, ...proposal.blockers.map((item) => item.message)].forEach(
			(message) => {
				$("<div class='alert alert-warning'>")
					.text(message)
					.appendTo(section.find(".scenario-warnings"));
			}
		);

		if (
			proposal.approvable &&
			this.model.preview_is_saved &&
			!this.model.onboarding.setup_approved
		) {
			$("<button class='btn btn-primary btn-sm'>")
				.text(__("Approve setup plan"))
				.on("click", () => this.approve())
				.appendTo(section);
		} else if (
			this.model.onboarding.setup_approved &&
			!this.model.onboarding.bootstrap_completed
		) {
			$("<button class='btn btn-primary btn-sm'>")
				.text(__("Initialize ERPNext foundations"))
				.on("click", () => this.initialize())
				.appendTo(section);
		} else if (this.model.onboarding.bootstrap_completed) {
			$("<div class='alert alert-success'>")
				.text(
					this.model.onboarding.scenario_run
						? __("Quick Demo is ready.")
						: __(
								"ERPNext foundations are ready. No scenario business data has run yet."
						  )
				)
				.appendTo(section);
			if (
				this.model.choices.intent === "Quick Demo" &&
				!this.model.onboarding.scenario_run
			) {
				$("<button class='btn btn-primary btn-sm'>")
					.text(__("Generate Quick Demo"))
					.on("click", () => this.generate_quick_demo())
					.appendTo(section);
			}
			if (this.model.onboarding.scenario_run) {
				$("<a class='btn btn-default btn-sm ml-2'>")
					.attr(
						"href",
						`/app/scenario-run/${encodeURIComponent(
							this.model.onboarding.scenario_run
						)}`
					)
					.text(__("Open scenario run"))
					.appendTo(section);
			}
		} else if (!this.model.preview_is_saved) {
			$("<div class='alert alert-info'>")
				.text(__("Save and preview these choices before approval."))
				.appendTo(section);
		}
	}

	async save_and_preview(new_variation = false) {
		const choices = { ...this.model.choices };
		for (const [fieldname, control] of Object.entries(this.controls)) {
			choices[fieldname] = control.get_value();
		}
		if (new_variation) {
			choices.preview_variation = Number(choices.preview_variation || 0) + 1;
		}
		const response = await frappe.call({
			method: "frappe_scenario.api.onboarding.save_wizard_choices",
			type: "POST",
			args: {
				choices,
				expected_version: this.model.onboarding.state_version,
			},
			freeze: true,
			freeze_message: __("Validating choices and preparing preview…"),
		});
		this.model.onboarding = response.message.onboarding;
		this.model.choices = response.message.choices;
		this.model.proposal = response.message.proposal;
		this.model.preview_is_saved = true;
		frappe.show_alert({ message: __("Choices and preview saved"), indicator: "green" });
		this.render();
	}

	approve() {
		frappe.confirm(
			__(
				"Approve the displayed ERPNext setup changes? You can review once more before initialization."
			),
			async () => {
				const response = await frappe.call({
					method: "frappe_scenario.api.onboarding.approve_setup_plan",
					type: "POST",
					args: { expected_version: this.model.onboarding.state_version },
					freeze: true,
				});
				this.model.onboarding = response.message.onboarding;
				this.render();
				this.initialize();
			}
		);
	}

	initialize() {
		frappe.confirm(
			__(
				"Initialize the approved ERPNext foundations now? Only the displayed missing settings and records will be changed; scenario business data will not be generated."
			),
			async () => {
				const response = await frappe.call({
					method: "frappe_scenario.api.onboarding.initialize_erpnext",
					type: "POST",
					args: { expected_version: this.model.onboarding.state_version },
					freeze: true,
					freeze_message: __("Initializing ERPNext foundations…"),
				});
				this.model.onboarding = response.message.onboarding;
				this.model.preflight = response.message.onboarding.last_preflight;
				frappe.show_alert({
					message: __("ERPNext foundations initialized"),
					indicator: "green",
				});
				this.render();
			}
		);
	}

	generate_quick_demo() {
		const non_disposable = !this.model.preflight.safety.disposable;
		const prompt = non_disposable
			? __(
					"This site is not marked disposable. Generate the linked Quick Demo on this default site anyway? Only manifest-owned records can be cleaned up automatically."
			  )
			: __(
					"Generate the linked Quick Demo now? This creates normal ERPNext business records owned by one cleanup manifest."
			  );
		frappe.confirm(prompt, async () => {
			const response = await frappe.call({
				method: "frappe_scenario.api.onboarding.generate_quick_demo_run",
				type: "POST",
				args: {
					expected_version: this.model.onboarding.state_version,
					allow_non_disposable: non_disposable ? 1 : 0,
					accept_quality_warnings: 1,
				},
				freeze: true,
				freeze_message: __("Generating linked ERPNext activity…"),
			});
			this.model.onboarding = response.message.onboarding;
			frappe.show_alert({
				message: __("Quick Demo generated"),
				indicator: "green",
			});
			this.render();
		});
	}

	select(fieldname, label, options, description = null) {
		return {
			fieldname,
			label,
			fieldtype: "Select",
			options: options.join("\n"),
			description,
			reqd: 1,
		};
	}

	data(fieldname, label, description = null, fieldtype = "Data") {
		return { fieldname, label, fieldtype, description, reqd: 1 };
	}

	check(fieldname, label) {
		return { fieldname, label, fieldtype: "Check" };
	}
}

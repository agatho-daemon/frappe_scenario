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
					"Your choices are saved as a resumable plan. Previewing and approving this page does not initialize ERPNext or generate business data."
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
			this.select("complexity", __("Complexity"), this.model.catalog.depths),
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
		} else if (this.model.onboarding.setup_approved) {
			$("<div class='alert alert-success'>")
				.text(__("Setup plan approved. No setup or data generation has run yet."))
				.appendTo(section);
		} else if (!this.model.preview_is_saved) {
			$("<div class='alert alert-info'>")
				.text(__("Save and preview these choices before approval."))
				.appendTo(section);
		}
	}

	async save_and_preview() {
		const choices = {};
		for (const [fieldname, control] of Object.entries(this.controls)) {
			choices[fieldname] = control.get_value();
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
				"Approve the displayed ERPNext setup changes? Approval is recorded now; no settings or business records are changed in this batch."
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
			}
		);
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

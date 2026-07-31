frappe.pages["scenario-troubleshooting"].on_page_load = (wrapper) => {
	new ScenarioTroubleshooting(wrapper);
};

class ScenarioTroubleshooting {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Troubleshooting Lab"),
			single_column: true,
		});
		this.body = $('<div class="scenario-troubleshooting">').appendTo(this.page.main);
		this.run_name = frappe.utils.get_url_arg("run");
		this.load();
	}

	async load() {
		if (!this.run_name) {
			this.body.html(`<div class="alert alert-warning">${__("Open the lab from a completed Scenario Run.")}</div>`);
			return;
		}
		const response = await frappe.call({
			method: "frappe_scenario.api.troubleshooting.get_lab",
			args: { run_name: this.run_name },
			freeze: true,
		});
		this.model = response.message;
		this.render();
	}

	render() {
		this.page.set_title(__("Troubleshooting: {0}", [this.model.run.company]));
		this.body.empty();
		$(`<div class="mb-4"><h3>${frappe.utils.escape_html(this.model.run.company)}</h3>
			<p class="text-muted">${__("Diagnose one controlled ERPNext problem at a time. The lab never corrects the problem silently.")}</p></div>`).appendTo(this.body);
		if (this.model.active_case) {
			this.render_active(this.model.active_case);
			return;
		}
		this.model.problems.forEach((problem) => this.render_problem(problem));
	}

	render_problem(problem) {
		const unavailable = !problem.availability.available;
		const card = $(`<section class="card mb-3"><div class="card-body">
			<div class="text-muted small">${frappe.utils.escape_html(problem.module)} · ${frappe.utils.escape_html(problem.difficulty)}</div>
			<h4>${frappe.utils.escape_html(problem.title)}</h4>
			<p>${frappe.utils.escape_html(problem.objective)}</p>
			${unavailable ? `<div class="alert alert-warning">${frappe.utils.escape_html(problem.availability.message)}</div>` : ""}
			<button class="btn btn-primary start-case" ${unavailable ? "disabled" : ""}>${__("Start case")}</button>
		</div></section>`).appendTo(this.body);
		card.find(".start-case").on("click", () => this.start(problem));
	}

	async start(problem) {
		frappe.confirm(__("Create a reversible training problem for {0}?", [problem.title]), async () => {
			await frappe.call({
				method: "frappe_scenario.api.troubleshooting.start_case",
				type: "POST",
				args: { run_name: this.run_name, problem_key: problem.key },
				freeze: true,
				freeze_message: __("Preparing the lab case…"),
			});
			await this.load();
		});
	}

	render_active(active) {
		const choices = active.choices.map((choice) => `<option value="${frappe.utils.escape_html(choice.key)}">${frappe.utils.escape_html(choice.label)}</option>`).join("");
		const hints = active.hints.length
			? `<div class="alert alert-info mt-3">${active.hints.map((hint) => frappe.utils.escape_html(hint)).join("<br>")}</div>`
			: "";
		const card = $(`<section class="card"><div class="card-body">
			<span class="indicator-pill ${active.status === "Diagnosed" ? "green" : "orange"}">${frappe.utils.escape_html(active.status)}</span>
			<h3 class="mt-3">${frappe.utils.escape_html(active.title)}</h3>
			<p>${frappe.utils.escape_html(active.objective)}</p>
			<a class="btn btn-default mb-3" href="${encodeURI(active.target.route)}">${__("Open ERPNext evidence")}</a>
			<div class="form-group"><label>${__("Your diagnosis")}</label><select class="form-control diagnosis"><option value="">${__("Select…")}</option>${choices}</select></div>
			<button class="btn btn-primary check-diagnosis">${__("Check diagnosis")}</button>
			<button class="btn btn-default restore-case ml-2">${__("Restore baseline")}</button>
			<div class="diagnosis-result mt-3"></div>${hints}
		</div></section>`).appendTo(this.body);
		card.find(".check-diagnosis").on("click", () => this.diagnose(active, card));
		card.find(".restore-case").on("click", () => this.restore(active));
	}

	async diagnose(active, card) {
		const diagnosis_key = card.find(".diagnosis").val();
		if (!diagnosis_key) {
			frappe.show_alert({ message: __("Choose a diagnosis first"), indicator: "orange" });
			return;
		}
		const response = await frappe.call({
			method: "frappe_scenario.api.troubleshooting.diagnose",
			type: "POST",
			args: { case_name: active.name, diagnosis_key },
		});
		frappe.show_alert({ message: response.message.message, indicator: response.message.passed ? "green" : "orange" });
		await this.load();
	}

	restore(active) {
		frappe.confirm(__("Remove the training problem and restore the pre-lab checkpoint?"), async () => {
			const response = await frappe.call({
				method: "frappe_scenario.api.troubleshooting.restore",
				type: "POST",
				args: { case_name: active.name },
				freeze: true,
			});
			if (response.message.blockers.length) {
				frappe.msgprint({ title: __("Restore blocked"), indicator: "orange", message: response.message.blockers.map((item) => `<p>${frappe.utils.escape_html(item.reference)}: ${frappe.utils.escape_html(item.message)}</p>`).join("") });
			} else {
				frappe.show_alert({ message: __("Lab baseline restored"), indicator: "green" });
			}
			await this.load();
		});
	}
}

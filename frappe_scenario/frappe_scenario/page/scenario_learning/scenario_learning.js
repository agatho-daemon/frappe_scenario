frappe.pages["scenario-learning"].on_page_load = (wrapper) => {
	new ScenarioLearning(wrapper);
};

class ScenarioLearning {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Learn ERPNext"),
			single_column: true,
		});
		this.body = $('<div class="scenario-learning">').appendTo(this.page.main);
		this.run_name = frappe.utils.get_url_arg("run");
		this.load();
	}

	async load() {
		if (!this.run_name) {
			await this.load_training_home();
			return;
		}
		const response = await frappe.call({
			method: "frappe_scenario.api.learning.get_learning_home",
			args: { run_name: this.run_name },
			freeze: true,
			freeze_message: __("Preparing your learning paths…"),
		});
		this.model = response.message;
		this.render();
	}

	async load_training_home() {
		const response = await frappe.call({
			method: "frappe_scenario.api.learning.get_training_home",
			freeze: true,
			freeze_message: __("Preparing your training workspace…"),
		});
		this.training = response.message;
		this.render_training_home();
	}

	render_training_home() {
		this.page.set_title(__("ERPNext Learning and Training"));
		this.body.empty();
		const summary = this.training.summary;
		$(`<div class="mb-4"><h3>${__("Your learning workspace")}</h3>
			<p class="text-muted">${__(
				"Discover realistic ERPNext lessons, resume your work, or review completed learning."
			)}</p>
			<div class="row">
				${this.summary_card(__("Available"), summary.available, "blue")}
				${this.summary_card(__("In progress"), summary.active, "orange")}
				${this.summary_card(__("Completed"), summary.completed, "green")}
				${this.summary_card(__("Assigned"), summary.assigned, "gray")}
			</div></div>`).appendTo(this.body);
		if (!this.training.runs.length) {
			$(
				`<div class="alert alert-info">${__(
					"No completed, eligible Scenario Run is available yet. Ask a manager to generate a learning scenario."
				)}</div>`
			).appendTo(this.body);
			return;
		}
		this.training.runs.forEach((run) => this.render_training_run(run));
	}

	summary_card(label, value, color) {
		return `<div class="col-sm-3 mb-2"><div class="card"><div class="card-body">
			<span class="indicator-pill ${color}">${frappe.utils.escape_html(label)}</span>
			<h3 class="mt-2 mb-0">${value}</h3></div></div></div>`;
	}

	render_training_run(run) {
		const card = $(`<section class="card mb-3"><div class="card-body">
			<h4>${frappe.utils.escape_html(run.company || run.title)}</h4>
			<p class="text-muted">${frappe.utils.escape_html(run.title)} · ${frappe.utils.escape_html(
			run.archetype || ""
		)}</p><div class="training-paths"></div></div></section>`).appendTo(this.body);
		run.paths.forEach((path) => {
			const eligible = path.eligibility.eligible;
			const reasons = (path.eligibility.reasons || []).join(" ");
			const label =
				path.status === "Completed"
					? __("Review")
					: path.status === "In Progress"
					? __("Resume")
					: path.assigned
					? __("Start assignment")
					: __("Start learning");
			const row =
				$(`<div class="border rounded p-3 mb-2 d-flex justify-content-between align-items-center">
				<div><strong>${frappe.utils.escape_html(path.title)}</strong>
					<div class="text-muted small">${frappe.utils.escape_html(path.module)} · ${
					path.percent
				}% · ${frappe.utils.escape_html(path.status)}</div>${
					reasons
						? `<div class="text-danger small">${frappe.utils.escape_html(
								reasons
						  )}</div>`
						: ""
				}</div>
				<button class="btn btn-sm ${eligible ? "btn-primary" : "btn-default"}" ${
					eligible ? "" : "disabled"
				}>${label}</button>
			</div>`).appendTo(card.find(".training-paths"));
			row.find("button").on("click", () => this.open_training_path(run, path));
		});
	}

	async open_training_path(run, path) {
		if (!path.assigned) {
			await frappe.call({
				method: "frappe_scenario.api.learning.enroll_learning_path",
				type: "POST",
				args: { run_name: run.name, path_key: path.key },
			});
		}
		frappe.set_route("scenario-learning", { run: run.name, path: path.key });
	}

	render() {
		this.page.set_title(__("Learn ERPNext: {0}", [this.model.run.company]));
		this.page.clear_inner_toolbar();
		this.page.add_inner_button(__("All learning"), () =>
			frappe.set_route("scenario-learning")
		);
		if (frappe.user.has_role("System Manager")) {
			this.page.add_inner_button(__("What did I change?"), () => this.show_changes());
			this.page.add_inner_button(__("Save checkpoint"), () => this.save_checkpoint());
			this.page.add_inner_button(__("Restore scenario"), () => this.restore_scenario());
			this.page.add_inner_button(__("Troubleshooting Lab"), () => {
				frappe.set_route("scenario-troubleshooting", { run: this.run_name });
			});
		}
		this.body.empty();
		$(`<div class="mb-4">
			<h3>${frappe.utils.escape_html(this.model.run.company || this.model.run.title)}</h3>
			<p class="text-muted">${__(
				"Progressive lessons verified against the real documents and reports in this scenario."
			)}</p>
		</div>`).appendTo(this.body);

		this.model.paths.forEach((path) => this.render_path(path));
		this.render_glossary();
	}

	render_path(path) {
		const unavailable = !path.availability.available;
		const missing_steps = new Set(path.availability.missing_steps || []);
		const card = $(`<section class="card mb-3">
			<div class="card-body">
				<div class="d-flex justify-content-between">
					<div><span class="text-muted small">${frappe.utils.escape_html(path.module)}</span>
					<h4>${frappe.utils.escape_html(path.title)}</h4></div>
					<span class="indicator-pill ${
						path.progress.status === "Completed"
							? "green"
							: unavailable
							? "gray"
							: "blue"
					}">${path.progress.percent}%</span>
				</div>
				<p>${frappe.utils.escape_html(path.description)}</p>
				${
					unavailable
						? `<div class="alert alert-warning">${frappe.utils.escape_html(
								path.availability.message
						  )}</div>`
						: ""
				}
				<div class="lessons"></div>
				<button class="btn btn-xs btn-default restart-path">${__("Restart progress")}</button>
				${
					frappe.user.has_role("System Manager")
						? `<button class="btn btn-xs btn-default reset-module ml-2">${__(
								"Reset module data"
						  )}</button>`
						: ""
				}
				${
					path.key === "selling"
						? `<button class="btn btn-xs btn-primary launch-tutorial ml-2">${__(
								"Launch interactive tutorial"
						  )}</button>`
						: ""
				}
			</div>
		</section>`).appendTo(this.body);
		const completed = new Set(path.progress.completed_steps || []);
		path.lessons.forEach((lesson) => {
			const lesson_block = $(`<div class="mb-4"><h5>${frappe.utils.escape_html(
				lesson.title
			)}</h5>
				<p class="text-muted">${frappe.utils.escape_html(lesson.summary)}</p><ol class="steps"></ol>
				${
					frappe.user.has_role("System Manager")
						? `<button class="btn btn-xs btn-default reset-exercise">${__(
								"Reset this exercise"
						  )}</button>`
						: ""
				}</div>`).appendTo(card.find(".lessons"));
			lesson_block
				.find(".reset-exercise")
				.on("click", () => this.reset_exercise(path, lesson));
			lesson.steps.forEach((step) => {
				const step_id = `${lesson.key}/${step.key}`;
				const done = completed.has(step_id);
				const step_unavailable = missing_steps.has(step_id);
				const glossary = step.configuration.glossary
					? `<a href="#scenario-glossary-${frappe.scrub(
							step.configuration.glossary
					  )}" class="ml-2">${__("Glossary: {0}", [
							frappe.utils.escape_html(step.configuration.glossary),
					  ])}</a>`
					: "";
				const row = $(`<li class="mb-2 ${done ? "text-muted" : ""}">
					<span>${done ? "✓ " : ""}${frappe.utils.escape_html(step.title)}</span>${glossary}
					<button class="btn btn-xs ${done ? "btn-default" : "btn-primary"} ml-2 verify-step" ${
					step_unavailable ? "disabled" : ""
				}>${
					step_unavailable
						? __("Not in this dataset")
						: done
						? __("Verify again")
						: __("Verify and complete")
				}</button>
					<span class="step-result ml-2"></span>
				</li>`).appendTo(lesson_block.find(".steps"));
				row.find(".verify-step").on("click", () => this.verify(path, lesson, step, row));
			});
		});
		card.find(".restart-path").on("click", () => this.restart(path));
		card.find(".reset-module").on("click", () => this.reset_module(path));
		card.find(".launch-tutorial").on("click", () => {
			frappe.scenario_tutorial?.start(this.run_name);
		});
	}

	async reset_exercise(path, lesson) {
		frappe.confirm(
			__("Restore scenario-owned records used by {0} to the generated baseline?", [
				lesson.title,
			]),
			async () => {
				const response = await frappe.call({
					method: "frappe_scenario.api.experimentation.reset_lesson",
					type: "POST",
					args: { run_name: this.run_name, path_key: path.key, lesson_key: lesson.key },
					freeze: true,
				});
				this.show_reset_result(response.message);
				await this.load();
			}
		);
	}

	async reset_module(path) {
		frappe.confirm(
			__("Restore all scenario-owned records used by {0}?", [path.title]),
			async () => {
				const response = await frappe.call({
					method: "frappe_scenario.api.experimentation.reset_learning_module",
					type: "POST",
					args: { run_name: this.run_name, path_key: path.key },
					freeze: true,
				});
				this.show_reset_result(response.message);
				await this.load();
			}
		);
	}

	async show_changes() {
		const response = await frappe.call({
			method: "frappe_scenario.api.experimentation.get_changes",
			args: { run_name: this.run_name },
			freeze: true,
		});
		const result = response.message;
		const rows = result.changes.length
			? result.changes
					.map(
						(change) =>
							`<tr><td>${frappe.utils.escape_html(
								change.reference
							)}</td><td>${frappe.utils.escape_html(
								change.status
							)}</td><td>${frappe.utils.escape_html(
								(change.fields || []).join(", ")
							)}</td></tr>`
					)
					.join("")
			: `<tr><td colspan="3">${__("No changes from the generated baseline.")}</td></tr>`;
		frappe.msgprint({
			title: __("What did I change?"),
			message: `<p class="text-muted">${frappe.utils.escape_html(
				result.scope_note
			)}</p><div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__(
				"Record"
			)}</th><th>${__("State")}</th><th>${__(
				"Fields"
			)}</th></tr></thead><tbody>${rows}</tbody></table></div>`,
			wide: true,
		});
	}

	save_checkpoint() {
		frappe.prompt(
			{ fieldname: "label", fieldtype: "Data", label: __("Checkpoint name"), reqd: 1 },
			async (values) => {
				await frappe.call({
					method: "frappe_scenario.api.experimentation.save_checkpoint",
					type: "POST",
					args: { run_name: this.run_name, label: values.label },
					freeze: true,
				});
				frappe.show_alert({ message: __("Checkpoint saved"), indicator: "green" });
			},
			__("Save checkpoint")
		);
	}

	async restore_scenario() {
		const response = await frappe.call({
			method: "frappe_scenario.api.experimentation.get_checkpoints",
			args: { run_name: this.run_name },
		});
		const checkpoints = response.message;
		frappe.prompt(
			{
				fieldname: "checkpoint_name",
				fieldtype: "Select",
				label: __("Restore checkpoint"),
				options: checkpoints.map((item) => ({
					label: `${item.checkpoint_label} (${item.checkpoint_type})`,
					value: item.name,
				})),
				reqd: 1,
			},
			(values) => {
				frappe.confirm(
					__(
						"Restore every scenario-owned record to this checkpoint? Non-owned records will never be removed."
					),
					async () => {
						const restored = await frappe.call({
							method: "frappe_scenario.api.experimentation.restore_checkpoint",
							type: "POST",
							args: {
								run_name: this.run_name,
								checkpoint_name: values.checkpoint_name,
							},
							freeze: true,
						});
						this.show_reset_result(restored.message);
						await this.load();
					}
				);
			},
			__("Restore scenario")
		);
	}

	show_reset_result(result) {
		if (result.blockers.length) {
			frappe.msgprint({
				title: __("Reset needs attention"),
				indicator: "orange",
				message: result.blockers
					.map(
						(item) =>
							`<p><strong>${frappe.utils.escape_html(
								item.reference
							)}</strong>: ${frappe.utils.escape_html(item.message)}</p>`
					)
					.join(""),
			});
		} else {
			frappe.show_alert({
				message: __("Restored {0} record(s)", [result.restored]),
				indicator: "green",
			});
		}
	}

	async verify(path, lesson, step, row) {
		const response = await frappe.call({
			method: "frappe_scenario.api.learning.verify_lesson_step",
			type: "POST",
			args: {
				run_name: this.run_name,
				path_key: path.key,
				lesson_key: lesson.key,
				step_key: step.key,
			},
		});
		const result = response.message;
		row.find(".step-result")
			.text(result.message)
			.toggleClass("text-success", result.passed)
			.toggleClass("text-danger", !result.passed);
		if (result.passed && result.evidence.route) {
			$(
				`<a class="ml-2" href="${result.evidence.route}">${__("Open evidence")}</a>`
			).appendTo(row.find(".step-result"));
		}
		if (result.passed) {
			await this.load();
		}
	}

	restart(path) {
		frappe.confirm(
			__("Restart progress for {0}? This does not change ERPNext business records.", [
				path.title,
			]),
			async () => {
				await frappe.call({
					method: "frappe_scenario.api.learning.restart_learning_path",
					type: "POST",
					args: { run_name: this.run_name, path_key: path.key },
				});
				await this.load();
			}
		);
	}

	render_glossary() {
		const section = $(
			'<section class="card mt-4"><div class="card-body"><h3>' +
				__("Glossary") +
				"</h3></div></section>"
		).appendTo(this.body);
		Object.entries(this.model.glossary).forEach(([term, definition]) => {
			$(`<details id="scenario-glossary-${frappe.scrub(term)}" class="mb-2">
				<summary><strong>${frappe.utils.escape_html(term)}</strong> — ${frappe.utils.escape_html(
				definition.simple
			)}</summary>
				<p class="mt-2 text-muted">${frappe.utils.escape_html(definition.advanced)}</p>
			</details>`).appendTo(section.find(".card-body"));
		});
	}
}

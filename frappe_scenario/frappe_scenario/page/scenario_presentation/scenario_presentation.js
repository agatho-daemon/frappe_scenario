frappe.pages["scenario-presentation"].on_page_load = (wrapper) => {
	new ScenarioPresentation(wrapper);
};

class ScenarioPresentation {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Presentation Demo"),
			single_column: true,
		});
		this.body = $('<div class="scenario-presentation">').appendTo(this.page.main);
		this.run_name = frappe.utils.get_url_arg("run");
		this.load();
	}

	async load() {
		if (!this.run_name) {
			this.body.html(
				`<div class="alert alert-warning">${__(
					"Open Presentation from a completed Presentation Demo run."
				)}</div>`
			);
			return;
		}
		const response = await frappe.call({
			method: "frappe_scenario.api.runs.get_presentation",
			args: { run_name: this.run_name },
			freeze: true,
			freeze_message: __("Preparing the presentation…"),
		});
		this.model = response.message;
		this.render();
	}

	render() {
		const model = this.model;
		const identity = model.identity;
		this.body.css({
			"--scenario-primary": identity.palette.primary,
			"--scenario-accent": identity.palette.accent,
			"--scenario-surface": identity.palette.surface,
		});
		this.page.set_title(model.run.company || model.run.title);
		this.page.add_inner_button(__("Business Story"), () => {
			frappe.set_route("scenario-story", { run: this.run_name });
		});
		this.body.empty();
		const hero = $(`<section class="scenario-presentation-hero">
			<div class="scenario-presentation-logo"></div>
			<div><div class="text-muted small">${frappe.utils.escape_html(identity.style)}</div>
			<h2>${frappe.utils.escape_html(identity.company)}</h2>
			<p>${frappe.utils.escape_html(model.copy.primary.tagline)}</p>
			${
				model.copy.secondary
					? `<p class="scenario-presentation-secondary">${frappe.utils.escape_html(
							model.copy.secondary.tagline
					  )}</p>`
					: ""
			}</div></section>`).appendTo(this.body);
		if (identity.logo_svg) {
			hero.find(".scenario-presentation-logo").html(identity.logo_svg);
		}
		this.render_metrics();
		this.render_activity();
		this.render_tour();
	}

	render_metrics() {
		const grid = $('<section class="scenario-presentation-grid">').appendTo(this.body);
		this.model.metrics.forEach((metric) => {
			const value = metric.currency
				? format_currency(metric.value, metric.currency)
				: format_number(metric.value);
			$(`<a class="scenario-presentation-metric" href="${encodeURI(metric.route)}">
				<div class="text-muted">${frappe.utils.escape_html(metric.label)}</div>
				<div class="scenario-presentation-value">${frappe.utils.escape_html(value)}</div>
			</a>`).appendTo(grid);
		});
	}

	render_activity() {
		const section = $(`<section class="scenario-presentation-section mb-3">
			<h4>${frappe.utils.escape_html(this.model.copy.primary.recent)}</h4>
			<div class="list-group"></div></section>`).appendTo(this.body);
		this.model.recent_activity.forEach((event) => {
			$(`<a class="list-group-item" href="${encodeURI(event.route)}">
				<span class="text-muted small">${frappe.datetime.str_to_user(
					event.date
				)} · ${frappe.utils.escape_html(event.type)}</span><br>${frappe.utils.escape_html(
				event.title
			)}
			</a>`).appendTo(section.find(".list-group"));
		});
	}

	render_tour() {
		if (!this.model.tour.length) return;
		const section = $(`<section class="scenario-presentation-section">
			<h4>${frappe.utils.escape_html(this.model.copy.primary.tour)}</h4>
			<div class="scenario-tour"></div></section>`).appendTo(this.body);
		this.model.tour.forEach((step) => {
			$(`<div class="scenario-presentation-tour-step">
				<div class="text-muted small">${__("Step {0}", [step.sequence])} · ${__("{0} records", [
				step.evidence_count,
			])}</div>
				<h5>${frappe.utils.escape_html(step.title)}</h5>
				<p>${frappe.utils.escape_html(step.description)}</p>
				<a class="btn btn-sm btn-primary" href="${encodeURI(step.route)}">${__("Open in ERPNext")}</a>
			</div>`).appendTo(section.find(".scenario-tour"));
		});
	}
}

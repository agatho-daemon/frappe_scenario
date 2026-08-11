/* global cur_frm */

frappe.provide("frappe.scenario_tutorial");

(() => {
	const STORAGE_KEY = "frappe_scenario.active_tutorial";

	class ScenarioTutorialRunner {
		constructor() {
			this.pointer = this.read_pointer();
			frappe.router.on("change", () => this.on_route_change());
			$(document).on("click", ".scenario-tutorial-resume", () => this.resume());
			this.on_route_change();
		}

		async start(run_name) {
			const response = await this.call("start_selling_tutorial", { run_name });
			this.pointer = { run_name };
			this.write_pointer();
			await this.present(response.message);
		}

		async resume() {
			if (!this.pointer?.run_name) return;
			const response = await this.call("get_tutorial_state", {
				run_name: this.pointer.run_name,
			});
			await this.present(response.message);
		}

		async advance() {
			const response = await this.call("advance_selling_tutorial", {
				run_name: this.pointer.run_name,
			});
			const state = response.message;
			if (!state.passed) {
				frappe.msgprint({ title: __("Not verified yet"), message: state.message });
				return;
			}
			if (state.completed) {
				this.clear_pointer();
				frappe.msgprint({
					title: __("Tutorial complete"),
					indicator: "green",
					message: __("You completed the verified order-to-cash tutorial."),
				});
				return;
			}
			await this.present(state);
		}

		async exit() {
			if (this.pointer?.run_name) {
				await this.call("exit_selling_tutorial", { run_name: this.pointer.run_name });
			}
			this.clear_pointer();
			this.dialog?.hide();
		}

		async restart(run_name) {
			const response = await this.call("restart_selling_tutorial", { run_name });
			this.pointer = { run_name };
			this.write_pointer();
			await this.present(response.message);
		}

		async present(state) {
			if (!state?.step) return;
			this.pointer = { run_name: state.run.name };
			this.write_pointer();
			const step = state.step;
			this.dialog?.hide();
			this.dialog = new frappe.ui.Dialog({
				title: __("Order to cash — Step {0} of {1}", [step.position, step.total]),
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "instruction",
						options: `<p>${frappe.utils.escape_html(step.title)}</p>
							<p class="text-muted">${frappe.utils.escape_html(
								__("Your progress is saved for this lesson version and user.")
							)}</p>`,
					},
				],
				primary_action_label: __("Verify and continue"),
				primary_action: () => this.advance(),
				secondary_action_label: __("Exit for now"),
				secondary_action: () => this.exit(),
			});
			this.dialog.set_secondary_action_label(__("Exit for now"));
			this.dialog.add_custom_action(__("Open target"), () => {
				frappe.set_route(step.target.route);
			});
			this.dialog.add_custom_action(__("Restart tutorial"), () => {
				frappe.confirm(
					__("Restart this tutorial from its first step? Business records are unchanged."),
					() => this.restart(state.run.name)
				);
			});
			this.dialog.show();
			this.run_native_field_tour(step);
		}

		run_native_field_tour(step) {
			if (
				step.action !== "highlight_field" ||
				!step.target.fieldname ||
				typeof cur_frm === "undefined" ||
				!cur_frm ||
				cur_frm.doctype !== step.target.doctype ||
				cur_frm.doc.name !== step.target.name ||
				!frappe.ui.form.FormTour
			) {
				return;
			}
			const tour = new frappe.ui.form.FormTour({ frm: cur_frm });
			tour.tour = {
				steps: [
					{
						idx: 1,
						fieldname: step.target.fieldname,
						title: step.title,
						description: __("Inspect this value, then return to the tutorial to verify it."),
						position: "Bottom",
					},
				],
			};
			tour.init_driver();
			tour.build_steps();
			tour.update_driver_steps();
			tour.start();
		}

		on_route_change() {
			$(".scenario-tutorial-resume").remove();
			if (!this.pointer?.run_name) return;
			$(`<button class="btn btn-primary btn-sm scenario-tutorial-resume" style="position:fixed;right:24px;bottom:24px;z-index:1040">
				${frappe.utils.escape_html(__("Resume tutorial"))}
			</button>`).appendTo(document.body);
		}

		call(method, args) {
			return frappe.call({
				method: `frappe_scenario.api.learning.${method}`,
				type: method === "get_tutorial_state" ? "GET" : "POST",
				args,
			});
		}

		read_pointer() {
			try {
				return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
			} catch (_error) {
				return null;
			}
		}

		write_pointer() {
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(this.pointer));
			this.on_route_change();
		}

		clear_pointer() {
			this.pointer = null;
			window.localStorage.removeItem(STORAGE_KEY);
			this.on_route_change();
		}
	}

	frappe.ready(() => {
		frappe.scenario_tutorial = new ScenarioTutorialRunner();
	});
})();

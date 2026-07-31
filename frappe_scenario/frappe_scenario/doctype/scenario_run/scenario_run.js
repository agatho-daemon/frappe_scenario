frappe.ui.form.on("Scenario Run", {
	refresh(frm) {
		let specification = {};
		try {
			specification = JSON.parse(frm.doc.specification || "{}");
		} catch (_error) {
			specification = {};
		}
		if (
			frm.doc.status === "Completed" &&
			specification.scenario?.intent === "Presentation Demo"
		) {
			frm.add_custom_button(__("Open Presentation"), () => {
				frappe.set_route("scenario-presentation", { run: frm.doc.name });
			});
		}
		if (!frm.is_new() && frm.doc.event_count) {
			frm.add_custom_button(__("Open Business Story"), () => {
				frappe.set_route("scenario-story", { run: frm.doc.name });
			});
			if (frm.doc.status === "Completed") {
				frm.add_custom_button(__("Start Learning"), () => {
					frappe.set_route("scenario-learning", { run: frm.doc.name });
				});
			}
		}
	},
});

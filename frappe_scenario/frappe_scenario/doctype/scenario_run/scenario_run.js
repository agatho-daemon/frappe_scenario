frappe.ui.form.on("Scenario Run", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.event_count) {
			frm.add_custom_button(__("Open Business Story"), () => {
				frappe.set_route("scenario-story", { run: frm.doc.name });
			});
		}
	},
});

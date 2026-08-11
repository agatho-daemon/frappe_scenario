frappe.provide("frappe.scenario_tutorial_compatibility");

(() => {
	const TARGET_KINDS = new Set([
		"doctype_field",
		"form_control",
		"registered_action",
		"workspace_shortcut",
		"report",
		"tutorial_hook",
		"document",
	]);

	/**
	 * Client compatibility is deliberately internal. The server supplies only a
	 * semantic kind and identifiers; definitions cannot supply executable
	 * expressions or presentation-engine locators.
	 */
	frappe.scenario_tutorial_compatibility = {
		validate(target) {
			const semantic = target?.semantic;
			if (!semantic || !TARGET_KINDS.has(semantic.kind)) {
				throw new Error(__("Unsupported tutorial target."));
			}
			return semantic;
		},

		field(target) {
			const semantic = this.validate(target);
			if (
				semantic.kind !== "doctype_field" ||
				typeof cur_frm === "undefined" ||
				!cur_frm ||
				cur_frm.doctype !== semantic.doctype
			) {
				return null;
			}
			return cur_frm.get_field(semantic.fieldname) || null;
		},

		form_control(target) {
			const semantic = this.validate(target);
			if (semantic.kind !== "form_control" || typeof cur_frm === "undefined" || !cur_frm) {
				return null;
			}
			return semantic.control === "save" ? cur_frm.page?.btn_primary : null;
		},
	};
})();

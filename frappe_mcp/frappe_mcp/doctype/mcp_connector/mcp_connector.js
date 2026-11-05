frappe.ui.form.on("MCP Connector", {
	user(frm) {
		if (!frm.is_new() || !frm.doc.user) {
			return;
		}
		frappe.db.get_value("MCP Connector", { user: frm.doc.user }, "name").then((response) => {
			const existing = response.message && response.message.name;
			if (existing) {
				frappe.msgprint(
					__("User {0} already has connector {1}. One user can have only one MCP connector.", [
						frm.doc.user,
						existing,
					])
				);
			}
		});
	},
	refresh(frm) {
		if (frm.is_new()) {
			if (!frm.doc.user) {
				frm.set_value("user", frappe.session.user);
			}
			return;
		}
		frm.add_custom_button(__("Regenerate Token"), () => {
			frappe.confirm(
				__("The current token stops working immediately. Continue?"),
				() => {
					frappe.call({
						method: "frappe_mcp.api.connector.regenerate_token",
						args: { name: frm.doc.name },
						freeze: true,
						callback(response) {
							frm.reload_doc();
							frappe_mcp.show_token_dialog(response.message || {});
						},
					});
				}
			);
		});
	},
});

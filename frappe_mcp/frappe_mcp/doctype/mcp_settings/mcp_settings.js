frappe.ui.form.on("MCP Settings", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("OAuth Client"), () => {
			frappe.call({
				method: "frappe_mcp.api.oauth.default_client",
				freeze: true,
				callback(response) {
					const data = response.message || {};
					frappe.msgprint({
						title: __("OAuth client"),
						message: data.html || "",
						wide: true,
					});
				},
			});
		});
		frm.add_custom_button(__("Test Embedding"), () => {
			frappe.call({
				method: "frappe_mcp.api.maintenance.test_embedding",
				freeze: true,
				callback(response) {
					const data = response.message || {};
					frappe.msgprint(__("Embedding OK. Dimensions: {0}", [data.dimensions]));
				},
			});
		}, __("Semantic Search"));
		frm.add_custom_button(__("Reindex"), () => {
			frappe.call({
				method: "frappe_mcp.api.maintenance.reindex_semantic_search",
				freeze: true,
				callback() {
					frappe.show_alert({ message: __("Index queued"), indicator: "blue" });
				},
			});
		}, __("Semantic Search"));
		frm.add_custom_button(__("Reset Vector Index"), () => {
			frappe.confirm(
				__("This deletes this site's Qdrant collections and rebuilds them. Continue?"),
				() => {
					frappe.call({
						method: "frappe_mcp.api.maintenance.reset_vector_index",
						freeze: true,
						callback() {
							frappe.show_alert({ message: __("Vector index reset queued"), indicator: "orange" });
						},
					});
				}
			);
		}, __("Semantic Search"));
	},
});

frappe.provide("frappe_mcp");

frappe_mcp.can_bulk_connectors = function () {
	return frappe.session.user === "Administrator" || frappe.user.has_role("System Manager");
};

frappe_mcp.show_token_dialog = function (data) {
	const token = data.token || "";
	const config = data.client_config || "";
	const endpoint = (data.endpoint || "").replace(/\/$/, "");
	const serverUrl = data.server_url || (token && endpoint ? endpoint + "/" + token + "/message" : "");
	const dialog = new frappe.ui.Dialog({
		title: __("MCP token"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "body",
			},
		],
	});
	const block = (label, value, copyClass, copyLabel) =>
		"<p><b>" +
		label +
		"</b></p>" +
		"<pre class='mcp-token-block'>" +
		frappe.utils.escape_html(value) +
		"</pre>" +
		"<p><button type='button' class='btn btn-default btn-sm " +
		copyClass +
		"'>" +
		copyLabel +
		"</button></p>";
	dialog.fields_dict.body.$wrapper.html(
		"<p>" +
			__("Paste the server URL into the MCP client. The key is inside the link.") +
			"</p>" +
			block(__("Server URL"), serverUrl, "mcp-copy-url", __("Copy URL")) +
			block(__("Token"), token, "mcp-copy-token", __("Copy token")) +
			block(__("Client config"), config, "mcp-copy-config", __("Copy config"))
	);
	dialog.$wrapper.find(".mcp-token-block").css({
		"white-space": "pre-wrap",
		"word-break": "break-all",
		"user-select": "all",
		background: "var(--bg-light-gray, #f4f5f6)",
		padding: "8px",
		"border-radius": "6px",
	});
	dialog.$wrapper.find(".mcp-copy-url").on("click", () => frappe_mcp.copy_text(serverUrl));
	dialog.$wrapper.find(".mcp-copy-token").on("click", () => frappe_mcp.copy_text(token));
	dialog.$wrapper.find(".mcp-copy-config").on("click", () => frappe_mcp.copy_text(config));
	dialog.show();
};

frappe_mcp.copy_text = function (text) {
	if (navigator.clipboard && navigator.clipboard.writeText) {
		navigator.clipboard.writeText(text).then(() => {
			frappe.show_alert({ message: __("Copied"), indicator: "green" });
		});
		return;
	}
	frappe.utils.copy_to_clipboard(text);
};

frappe_mcp.download_connector_csv = function (rows, filename) {
	const headers = [
		"name",
		"connector_name",
		"user",
		"token",
		"endpoint",
		"client_config",
	];
	const lines = [headers.join(",")];
	(rows || []).forEach((row) => {
		lines.push(
			headers
				.map((key) => {
					const value = row[key] == null ? "" : String(row[key]);
					return '"' + value.replace(/"/g, '""') + '"';
				})
				.join(",")
		);
	});
	const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.href = url;
	link.download = filename || "mcp-connectors.csv";
	link.click();
	URL.revokeObjectURL(url);
};

frappe.listview_settings["MCP Connector"] = {
	onload(listview) {
		if (!frappe_mcp.can_bulk_connectors()) {
			return;
		}
		const page = listview.page;
		page.add_menu_item(__("Bulk Create"), () => {
			frappe_mcp.open_bulk_create(listview);
		});
		page.add_menu_item(__("Export Connectors"), () => {
			const names = listview.get_checked_items(true);
			const args = names.length ? { names } : {};
			open_url_post("/api/method/frappe_mcp.api.connector.export_connectors", args);
		});
		page.add_menu_item(__("Regenerate & Export"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Select at least one connector."));
				return;
			}
			frappe.confirm(
				__(
					"This replaces the token on every selected connector. Old tokens stop working. A CSV with the new tokens downloads once."
				),
				() => {
					frappe.call({
						method: "frappe_mcp.api.connector.regenerate_and_export",
						args: { names },
						freeze: true,
						callback(response) {
							const rows = response.message || [];
							frappe_mcp.download_connector_csv(rows, "mcp-connector-tokens.csv");
							listview.refresh();
						},
					});
				}
			);
		});
	},
};

frappe_mcp.load_bulk_users = function (dialog) {
	if (dialog.get_value("all_users")) {
		return;
	}
	const box = dialog.fields_dict.user_list;
	if (!box) {
		return;
	}
	frappe.call({
		method: "frappe_mcp.api.connector.user_link_options",
		args: {
			txt: dialog.get_value("user_search") || "",
			role: dialog.get_value("role") || "",
			limit: 200,
		},
		callback(response) {
			frappe_mcp.render_bulk_users(dialog, response.message || []);
		},
	});
};

frappe_mcp.render_bulk_users = function (dialog, users) {
	const selected = dialog._selected_users || new Set();
	const wrapper = dialog.fields_dict.user_list.$wrapper.empty();
	if (!users.length) {
		wrapper.append($("<div class='text-muted'>").text(__("No users match.")));
		return;
	}
	const list = $("<div>").css({
		"max-height": "240px",
		overflow: "auto",
		border: "1px solid var(--border-color)",
		"border-radius": "8px",
		padding: "8px 12px",
	});
	const select_all = $("<label>").css({
		display: "flex",
		gap: "8px",
		"align-items": "center",
		"font-weight": "600",
		margin: "0 0 6px",
	});
	const select_all_input = $("<input type='checkbox' class='mcp-bulk-all'>");
	select_all.append(select_all_input, document.createTextNode(__("Select all shown")));
	list.append(select_all);
	users.forEach((user) => {
		const row = $("<label>").css({
			display: "flex",
			gap: "8px",
			"align-items": "center",
			margin: "0",
			padding: "4px 0",
		});
		const input = $("<input type='checkbox' class='mcp-bulk-user'>");
		if (user.taken) {
			input.prop("disabled", true);
			row.addClass("text-muted");
		} else if (selected.has(user.value)) {
			input.prop("checked", true);
		}
		input.on("change", function () {
			if (this.checked) {
				selected.add(user.value);
			} else {
				selected.delete(user.value);
			}
		});
		const text = $("<span>");
		text.append(document.createTextNode((user.description || user.value) + " "));
		text.append($("<span class='text-muted'>").text("(" + user.value + ")"));
		if (user.taken) {
			text.append($("<span class='text-muted'>").text(" " + __("already has a connector")));
		}
		row.append(input, text);
		list.append(row);
	});
	select_all_input.on("change", function () {
		const on = this.checked;
		list.find(".mcp-bulk-user:not(:disabled)").each(function () {
			this.checked = on;
			$(this).trigger("change");
		});
	});
	dialog._selected_users = selected;
	wrapper.append(list);
};

frappe_mcp.refresh_bulk_match = function (dialog) {
	const info = dialog.fields_dict.match_info;
	if (!info) {
		return;
	}
	if (!dialog.get_value("all_users")) {
		info.$wrapper.empty();
		return;
	}
	frappe.call({
		method: "frappe_mcp.api.connector.matching_users",
		args: { role: dialog.get_value("role") },
		callback(response) {
			const data = response.message || {};
			info.$wrapper.html(
				"<p class='text-muted'>" +
					__(
						"{0} user(s) will get a connector. {1} already have one and will be skipped.",
						[data.count || 0, data.skipped || 0]
					) +
					"</p>"
			);
		},
	});
};

frappe_mcp.open_bulk_create = function (listview) {
	const dialog = new frappe.ui.Dialog({
		title: __("Bulk Create MCP Connectors"),
		size: "large",
		fields: [
			{
				fieldname: "role",
				fieldtype: "Link",
				label: __("Role"),
				options: "Role",
				description: __("Search a role. Blank means every enabled user except Guest."),
			},
			{
				fieldname: "connector_name",
				fieldtype: "Data",
				label: __("Connector Name"),
				reqd: 1,
				description: __("Written on every connector created in this batch."),
			},
			{
				fieldname: "all_users",
				fieldtype: "Check",
				label: __("All matching users"),
				description: __("One connector for every enabled user in this filter who does not already have one."),
			},
			{
				fieldname: "match_info",
				fieldtype: "HTML",
			},
			{
				fieldname: "user_search",
				fieldtype: "Data",
				label: __("Search Users"),
				depends_on: "eval:!doc.all_users",
				placeholder: __("Name or email"),
			},
			{
				fieldname: "user_list",
				fieldtype: "HTML",
				depends_on: "eval:!doc.all_users",
			},
		],
		primary_action_label: __("Create and Download CSV"),
		primary_action(values) {
			const connector_name = (values.connector_name || "").trim();
			if (!connector_name) {
				frappe.msgprint(__("Connector Name is required."));
				return;
			}
			const users = values.all_users ? [] : Array.from(dialog._selected_users || []);
			if (!values.all_users && !users.length) {
				frappe.msgprint(__("Select at least one user, or check All matching users."));
				return;
			}
			frappe.call({
				method: "frappe_mcp.api.connector.bulk_create",
				args: {
					users: users,
					role: values.role,
					all_users: values.all_users ? 1 : 0,
					connector_name: connector_name,
				},
				freeze: true,
				callback(response) {
					const payload = response.message || {};
					const rows = payload.created || [];
					dialog.hide();
					frappe_mcp.download_connector_csv(rows, "mcp-connectors.csv");
					let message = __(
						"Created {0} connector(s). The CSV contains the tokens. They will not be shown again.",
						[rows.length]
					);
					if (payload.skipped) {
						message += " " + __("Skipped {0} user(s) who already have a connector.", [payload.skipped]);
					}
					frappe.msgprint(message);
					listview.refresh();
				},
			});
		},
	});
	dialog._selected_users = new Set();
	dialog.fields_dict.role.df.onchange = () => {
		dialog._selected_users = new Set();
		frappe_mcp.refresh_bulk_match(dialog);
		frappe_mcp.load_bulk_users(dialog);
	};
	dialog.fields_dict.all_users.df.onchange = () => {
		frappe_mcp.refresh_bulk_match(dialog);
		frappe_mcp.load_bulk_users(dialog);
	};
	dialog.show();
	dialog.$wrapper.find(".modal-body").css("overflow", "visible");
	if (dialog.fields_dict.role.awesomplete) {
		dialog.fields_dict.role.awesomplete.ul.style.zIndex = "2000";
	}
	dialog.fields_dict.user_search.$input.on(
		"input",
		frappe.utils.debounce(() => frappe_mcp.load_bulk_users(dialog), 300)
	);
	frappe_mcp.load_bulk_users(dialog);
};

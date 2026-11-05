# Copyright (c) 2026, Shaid Azmin and contributors
# For license information, please see license.txt

"""OAuth 2.1 for ChatGPT and Gemini.

Static connector tokens stay valid. An OAuth access token is a second key
that points at the same user's one MCP Connector.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import frappe
from frappe.utils import add_to_date, escape_html, get_datetime, now_datetime

ACCESS_SECONDS = 60 * 60
REFRESH_DAYS = 30
CODE_MINUTES = 10


def external_base() -> str:
	"""Public origin the client used. Ngrok sends this in forwarded headers."""
	proto, host = "https", ""
	try:
		proto = frappe.get_request_header("X-Forwarded-Proto") or getattr(frappe.request, "scheme", "") or "https"
		host = frappe.get_request_header("X-Forwarded-Host") or getattr(frappe.request, "host", "") or ""
	except Exception:
		proto, host = "https", ""
	proto = str(proto).split(",")[0].strip().lower() or "https"
	host = str(host).split(",")[0].strip()
	if proto not in ("http", "https") or not host or "/" in host or " " in host or "\\" in host:
		return frappe.utils.get_url().rstrip("/")
	return f"{proto}://{host}".rstrip("/")


def www_authenticate() -> str:
	meta = external_base() + "/.well-known/oauth-protected-resource/mcp"
	return f'Bearer realm="frappe-mcp", resource_metadata="{meta}"'


def authorization_server_metadata(base: str | None = None) -> dict:
	base = (base or external_base()).rstrip("/")
	return {
		"issuer": base,
		"authorization_endpoint": base + "/oauth/authorize",
		"token_endpoint": base + "/oauth/token",
		"registration_endpoint": base + "/register",
		"response_types_supported": ["code"],
		"response_modes_supported": ["query"],
		"grant_types_supported": ["authorization_code", "refresh_token"],
		"code_challenge_methods_supported": ["S256"],
		"token_endpoint_auth_methods_supported": [
			"client_secret_post",
			"client_secret_basic",
			"none",
		],
		"scopes_supported": ["mcp"],
		"authorization_response_iss_parameter_supported": True,
	}


def protected_resource_metadata(base: str | None = None) -> dict:
	base = (base or external_base()).rstrip("/")
	return {
		"resource": base + "/mcp",
		"authorization_servers": [base],
		"bearer_methods_supported": ["header"],
		"scopes_supported": ["mcp"],
	}


def s256(verifier: str) -> str:
	digest = hashlib.sha256(verifier.encode("ascii")).digest()
	return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _hash(value: str) -> str:
	from frappe_mcp.mcp.auth import token_hash

	return token_hash(value)


def _safe_redirect(uri: str) -> bool:
	if not uri or len(uri) > 750 or any(char in uri for char in "\r\n\x00 "):
		return False
	parts = urlsplit(uri)
	if parts.fragment or not parts.scheme or not parts.netloc:
		return False
	if parts.scheme == "https":
		return True
	host = (parts.hostname or "").lower()
	return parts.scheme == "http" and host in ("localhost", "127.0.0.1")


def _redirects(client) -> list:
	try:
		rows = json.loads(client.redirect_uris or "[]")
	except json.JSONDecodeError:
		return []
	return [row for row in rows if isinstance(row, str)]


def redirect_allowed(client, uri: str) -> bool:
	if not _safe_redirect(uri):
		return False
	if uri in _redirects(client):
		return True
	return bool(client.is_default) and uri.startswith("https://")


def _client(client_id: str):
	if not client_id or not frappe.db.exists("MCP OAuth Client", client_id):
		return None
	return frappe.get_doc("MCP OAuth Client", client_id)


def ensure_default_client():
	if not frappe.db.table_exists("MCP OAuth Client"):
		return None
	name = frappe.db.get_value("MCP OAuth Client", {"is_default": 1}, "name")
	if name:
		return frappe.get_doc("MCP OAuth Client", name)
	client_id = "fmcp-client-" + secrets.token_urlsafe(18)
	secret = secrets.token_urlsafe(32)
	doc = frappe.get_doc(
		{
			"doctype": "MCP OAuth Client",
			"client_id": client_id,
			"client_name": "Frappe MCP",
			"auth_method": "client_secret_post",
			"is_default": 1,
			"client_secret": secret,
			"client_secret_hash": _hash(secret),
			"redirect_uris": "[]",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def register_client(payload: dict) -> tuple[int, dict]:
	if registration_limited():
		return 429, {"error": "slow_down", "error_description": "Too many registrations."}
	raw_uris = payload.get("redirect_uris") or []
	if isinstance(raw_uris, str):
		raw_uris = [raw_uris]
	uris = []
	for uri in raw_uris:
		if not isinstance(uri, str) or not _safe_redirect(uri) or uri in uris:
			return 400, {"error": "invalid_redirect_uri", "error_description": "Redirect URI must be https."}
		uris.append(uri)
	if not uris or len(uris) > 10:
		return 400, {"error": "invalid_redirect_uri", "error_description": "One to ten redirect URIs are required."}
	method = payload.get("token_endpoint_auth_method") or "none"
	if method not in ("none", "client_secret_post", "client_secret_basic"):
		return 400, {"error": "invalid_client_metadata", "error_description": "Unsupported token auth method."}
	name = str(payload.get("client_name") or "MCP client")[:120]
	client_id = "fmcp-client-" + secrets.token_urlsafe(18)
	secret = secrets.token_urlsafe(32) if method != "none" else ""
	doc = frappe.get_doc(
		{
			"doctype": "MCP OAuth Client",
			"client_id": client_id,
			"client_name": name,
			"auth_method": method,
			"is_default": 0,
			"client_secret": secret,
			"client_secret_hash": _hash(secret) if secret else "",
			"redirect_uris": json.dumps(uris),
		}
	)
	doc.insert(ignore_permissions=True)
	body = {
		"client_id": client_id,
		"client_name": name,
		"redirect_uris": uris,
		"grant_types": ["authorization_code", "refresh_token"],
		"response_types": ["code"],
		"token_endpoint_auth_method": method,
		"client_secret_expires_at": 0,
	}
	if secret:
		body["client_secret"] = secret
	return 201, body


def registration_limited() -> bool:
	ip = getattr(frappe.local, "request_ip", None) or "unknown"
	hour = now_datetime().strftime("%Y%m%d%H")
	key = f"frappe_mcp:dcr:{ip}:{hour}"
	current = int(frappe.cache().get_value(key) or 0)
	if current >= 30:
		return True
	frappe.cache().set_value(key, current + 1, expires_in_sec=3700)
	return False


def issue_code(client_id: str, user: str, redirect_uri: str, code_challenge: str = "") -> str:
	raw = secrets.token_urlsafe(32)
	frappe.get_doc(
		{
			"doctype": "MCP OAuth Code",
			"code_hash": _hash(raw),
			"client_id": client_id,
			"user": user,
			"redirect_uri": redirect_uri,
			"code_challenge": code_challenge or "",
			"expires": add_to_date(now_datetime(), minutes=CODE_MINUTES),
			"used": 0,
		}
	).insert(ignore_permissions=True)
	return raw


def _burn_code(name: str) -> None:
	frappe.db.set_value("MCP OAuth Code", name, "used", 1, update_modified=False)


def _pkce_ok(challenge: str, verifier: str) -> bool:
	if not challenge or not verifier or len(verifier) < 43 or len(verifier) > 128:
		return False
	try:
		return hmac.compare_digest(challenge, s256(verifier))
	except Exception:
		return False


def _secret_ok(client, presented: str) -> bool:
	if client.auth_method == "none":
		return True
	stored = client.client_secret_hash or ""
	if not stored or not presented:
		return False
	try:
		return hmac.compare_digest(stored, _hash(presented))
	except Exception:
		return False


def exchange(params: dict) -> tuple[int, dict]:
	grant = params.get("grant_type") or ""
	client_id = params.get("client_id") or ""
	client = _client(client_id)
	if not client or not _secret_ok(client, params.get("client_secret") or ""):
		return 401, {"error": "invalid_client", "error_description": "Client authentication failed."}
	if grant == "authorization_code":
		return _exchange_code(client, params)
	if grant == "refresh_token":
		return _exchange_refresh(client, params)
	return 400, {"error": "unsupported_grant_type", "error_description": "Use authorization_code or refresh_token."}


def _exchange_code(client, params: dict) -> tuple[int, dict]:
	raw = params.get("code") or ""
	row = frappe.db.get_value(
		"MCP OAuth Code",
		{"code_hash": _hash(raw)} if raw else {"name": ""},
		["name", "client_id", "user", "redirect_uri", "code_challenge", "expires", "used"],
		as_dict=True,
	)
	if not row or row.used or row.client_id != client.client_id:
		return 400, {"error": "invalid_grant", "error_description": "Authorization code is not valid."}
	if get_datetime(row.expires) < now_datetime():
		_burn_code(row.name)
		return 400, {"error": "invalid_grant", "error_description": "Authorization code expired."}
	if (params.get("redirect_uri") or "") != row.redirect_uri:
		_burn_code(row.name)
		return 400, {"error": "invalid_grant", "error_description": "Redirect URI does not match."}
	public = client.auth_method == "none"
	if row.code_challenge:
		if not _pkce_ok(row.code_challenge, params.get("code_verifier") or ""):
			_burn_code(row.name)
			return 400, {"error": "invalid_grant", "error_description": "PKCE verification failed."}
	elif public:
		_burn_code(row.name)
		return 400, {"error": "invalid_request", "error_description": "PKCE is required."}
	_burn_code(row.name)
	if not frappe.db.get_value("User", row.user, "enabled"):
		return 400, {"error": "invalid_grant", "error_description": "User is disabled."}
	return 200, _issue_token(client.client_id, row.user)


def _exchange_refresh(client, params: dict) -> tuple[int, dict]:
	raw = params.get("refresh_token") or ""
	row = frappe.db.get_value(
		"MCP OAuth Token",
		{"refresh_hash": _hash(raw)} if raw else {"name": ""},
		["name", "client_id", "user", "refresh_expires"],
		as_dict=True,
	)
	if not row or row.client_id != client.client_id:
		return 400, {"error": "invalid_grant", "error_description": "Refresh token is not valid."}
	if row.refresh_expires and get_datetime(row.refresh_expires) < now_datetime():
		return 400, {"error": "invalid_grant", "error_description": "Refresh token expired."}
	if not frappe.db.get_value("User", row.user, "enabled"):
		return 400, {"error": "invalid_grant", "error_description": "User is disabled."}
	return 200, _issue_token(client.client_id, row.user, replace=row.name)


def _issue_token(client_id: str, user: str, replace: str | None = None) -> dict:
	connector = ensure_connector(user)
	access = "fmcp_oa_" + secrets.token_urlsafe(32)
	refresh = secrets.token_urlsafe(32)
	values = {
		"access_hash": _hash(access),
		"refresh_hash": _hash(refresh),
		"client_id": client_id,
		"user": user,
		"connector": connector,
		"expires": add_to_date(now_datetime(), seconds=ACCESS_SECONDS),
		"refresh_expires": add_to_date(now_datetime(), days=REFRESH_DAYS),
	}
	if replace:
		frappe.db.set_value("MCP OAuth Token", replace, values, update_modified=False)
	else:
		frappe.get_doc({"doctype": "MCP OAuth Token", **values}).insert(ignore_permissions=True)
	return {
		"access_token": access,
		"token_type": "Bearer",
		"expires_in": ACCESS_SECONDS,
		"refresh_token": refresh,
		"scope": "mcp",
	}


def ensure_connector(user: str) -> str:
	existing = frappe.db.get_value("MCP Connector", {"user": user}, "name")
	if existing:
		return existing
	full_name = frappe.db.get_value("User", user, "full_name") or user
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		doc = frappe.get_doc(
			{
				"doctype": "MCP Connector",
				"user": user,
				"connector_name": full_name,
				"enabled": 1,
			}
		)
		doc.flags.skip_token_dialog = True
		doc.insert(ignore_permissions=True)
		return doc.name
	finally:
		if frappe.session.user != previous:
			frappe.set_user(previous)


def connector_for_access_token(token: str):
	if not token or not frappe.db.exists("DocType", "MCP OAuth Token"):
		return None
	row = frappe.db.get_value(
		"MCP OAuth Token",
		{"access_hash": _hash(token)},
		["connector", "user", "expires"],
		as_dict=True,
	)
	if not row or not row.connector:
		return None
	if row.expires and get_datetime(row.expires) < now_datetime():
		return None
	connector = frappe.get_doc("MCP Connector", row.connector)
	if connector.user != row.user:
		return None
	return connector


def request_params() -> dict:
	raw = ""
	try:
		raw = frappe.request.get_data(as_text=True) or ""
	except Exception:
		raw = ""
	ctype = ""
	try:
		ctype = (frappe.get_request_header("Content-Type") or "").lower()
	except Exception:
		ctype = ""
	payload = {}
	if raw.strip().startswith("{") and ("json" in ctype or not ctype):
		try:
			payload = json.loads(raw)
		except json.JSONDecodeError:
			payload = {}
	elif raw and "=" in raw:
		payload = {key: values[-1] for key, values in parse_qsl_multi(raw).items()}
	form = dict(getattr(frappe.local, "form_dict", None) or {})
	for key, value in form.items():
		if key in ("cmd", "data"):
			continue
		if key not in payload or payload.get(key) in (None, ""):
			payload[key] = value[-1] if isinstance(value, (list, tuple)) else value
	basic_id, basic_secret = basic_client()
	if basic_id and not payload.get("client_id"):
		payload["client_id"] = basic_id
	if basic_secret and not payload.get("client_secret"):
		payload["client_secret"] = basic_secret
	args = getattr(frappe.request, "args", None)
	if args:
		for key in ("client_id", "redirect_uri", "response_type", "code_challenge", "code_challenge_method", "state", "scope"):
			if key not in payload and args.get(key):
				payload[key] = args.get(key)
	return payload


def parse_qsl_multi(raw: str) -> dict:
	rows = {}
	for key, value in parse_qsl(raw, keep_blank_values=True):
		rows.setdefault(key, []).append(value)
	return rows


def basic_client() -> tuple[str, str]:
	try:
		header = frappe.get_request_header("Authorization") or ""
	except Exception:
		return "", ""
	if not header.lower().startswith("basic "):
		return "", ""
	try:
		decoded = base64.b64decode(header.split(" ", 1)[1].strip()).decode()
		client_id, secret = decoded.split(":", 1)
	except Exception:
		return "", ""
	return client_id, secret


def authorize(params: dict):
	client = _client(params.get("client_id") or "")
	redirect_uri = params.get("redirect_uri") or ""
	if not client or not redirect_allowed(client, redirect_uri):
		return html_page("This sign-in link is not valid.", "The app link could not be verified."), 400
	state = str(params.get("state") or "").replace("\r", "").replace("\n", "")
	if (params.get("response_type") or "") != "code":
		return finish_redirect(redirect_uri, {"error": "unsupported_response_type", "state": state})
	challenge = params.get("code_challenge") or ""
	method = (params.get("code_challenge_method") or "").strip()
	if challenge and method.lower() == "s256":
		method = "S256"
	elif challenge and not method:
		method = "S256"
	elif challenge and method != "S256":
		return finish_redirect(redirect_uri, {"error": "invalid_request", "state": state})
	if client.auth_method == "none" and not challenge:
		return finish_redirect(redirect_uri, {"error": "invalid_request", "state": state})
	user = frappe.session.user
	if user in ("", "Guest"):
		return redirect_response("/login?" + urlencode({"redirect-to": login_target()}))
	if frappe.request.method == "POST":
		return submit_consent(client, user, redirect_uri, challenge, state, params)
	return consent_page(client, user, redirect_uri, challenge, method, state), 200


def submit_consent(client, user, redirect_uri, challenge, state, params):
	if not csrf_ok(params.get("csrf_token")):
		return html_page("Sign-in expired.", "Go back to the chat app and try connecting again."), 403
	if (params.get("decision") or "") != "allow":
		return finish_redirect(redirect_uri, {"error": "access_denied", "state": state})
	if not frappe.db.get_value("User", user, "enabled"):
		return finish_redirect(redirect_uri, {"error": "access_denied", "state": state})
	code = issue_code(client.client_id, user, redirect_uri, challenge)
	return finish_redirect(redirect_uri, {"code": code, "state": state})


def finish_redirect(redirect_uri: str, params: dict):
	query = {}
	for key, value in params.items():
		if key == "state":
			query["state"] = "" if value is None else str(value)
			continue
		if value:
			query[key] = value
	query["iss"] = external_base()
	return redirect_response(with_query(redirect_uri, query))


def with_query(uri: str, params: dict) -> str:
	parts = urlsplit(uri)
	current = dict(parse_qsl(parts.query, keep_blank_values=True))
	current.update(params)
	return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(current), ""))


def redirect_response(location: str):
	response = frappe_response("", 302, "text/plain")
	response.headers["Location"] = location
	return response


def login_target() -> str:
	request = frappe.request
	full = getattr(request, "full_path", None) or ""
	if full.startswith("/oauth/authorize"):
		return full
	query = getattr(request, "query_string", b"") or b""
	if isinstance(query, bytes):
		query = query.decode()
	if query:
		return "/oauth/authorize?" + query
	return "/oauth/authorize"


def csrf_ok(posted) -> bool:
	"""Frappe already checked csrf_token and then removed it from the form."""
	try:
		expected = frappe.local.session.data.csrf_token
	except Exception:
		return False
	if not expected:
		return False
	if not posted:
		return True
	try:
		return hmac.compare_digest(str(expected), str(posted))
	except Exception:
		return False


def consent_page(client, user, redirect_uri, challenge, method, state) -> str:
	from frappe.sessions import get_csrf_token

	full_name, email = frappe.db.get_value("User", user, ["full_name", "email"]) or (user, user)
	who = escape_html(full_name or email or user)
	app_name = escape_html(client.client_name or "This app")
	fields = {
		"client_id": client.client_id,
		"redirect_uri": redirect_uri,
		"response_type": "code",
		"code_challenge": challenge,
		"code_challenge_method": method,
		"state": state,
		"csrf_token": get_csrf_token(),
	}
	hidden = "".join(
		f'<input type="hidden" name="{escape_html(key)}" value="{escape_html(str(value or ""))}">'
		for key, value in fields.items()
	)
	return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect {app_name}</title>
<style>
body{{margin:0;background:#f4f5f7;font:16px/1.45 system-ui,sans-serif;color:#1f2328}}
main{{max-width:440px;margin:8vh auto;background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:28px}}
h1{{font-size:22px;margin:0 0 8px}} p{{margin:0 0 16px;color:#424a53}}
.row{{display:flex;gap:8px;justify-content:flex-end}}
button{{border-radius:8px;padding:8px 14px;font:inherit;cursor:pointer}}
.no{{background:#fff;border:1px solid #d0d7de}} .yes{{background:#1f2328;color:#fff;border:0}}
</style></head><body><main>
<h1>Connect {app_name}</h1>
<p>{who} is about to let this chat app use Frappe. It can only do what this user can already do.</p>
<form method="post" action="/oauth/authorize">{hidden}
<div class="row">
<button class="no" type="submit" name="decision" value="deny">Deny</button>
<button class="yes" type="submit" name="decision" value="allow">Allow</button>
</div></form></main></body></html>"""


def html_page(title: str, message: str) -> str:
	return (
		"<!doctype html><html><head><meta charset='utf-8'><title>"
		+ escape_html(title)
		+ "</title></head><body><h1>"
		+ escape_html(title)
		+ "</h1><p>"
		+ escape_html(message)
		+ "</p></body></html>"
	)


def frappe_response(body: str, status: int, mimetype: str):
	from werkzeug.wrappers import Response

	response = Response(body, status=status, mimetype=mimetype)
	response.headers["Cache-Control"] = "no-store"
	response.headers["Pragma"] = "no-cache"
	return response


def json_response(body: dict, status: int):
	response = frappe_response(json.dumps(body), status, "application/json")
	response.headers["Access-Control-Allow-Origin"] = "*"
	return response


def default_client_html() -> str:
	doc = ensure_default_client()
	if not doc:
		return "<p>OAuth client is not ready. Run bench migrate.</p>"
	secret = ""
	try:
		secret = doc.get_password("client_secret") or ""
	except Exception:
		secret = ""
	client_id = escape_html(doc.client_id)
	safe_secret = escape_html(secret)
	return (
		"<p>ChatGPT can sign in with OAuth and does not need these values. "
		"Paste them into Gemini only if it asks for a client id and secret.</p>"
		"<p><b>Client ID</b></p>"
		f"<pre style='white-space:pre-wrap;word-break:break-all;user-select:all'>{client_id}</pre>"
		"<p><b>Client secret</b></p>"
		f"<pre style='white-space:pre-wrap;word-break:break-all;user-select:all'>{safe_secret}</pre>"
		"<p>Server URL is your public site ending in <b>/mcp</b>. Authentication is OAuth. "
		"Sign in as the Frappe user who should answer.</p>"
	)

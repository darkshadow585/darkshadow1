"""
DarkShadow Stage 3 (Hardened & Fixed): Composio App Integrations Bridge
=======================================================================
Connects Gmail, GitHub, Google Calendar, Slack, Notion, YouTube, Google Drive,
and Linear into DarkShadow's MCPToolRegistry + LangGraph brain with 2-step HITL
safety gates.

Fixes applied:
  1. Parses BOTH standard JSON (`application/json`) AND SSE (`text/event-stream`)
     MCP responses from Composio (fixes silent "No response data received" failure!).
  2. Full MCP Streamable HTTP session support (`initialize` + `Mcp-Session-Id`).
  3. Supports BOTH Consumer Keys (`ck_...` via `x-consumer-api-key`) AND standard
     Composio API Keys (`ak_...` via `x-api-key` or Python `composio` SDK).
  4. Validates `COMPOSIO_API_KEY` upfront and surfaces real HTTP error details.
  5. Inspects inner tool execution results (`results[0].error` / `successful: false`)
     so failed Composio calls NEVER falsely report `ok=True`.
  6. Fixes `list_connected_apps()` for `ck_` keys and `check_or_initiate_connection()`
     so missing OAuth apps actually return an actionable `redirect_url`.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from typing import Any

from config import get_composio_api_key, get_composio_mcp_url
from error_tracker import log_error
from windows_tools import check_hard_shields

HAS_COMPOSIO: bool | None = None


def _check_composio() -> bool:
    global HAS_COMPOSIO
    if HAS_COMPOSIO is None:
        try:
            import composio  # type: ignore  # noqa: F401
            HAS_COMPOSIO = True
        except Exception:
            HAS_COMPOSIO = False
    return HAS_COMPOSIO


_WRITE_ACTION_RE = re.compile(
    r"(SEND|CREATE|DELETE|UPDATE|POST|REPLY|MERGE|CLOSE|INVITE|REMOVE|ARCHIVE|EDIT|MODIFY|WRITE|UPLOAD|SHARE|TRANSFER)",
    re.IGNORECASE,
)

_SLUG_ALIASES: dict[str, str] = {
    "YOUTUBE_SEARCH": "YOUTUBE_SEARCH_YOU_TUBE",
    "YOUTUBE_SEARCH_VIDEOS": "YOUTUBE_SEARCH_YOU_TUBE",
    "GOOGLE_DRIVE_LIST_FILES": "GOOGLEDRIVE_LIST_FILES",
    "GOOGLE_DRIVE_FIND_FILE": "GOOGLEDRIVE_FIND_FILE",
    "GOOGLE_DRIVE_GET_FILE": "GOOGLEDRIVE_GET_FILE",
    "GOOGLE_CALENDAR_LIST_EVENTS": "GOOGLECALENDAR_LIST_EVENTS",
    "GOOGLE_CALENDAR_CREATE_EVENT": "GOOGLECALENDAR_CREATE_EVENT",
}

_PREFIX_NORMALIZERS: tuple[tuple[str, str], ...] = (
    ("GOOGLE_DRIVE_", "GOOGLEDRIVE_"),
    ("GOOGLE_CALENDAR_", "GOOGLECALENDAR_"),
    ("GOOGLE_PHOTOS_", "GOOGLEPHOTOS_"),
    ("GOOGLE_SHEETS_", "GOOGLESHEETS_"),
    ("GOOGLE_DOCS_", "GOOGLEDOCS_"),
    ("GOOGLE_CONTACTS_", "GOOGLECONTACTS_"),
)


def normalize_composio_slug_and_args(action_slug: str, arguments: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Canonicalize common toolkit slug typos and argument aliases in one place."""
    slug = (action_slug or "").strip().upper()
    slug = _SLUG_ALIASES.get(slug, slug)
    for bad_prefix, good_prefix in _PREFIX_NORMALIZERS:
        if slug.startswith(bad_prefix):
            slug = good_prefix + slug[len(bad_prefix):]
            break

    args = dict(arguments or {})
    if "YOUTUBE_SEARCH" in slug:
        if "query" in args and "q" not in args:
            args["q"] = args.pop("query")
        if "search_query" in args and "q" not in args:
            args["q"] = args.pop("search_query")
    return slug, args


def _parse_mcp_http_payload(raw_text: str) -> list[dict[str, Any]]:
    """
    Parse BOTH standard JSON (`application/json`) and SSE (`text/event-stream`)
    MCP Streamable HTTP responses cleanly.
    """
    stripped = (raw_text or "").strip()
    if not stripped:
        return []

    # 1. Standard JSON response (object or JSON-RPC batch array)
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return [parsed]
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except Exception:
            pass

    # 2. Server-Sent Events (SSE) stream (`data: {...}`)
    messages: list[dict[str, Any]] = []
    data_buf: list[str] = []
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if line.startswith("data:"):
            chunk = line[5:].strip()
            if chunk and chunk != "[DONE]":
                data_buf.append(chunk)
        elif not line and data_buf:
            joined = "\n".join(data_buf)
            data_buf.clear()
            try:
                obj = json.loads(joined)
                if isinstance(obj, dict):
                    messages.append(obj)
            except Exception:
                pass

    if data_buf:
        joined = "\n".join(data_buf)
        try:
            obj = json.loads(joined)
            if isinstance(obj, dict):
                messages.append(obj)
        except Exception:
            # Try individual lines if multiple single-line data events had no blank line separator
            for chunk in data_buf:
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict):
                        messages.append(obj)
                except Exception:
                    continue

    return messages


def _extract_mcp_tool_result(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract normalized tool result dict from parsed MCP JSON-RPC response message(s)."""
    for msg in reversed(messages):
        if "error" in msg and isinstance(msg["error"], dict):
            err_obj = msg["error"]
            return {
                "successful": False,
                "error": str(err_obj.get("message") or err_obj),
                "error_code": err_obj.get("code"),
            }
        result = msg.get("result")
        if not isinstance(result, dict):
            continue
        is_err = bool(result.get("isError", False))
        content_items = result.get("content", [])
        if isinstance(content_items, list) and content_items:
            text_parts = [
                str(item.get("text", "")).strip()
                for item in content_items
                if isinstance(item, dict) and item.get("text") is not None
            ]
            combined = "\n".join(p for p in text_parts if p).strip()
            if combined:
                try:
                    parsed = json.loads(combined)
                    if isinstance(parsed, dict):
                        if is_err and "successful" not in parsed:
                            parsed["successful"] = False
                        elif "successful" not in parsed:
                            parsed["successful"] = not bool(parsed.get("error"))
                        return parsed
                    return {"successful": not is_err, "data": parsed}
                except Exception:
                    return {
                        "successful": not is_err,
                        "error": combined if is_err else "",
                        "data": {"text": combined},
                    }
        # Some MCP responses return structuredContent directly
        if "structuredContent" in result and isinstance(result["structuredContent"], dict):
            sc = dict(result["structuredContent"])
            sc.setdefault("successful", not is_err)
            return sc
        return {"successful": not is_err, "data": result}

    return {"successful": False, "error": "No valid JSON-RPC response received from Composio MCP"}


class ComposioAppBridge:
    """Safe wrapper over Composio toolkits with Captain HITL gating on write actions."""

    def __init__(self, entity_id: str = "captain_kuldeep") -> None:
        self.entity_id = os.getenv("COMPOSIO_ENTITY_ID", entity_id)
        self._client: Any = None
        self._mcp_session_id: str = ""
        self._mcp_lock = threading.Lock()
        self._req_id = 0

    def _get_api_key(self) -> str:
        return get_composio_api_key()

    def _is_consumer_key(self, api_key: str) -> bool:
        return api_key.startswith("ck_")

    def _next_id(self) -> int:
        with self._mcp_lock:
            self._req_id += 1
            return self._req_id

    def _build_mcp_headers(self, api_key: str, include_session: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "DarkShadow-Desktop/2.1",
        }
        if self._is_consumer_key(api_key):
            headers["x-consumer-api-key"] = api_key
        else:
            headers["x-api-key"] = api_key
        if include_session and self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        return headers

    def _post_mcp(self, payload: dict[str, Any], api_key: str, timeout: float = 25.0) -> tuple[str, dict[str, str]]:
        url = get_composio_mcp_url()
        headers = self._build_mcp_headers(api_key, include_session=True)
        req = urllib.request.Request(
            url,
            headers=headers,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                sid = resp_headers.get("mcp-session-id", "").strip()
                if sid:
                    with self._mcp_lock:
                        self._mcp_session_id = sid
                return resp.read().decode("utf-8", errors="replace"), resp_headers
        except urllib.error.HTTPError as http_err:
            err_body = ""
            try:
                err_body = http_err.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(f"Composio HTTP {http_err.code}: {err_body or http_err.reason}") from http_err

    def _ensure_mcp_session(self, api_key: str) -> None:
        """Perform lightweight MCP Streamable HTTP initialize handshake once per bridge lifecycle."""
        if self._mcp_session_id:
            return
        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "darkshadow-desktop", "version": "2.1.0"},
            },
        }
        try:
            self._post_mcp(init_payload, api_key, timeout=12.0)
            if self._mcp_session_id:
                try:
                    self._post_mcp(
                        {"jsonrpc": "2.0", "method": "notifications/initialized"},
                        api_key,
                        timeout=6.0,
                    )
                except Exception:
                    pass
        except Exception:
            # Stateless Composio MCP endpoints accept direct tools/call without initialize
            pass

    def _ensure_client(self) -> Any:
        if not _check_composio():
            raise RuntimeError("Install composio: pip install composio composio-langgraph")
        if self._client is None:
            from composio import Composio  # type: ignore

            api_key = self._get_api_key()
            if not api_key:
                raise RuntimeError("COMPOSIO_API_KEY missing in .env")
            if self._is_consumer_key(api_key):
                raise RuntimeError(
                    "COMPOSIO_API_KEY is a consumer key (ck_...), which uses Composio Connect MCP instead of the Python SDK."
                )
            self._client = Composio(api_key=api_key)
        return self._client

    def health_check(self) -> dict[str, Any]:
        """Diagnostic check for Composio configuration, key type, and connectivity."""
        api_key = self._get_api_key()
        if not api_key:
            return {
                "ok": False,
                "error_code": "MISSING_API_KEY",
                "message": "COMPOSIO_API_KEY .env mein set nahi hai.",
            }
        mode = "mcp_consumer_key" if self._is_consumer_key(api_key) else "sdk_or_api_key"
        conn = self.list_connected_apps()
        return {
            "ok": bool(conn.get("ok")),
            "mode": mode,
            "mcp_url": get_composio_mcp_url(),
            "entity_id": self.entity_id,
            "sdk_installed": _check_composio(),
            "connections": conn.get("connections", []),
            "message": conn.get("message", "Composio ready." if conn.get("ok") else "Composio check failed."),
        }

    def list_connected_apps(self) -> dict[str, Any]:
        api_key = self._get_api_key()
        if not api_key:
            return {"ok": False, "error_code": "MISSING_API_KEY", "message": "COMPOSIO_API_KEY missing in .env"}

        # Consumer keys (ck_...) MUST use MCP rather than Python SDK
        if self._is_consumer_key(api_key) or not _check_composio():
            try:
                res = self._call_mcp_direct(
                    "COMPOSIO_MANAGE_CONNECTIONS",
                    {"toolkits": ["GMAIL", "GITHUB", "GOOGLECALENDAR", "SLACK", "NOTION", "GOOGLEDRIVE", "YOUTUBE"]},
                )
                if not res.get("successful"):
                    return {
                        "ok": False,
                        "error_code": "COMPOSIO_MCP_ERROR",
                        "message": str(res.get("error") or "Unable to fetch Composio connections via MCP."),
                    }
                raw_results = res.get("data", {}).get("results", res.get("data", {}))
                items: list[dict[str, Any]] = []
                if isinstance(raw_results, dict):
                    for tk, info in raw_results.items():
                        if isinstance(info, dict):
                            items.append(
                                {
                                    "app": str(tk),
                                    "status": str(info.get("status", "UNKNOWN")),
                                    "redirect_url": info.get("redirect_url"),
                                }
                            )
                elif isinstance(raw_results, list):
                    for info in raw_results:
                        if isinstance(info, dict):
                            items.append(
                                {
                                    "app": str(info.get("toolkit") or info.get("app") or "unknown"),
                                    "status": str(info.get("status", "UNKNOWN")),
                                    "redirect_url": info.get("redirect_url"),
                                }
                            )
                return {"ok": True, "mode": "mcp", "count": len(items), "connections": items}
            except Exception as exc:
                return {"ok": False, "error_code": "COMPOSIO_UNAVAILABLE", "message": str(exc)}

        try:
            client = self._ensure_client()
            accounts = client.connected_accounts.list(user_ids=[self.entity_id])
            items = [
                {
                    "app": (
                        getattr(acc, "toolkit", {}).get("slug", "unknown")
                        if isinstance(getattr(acc, "toolkit", None), dict)
                        else str(getattr(acc, "appName", getattr(getattr(acc, "toolkit", None), "slug", "app")))
                    ),
                    "status": str(getattr(acc, "status", "UNKNOWN")),
                    "id": str(getattr(acc, "id", "")),
                }
                for acc in getattr(accounts, "items", accounts) or []
            ]
            return {"ok": True, "mode": "sdk", "count": len(items), "connections": items}
        except Exception as exc:
            return {"ok": False, "error_code": "COMPOSIO_UNAVAILABLE", "message": str(exc)}

    def get_langgraph_tools(self, toolkits: list[str] | None = None) -> list[Any]:
        """Load Composio tool definitions formatted for LangGraph ToolNode / Gemini."""
        try:
            client = self._ensure_client()
            kits = toolkits or ["GMAIL", "GITHUB", "GOOGLECALENDAR", "SLACK", "NOTION"]
            return list(client.tools.get(user_id=self.entity_id, toolkits=kits))
        except Exception as exc:
            log_error("composio_bridge", f"Tool load failed: {exc}", exception=exc)
            return []

    def _call_mcp_direct(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Direct helper to call Composio MCP tools with Streamable HTTP JSON+SSE + session retry."""
        api_key = self._get_api_key()
        if not api_key:
            return {"successful": False, "error": "COMPOSIO_API_KEY missing in .env"}

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            raw, _ = self._post_mcp(payload, api_key, timeout=25.0)
        except RuntimeError as first_err:
            # Retry once with fresh MCP session initialization if session expired/required
            if any(tok in str(first_err).lower() for tok in ("session", "400", "404", "initialize")):
                with self._mcp_lock:
                    self._mcp_session_id = ""
                self._ensure_mcp_session(api_key)
                raw, _ = self._post_mcp(payload, api_key, timeout=25.0)
            else:
                raise

        messages = _parse_mcp_http_payload(raw)
        return _extract_mcp_tool_result(messages)

    def search_tools(self, query: str) -> dict[str, Any]:
        """Search Composio tool catalog to find exact slug and schemas for an app/task."""
        try:
            return self._call_mcp_direct("COMPOSIO_SEARCH_TOOLS", {"query": query})
        except Exception as exc:
            return {"successful": False, "error": str(exc)}

    def check_or_initiate_connection(self, toolkit: str) -> dict[str, Any]:
        """Check status of a toolkit and generate an OAuth auth redirect link if not connected."""
        tk = (toolkit or "").strip().upper()
        if not tk:
            return {"successful": False, "error": "toolkit is required"}
        try:
            # Calling COMPOSIO_MANAGE_CONNECTIONS with toolkits checks active status AND creates a redirect_url if needed
            res = self._call_mcp_direct("COMPOSIO_MANAGE_CONNECTIONS", {"toolkits": [tk]})
            if res.get("successful"):
                return res
            # Fallback to explicit initiate/list payload variants
            return self._call_mcp_direct("COMPOSIO_MANAGE_CONNECTIONS", {"action": "initiate", "toolkits": [tk]})
        except Exception as exc:
            return {"successful": False, "error": str(exc)}

    def get_tool_schema(self, tool_slugs: list[str]) -> dict[str, Any]:
        """Retrieve exact parameter definitions and requirements for tool slugs."""
        try:
            return self._call_mcp_direct("COMPOSIO_GET_TOOL_SCHEMAS", {"tool_slugs": tool_slugs})
        except Exception as exc:
            return {"successful": False, "error": str(exc)}

    def _execute_via_mcp(self, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute action via Composio MCP HTTP endpoint (supports both JSON & SSE responses)."""
        target_slug, args_payload = normalize_composio_slug_and_args(slug, arguments)

        def _invoke_multi(tool_slug: str, tool_args: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            parsed_data = self._call_mcp_direct(
                "COMPOSIO_MULTI_EXECUTE_TOOL",
                {
                    "tools": [
                        {
                            "tool_slug": tool_slug,
                            "arguments": tool_args,
                        }
                    ]
                },
            )
            if not isinstance(parsed_data, dict):
                return None, {"successful": False, "error": "Unexpected non-dict MCP response"}

            data_block = parsed_data.get("data")
            results_list = data_block.get("results", []) if isinstance(data_block, dict) else []

            if results_list and isinstance(results_list, list):
                first = results_list[0]
                if isinstance(first, dict):
                    resp_obj = first.get("response") if isinstance(first.get("response"), dict) else {}
                    inner_failed = (
                        first.get("successful") is False
                        or resp_obj.get("successful") is False
                        or bool(first.get("error"))
                        or bool(first.get("not_found_message"))
                        or bool(resp_obj.get("error"))
                    )
                    if inner_failed:
                        return None, parsed_data
                    if parsed_data.get("successful", True):
                        return resp_obj.get("data", first), None

            if parsed_data.get("successful"):
                return (data_block if isinstance(data_block, dict) else {"value": data_block}), None

            return None, parsed_data

        result_data, err_parsed = _invoke_multi(target_slug, args_payload)
        if result_data is not None:
            return result_data

        if err_parsed:
            data_block = err_parsed.get("data") if isinstance(err_parsed.get("data"), dict) else {}
            results_arr = data_block.get("results", [])
            if isinstance(results_arr, list) and results_arr and isinstance(results_arr[0], dict):
                first_res = results_arr[0]
                suggestions = first_res.get("suggestions")
                if isinstance(suggestions, list) and suggestions:
                    retry_slug = str(suggestions[0]).strip().upper()
                    if retry_slug and retry_slug != target_slug:
                        retried_data, retry_err = _invoke_multi(retry_slug, args_payload)
                        if retried_data is not None:
                            return retried_data
                        if retry_err:
                            err_parsed = retry_err

                resp_obj = first_res.get("response") if isinstance(first_res.get("response"), dict) else {}
                resp_data = resp_obj.get("data") if isinstance(resp_obj.get("data"), dict) else {}
                detailed_err = (
                    first_res.get("not_found_message")
                    or first_res.get("error")
                    or resp_obj.get("error")
                    or resp_data.get("message")
                    or resp_data.get("error")
                )
                if detailed_err:
                    raise RuntimeError(str(detailed_err))

            raise RuntimeError(str(err_parsed.get("error") or "Composio MCP execution failed"))

        raise RuntimeError("Composio MCP returned no data")

    def _execute_via_sdk(self, slug: str, arguments: dict[str, Any]) -> Any:
        """Execute action via Python `composio` SDK with cross-version signature compatibility."""
        client = self._ensure_client()
        try:
            return client.tools.execute(slug=slug, user_id=self.entity_id, arguments=arguments)
        except TypeError:
            # Older/alternate SDK signature fallback
            return client.tools.execute(action=slug, params=arguments, entity_id=self.entity_id)

    def execute_action(
        self,
        action_slug: str,
        arguments: dict[str, Any] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Execute a Composio app action, gating mutating writes behind explicit confirmation."""
        slug, args = normalize_composio_slug_and_args(action_slug, arguments)
        if not slug:
            return {"ok": False, "error_code": "INVALID_ARGS", "message": "action_slug required (e.g. GMAIL_FETCH_EMAILS)."}

        shield = check_hard_shields(f"{slug} {args}")
        if shield:
            return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield}

        api_key = self._get_api_key()
        if not api_key:
            return {
                "ok": False,
                "error_code": "MISSING_API_KEY",
                "message": "Captain, .env file mein COMPOSIO_API_KEY set kijiye (Composio dashboard se key generate karein).",
            }

        if _WRITE_ACTION_RE.search(slug) and not slug.startswith("COMPOSIO_") and not confirmed:
            return {
                "ok": False,
                "needs_confirmation": True,
                "preview": {"action": slug, "arguments": args},
                "message": f"Captain, external app action '{slug}' ke liye confirmation chahiye. Confirm karne par execute karoon?",
            }

        try:
            if slug.startswith("COMPOSIO_"):
                res_meta = self._call_mcp_direct(slug, args)
                if res_meta.get("successful"):
                    return {
                        "ok": True,
                        "verified_state": "composio_meta_executed",
                        "action": slug,
                        "result": res_meta.get("data", {}),
                        "message": f"Composio meta-action '{slug}' successfully executed.",
                    }
                raise RuntimeError(str(res_meta.get("error") or "Meta-tool execution failed"))

            if self._is_consumer_key(api_key) or not _check_composio():
                result = self._execute_via_mcp(slug=slug, arguments=args)
            else:
                result = self._execute_via_sdk(slug=slug, arguments=args)

            return {
                "ok": True,
                "verified_state": "composio_executed",
                "action": slug,
                "result": result,
                "message": f"Composio action '{slug}' successfully execute ho gaya.",
            }
        except Exception as exc:
            err_msg = str(exc)
            toolkit_guess = slug.split("_")[0]
            redirect_url = None

            # Detect missing connection or auth requirements
            if any(k in err_msg.lower() for k in ("connection", "auth", "not connected", "unauthorized", "login", "account", "oauth")):
                try:
                    conn_res = self.check_or_initiate_connection(toolkit_guess)
                    if conn_res.get("successful"):
                        res_data = conn_res.get("data", {})
                        res_dict = res_data.get("results", res_data) if isinstance(res_data, dict) else {}
                        if isinstance(res_dict, dict):
                            t_data = (
                                res_dict.get(toolkit_guess)
                                or res_dict.get(toolkit_guess.lower())
                                or next((v for v in res_dict.values() if isinstance(v, dict) and v.get("redirect_url")), {})
                            )
                            if isinstance(t_data, dict):
                                redirect_url = t_data.get("redirect_url") or t_data.get("auth_url")
                except Exception:
                    pass

            if redirect_url:
                log_error(
                    "composio_bridge",
                    f"Action '{slug}' requires authentication: {redirect_url}",
                    command_or_context=f"{slug} {args}",
                    suggested_fix=f"Ask user to connect app via: {redirect_url}",
                    status="FIXED",
                )
                return {
                    "ok": False,
                    "error_code": "AUTH_REQUIRED",
                    "redirect_url": redirect_url,
                    "toolkit": toolkit_guess,
                    "message": f"App '{toolkit_guess}' ka active connection nahi mila ya authentication pending hai. Kripya is link par jaakar allow karein: {redirect_url}",
                }

            log_error("composio_bridge", f"execute_action({slug}) failed: {exc}", command_or_context=f"{slug} {args}", exception=exc)
            return {"ok": False, "error_code": "COMPOSIO_ERROR", "message": f"Composio failed: {exc}"}


COMPOSIO_BRIDGE = ComposioAppBridge()

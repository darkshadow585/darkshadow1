"""
DarkShadow Stage 3: Composio App Integrations Bridge
=====================================================
Connects Gmail, GitHub, Google Calendar, Slack, Notion, and Linear into
DarkShadow's MCPToolRegistry + LangGraph brain with 2-step HITL safety gates.

Install:
  pip install composio composio-langgraph
Set in .env:
  COMPOSIO_API_KEY=your_composio_key
"""

from __future__ import annotations

import os
import re
from typing import Any

from error_tracker import log_error
from windows_tools import check_hard_shields

HAS_COMPOSIO: bool | None = None

def _check_composio() -> bool:
    global HAS_COMPOSIO
    if HAS_COMPOSIO is None:
        try:
            import composio  # type: ignore
            HAS_COMPOSIO = True
        except Exception:
            HAS_COMPOSIO = False
    return HAS_COMPOSIO

_WRITE_ACTION_RE = re.compile(
    r"(SEND|CREATE|DELETE|UPDATE|POST|REPLY|MERGE|CLOSE|INVITE|REMOVE|ARCHIVE)",
    re.IGNORECASE,
)


class ComposioAppBridge:
    """Safe wrapper over Composio toolkits with Captain HITL gating on write actions."""

    def __init__(self, entity_id: str = "captain_kuldeep") -> None:
        self.entity_id = os.getenv("COMPOSIO_ENTITY_ID", entity_id)
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if not _check_composio():
            raise RuntimeError("Install composio: pip install composio composio-langgraph")
        if self._client is None:
            from composio import Composio
            api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("COMPOSIO_API_KEY missing in .env")
            self._client = Composio(api_key=api_key)
        return self._client

    def list_connected_apps(self) -> dict[str, Any]:
        try:
            client = self._ensure_client()
            accounts = client.connected_accounts.list(user_ids=[self.entity_id])
            items = [
                {
                    "app": getattr(acc, "toolkit", {}).get("slug", "unknown") if isinstance(getattr(acc, "toolkit", None), dict) else str(getattr(acc, "appName", "app")),
                    "status": str(getattr(acc, "status", "UNKNOWN")),
                    "id": str(getattr(acc, "id", "")),
                }
                for acc in getattr(accounts, "items", accounts) or []
            ]
            return {"ok": True, "count": len(items), "connections": items}
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
        """Direct helper to call Composio built-in MCP meta-tools (SEARCH_TOOLS, MANAGE_CONNECTIONS, GET_TOOL_SCHEMAS)."""
        import json
        import urllib.request
        api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
        url = "https://connect.composio.dev/mcp"
        headers = {
            "x-consumer-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        req = urllib.request.Request(url, headers=headers, data=json.dumps(payload).encode("utf-8"), method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8")
        for line in raw.split("\n"):
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except Exception:
                    continue
                items = msg.get("result", {}).get("content", [])
                if items and isinstance(items[0], dict):
                    txt = str(items[0].get("text", "{}")).strip()
                    try:
                        return json.loads(txt)
                    except Exception:
                        is_err = bool(msg.get("result", {}).get("isError", False)) or "error" in txt.lower()
                        return {"successful": not is_err, "error": txt, "data": {"text": txt}}
        return {"successful": False, "error": "No response data received from Composio MCP"}

    def search_tools(self, query: str) -> dict[str, Any]:
        """Search Composio tool catalog to find exact slug and schemas for an app/task."""
        try:
            return self._call_mcp_direct("COMPOSIO_SEARCH_TOOLS", {"query": query})
        except Exception as exc:
            return {"successful": False, "error": str(exc)}

    def check_or_initiate_connection(self, toolkit: str) -> dict[str, Any]:
        """Check status of a toolkit or generate an auth redirect link for connecting it."""
        try:
            tk = (toolkit or "").strip().upper()
            return self._call_mcp_direct("COMPOSIO_MANAGE_CONNECTIONS", {"action": "list", "toolkits": [tk]})
        except Exception as exc:
            return {"successful": False, "error": str(exc)}

    def get_tool_schema(self, tool_slugs: list[str]) -> dict[str, Any]:
        """Retrieve exact parameter definitions and requirements for tool slugs."""
        try:
            return self._call_mcp_direct("COMPOSIO_GET_TOOL_SCHEMAS", {"tool_slugs": tool_slugs})
        except Exception as exc:
            return {"successful": False, "error": str(exc)}

    def _execute_via_mcp(self, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute action via Composio MCP HTTP endpoint using consumer key (ck_...)."""
        import json
        import urllib.request
        api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
        url = "https://connect.composio.dev/mcp"
        headers = {
            "x-consumer-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # Normalize tool slug aliases
        aliases = {
            "YOUTUBE_SEARCH": "YOUTUBE_SEARCH_YOU_TUBE",
            "YOUTUBE_SEARCH_VIDEOS": "YOUTUBE_SEARCH_YOU_TUBE",
            "GOOGLE_DRIVE_LIST_FILES": "GOOGLEDRIVE_LIST_FILES",
            "GOOGLE_DRIVE_FIND_FILE": "GOOGLEDRIVE_FIND_FILE",
            "GOOGLE_DRIVE_GET_FILE": "GOOGLEDRIVE_GET_FILE",
            "GOOGLE_CALENDAR_LIST_EVENTS": "GOOGLECALENDAR_LIST_EVENTS",
        }
        target_slug = aliases.get(slug, slug)
        if target_slug.startswith("GOOGLE_DRIVE_"):
            target_slug = target_slug.replace("GOOGLE_DRIVE_", "GOOGLEDRIVE_")
        elif target_slug.startswith("GOOGLE_CALENDAR_"):
            target_slug = target_slug.replace("GOOGLE_CALENDAR_", "GOOGLECALENDAR_")
        elif target_slug.startswith("GOOGLE_PHOTOS_"):
            target_slug = target_slug.replace("GOOGLE_PHOTOS_", "GOOGLEPHOTOS_")
        elif target_slug.startswith("GOOGLE_SHEETS_"):
            target_slug = target_slug.replace("GOOGLE_SHEETS_", "GOOGLESHEETS_")
        elif target_slug.startswith("GOOGLE_DOCS_"):
            target_slug = target_slug.replace("GOOGLE_DOCS_", "GOOGLEDOCS_")
        elif target_slug.startswith("GOOGLE_CONTACTS_"):
            target_slug = target_slug.replace("GOOGLE_CONTACTS_", "GOOGLECONTACTS_")

        args_payload = dict(arguments or {})
        if "YOUTUBE_SEARCH" in target_slug:
            if "query" in args_payload and "q" not in args_payload:
                args_payload["q"] = args_payload.pop("query")
            if "search_query" in args_payload and "q" not in args_payload:
                args_payload["q"] = args_payload.pop("search_query")

        def _call_composio(tool_slug: str, tool_args: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "COMPOSIO_MULTI_EXECUTE_TOOL",
                    "arguments": {
                        "tools": [
                            {
                                "tool_slug": tool_slug,
                                "arguments": tool_args,
                            }
                        ]
                    },
                },
            }
            req = urllib.request.Request(url, headers=headers, data=json.dumps(payload).encode("utf-8"), method="POST")
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw_text = resp.read().decode("utf-8")
            for line in raw_text.split("\n"):
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    content_items = msg.get("result", {}).get("content", [])
                    if content_items and isinstance(content_items[0], dict):
                        inner_text = content_items[0].get("text", "{}")
                        try:
                            parsed_data = json.loads(inner_text)
                        except Exception:
                            parsed_data = {"successful": False, "error": inner_text}
                        if parsed_data.get("successful"):
                            r_list = parsed_data.get("data", {}).get("results", [])
                            if r_list:
                                return r_list[0].get("response", {}).get("data", r_list[0]), None, None
                            return parsed_data.get("data", {}), None, None
                        return None, parsed_data, None
            return None, None, raw_text

        result_data, err_parsed, raw_output = _call_composio(target_slug, args_payload)
        if result_data is not None:
            return result_data

        # If call failed, check for suggestions or fallback
        if err_parsed:
            results_arr = err_parsed.get("data", {}).get("results", [])
            if results_arr and isinstance(results_arr, list) and len(results_arr) > 0:
                first_res = results_arr[0]
                suggestions = first_res.get("suggestions")
                if suggestions and isinstance(suggestions, list) and suggestions:
                    retry_slug = str(suggestions[0])
                    retried_data, retry_err, _ = _call_composio(retry_slug, args_payload)
                    if retried_data is not None:
                        return retried_data

                detailed_err = (
                    first_res.get("not_found_message")
                    or first_res.get("error")
                    or first_res.get("response", {}).get("error")
                    or first_res.get("response", {}).get("data", {}).get("message")
                )
                if detailed_err:
                    raise RuntimeError(detailed_err)

            raise RuntimeError(err_parsed.get("error") or "Composio MCP execution failed")

        return {"raw": raw_output}

    def execute_action(
        self,
        action_slug: str,
        arguments: dict[str, Any] | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Execute a Composio app action, gating mutating writes behind explicit confirmation."""
        slug = (action_slug or "").strip().upper()
        if slug in ("YOUTUBE_SEARCH", "YOUTUBE_SEARCH_VIDEOS"):
            slug = "YOUTUBE_SEARCH_YOU_TUBE"

        args = dict(arguments or {})
        if "YOUTUBE_SEARCH" in slug:
            if "query" in args and "q" not in args:
                args["q"] = args.pop("query")
            if "search_query" in args and "q" not in args:
                args["q"] = args.pop("search_query")
        if not slug:
            return {"ok": False, "error_code": "INVALID_ARGS", "message": "action_slug required (e.g. GMAIL_FETCH_EMAILS)."}

        shield = check_hard_shields(f"{slug} {args}")
        if shield:
            return {"ok": False, "error_code": "SHIELD_BLOCKED", "message": shield}

        if _WRITE_ACTION_RE.search(slug) and not confirmed:
            return {
                "ok": False,
                "needs_confirmation": True,
                "preview": {"action": slug, "arguments": args},
                "message": f"Captain, external app action '{slug}' ke liye confirmation chahiye. Confirm karne par execute karoon?",
            }

        try:
            api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
            if slug.startswith("COMPOSIO_"):
                res_meta = self._call_mcp_direct(slug, args)
                if res_meta.get("successful"):
                    return {
                        "ok": True,
                        "action": slug,
                        "result": res_meta.get("data", {}),
                        "message": f"Composio meta-action '{slug}' successfully executed.",
                    }
                raise RuntimeError(res_meta.get("error") or "Meta-tool execution failed")

            if api_key.startswith("ck_"):
                result = self._execute_via_mcp(slug=slug, arguments=args)
            else:
                client = self._ensure_client()
                result = client.tools.execute(slug=slug, user_id=self.entity_id, arguments=args)
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
            if any(k in err_msg.lower() for k in ("connection", "auth", "not connected", "unauthorized", "login")):
                try:
                    conn_res = self.check_or_initiate_connection(toolkit_guess)
                    if conn_res.get("successful"):
                        res_dict = conn_res.get("data", {}).get("results", {})
                        t_data = res_dict.get(toolkit_guess) or res_dict.get(toolkit_guess.lower()) or {}
                        redirect_url = t_data.get("redirect_url")
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

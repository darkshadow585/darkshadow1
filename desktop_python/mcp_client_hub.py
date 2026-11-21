"""
D-1 (Fixed): Universal Model Context Protocol (MCP) Client Hub with Persistent Session Pool
===========================================================================================
Fixes applied:
  - Persistent background event-loop & reusable MCP stdio sessions (5x-10x faster — NO respawning
    `npx -y @playwright/mcp@latest` on every single click!).
  - Auto-resolves Windows executables (`npx` -> `npx.cmd`, `uvx` -> `uvx.exe`) via shutil.which().
  - Unified check_hard_shields() from windows_tools.py (blocks payments, OTP, camera, dangerous shell).
  - Enforces strict timeout on BOTH running-loop and non-loop callers via asyncio.wait_for().
  - Clean shutdown() method called from darkshadow_desktop._quit_app() (zero zombie Node/uvx processes!).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from error_tracker import log_error
from windows_tools import check_hard_shields

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "mcp_servers.json"


class _PersistentMCPWorker:
    """Dedicated background asyncio thread holding persistent MCP stdio sessions cleanly."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="darkshadow-mcp-pool")
        self._sessions: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._started = False
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Any, timeout: float = 60.0) -> Any:
        self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(asyncio.wait_for(coro, timeout=timeout), self._loop)
        return future.result(timeout=timeout + 2.0)

    async def get_session(self, server_name: str, cfg: dict[str, Any]) -> Any:
        if server_name in self._sessions:
            return self._sessions[server_name]

        from mcp import ClientSession, StdioServerParameters  # type: ignore
        from mcp.client.stdio import stdio_client  # type: ignore

        raw_cmd = str(cfg["command"])
        resolved_cmd = shutil.which(raw_cmd) or raw_cmd

        params = StdioServerParameters(
            command=resolved_cmd,
            args=[str(a) for a in cfg.get("args", [])],
            env={**os.environ, **{str(k): str(v) for k, v in (cfg.get("env") or {}).items()}},
        )

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()
            self._stacks[server_name] = stack
            self._sessions[server_name] = session
            return session
        except Exception:
            await stack.aclose()
            raise

    async def drop_session(self, server_name: str) -> None:
        self._sessions.pop(server_name, None)
        stack = self._stacks.pop(server_name, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:
                pass

    async def close_all_async(self) -> None:
        for name in list(self._stacks.keys()):
            await self.drop_session(name)

    def shutdown(self) -> None:
        if not self._started or self._loop.is_closed():
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.close_all_async(), self._loop)
            fut.result(timeout=5.0)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


class MCPClientHub:
    """Universal MCP Client Manager with persistent session pooling and unified Safety Shield."""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._tool_cache: dict[str, list[dict[str, Any]]] = {}
        self._worker = _PersistentMCPWorker()

    def load_config(self) -> dict[str, dict[str, Any]]:
        if not self.config_path.exists():
            return {}
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            servers = raw.get("mcpServers", {})
            if isinstance(servers, dict):
                return servers
        except Exception as exc:
            log_error("mcp_client_hub", f"Failed to parse {self.config_path}: {exc}")
        return {}

    def list_configured_servers(self) -> dict[str, Any]:
        servers = self.load_config()
        summary = [
            {
                "name": name,
                "enabled": bool(cfg.get("enabled", False)),
                "command": cfg.get("command", ""),
                "connected": name in self._worker._sessions,
                "description": cfg.get("description", ""),
            }
            for name, cfg in servers.items()
        ]
        return {
            "ok": True,
            "config_path": str(self.config_path),
            "servers": summary,
            "message": f"{len(summary)} MCP servers configured ({sum(1 for s in summary if s['enabled'])} enabled).",
        }

    def _is_sdk_installed(self) -> bool:
        try:
            import mcp  # noqa: F401
            return True
        except Exception:
            return False

    def _get_enabled_server(self, server_name: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not self._is_sdk_installed():
            return None, {
                "ok": False,
                "message": "Official `mcp` SDK not installed. Run `pip install mcp`.",
            }
        servers = self.load_config()
        cfg = servers.get(server_name)
        if not cfg:
            return None, {"ok": False, "message": f"MCP server '{server_name}' not found in mcp_servers.json."}
        if not cfg.get("enabled", False):
            return None, {
                "ok": False,
                "message": f"MCP server '{server_name}' is disabled in mcp_servers.json. Set enabled: true to activate.",
            }
        return cfg, None

    async def _discover_tools_coro(self, server_name: str, cfg: dict[str, Any]) -> dict[str, Any]:
        try:
            session = await self._worker.get_session(server_name, cfg)
            result = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": (t.description or "")[:180],
                    "inputSchema": getattr(t, "inputSchema", {}),
                }
                for t in (result.tools or [])
            ]
            self._tool_cache[server_name] = tools
            return {
                "ok": True,
                "server": server_name,
                "tool_count": len(tools),
                "tools": tools,
                "message": f"Discovered {len(tools)} tools on MCP server '{server_name}'.",
            }
        except Exception as exc:
            await self._worker.drop_session(server_name)
            log_error("mcp_client_hub", f"discover_tools({server_name}) failed: {exc}", exception=exc)
            return {"ok": False, "server": server_name, "message": f"MCP discovery failed: {exc}"}

    async def _call_tool_coro(
        self,
        server_name: str,
        cfg: dict[str, Any],
        tool_name: str,
        args_payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            session = await self._worker.get_session(server_name, cfg)
            res = await session.call_tool(tool_name, arguments=args_payload)
            text_parts: list[str] = []
            for item in getattr(res, "content", []) or []:
                text = getattr(item, "text", None)
                if text:
                    text_parts.append(str(text))
            output = "\n".join(text_parts).strip()
            is_err = bool(getattr(res, "isError", False))
            return {
                "ok": not is_err,
                "server": server_name,
                "tool": tool_name,
                "output": output[:3000],
                "message": output[:400] or f"Executed {server_name}.{tool_name}.",
            }
        except Exception as exc:
            await self._worker.drop_session(server_name)
            log_error("mcp_client_hub", f"call_tool({server_name}.{tool_name}) failed: {exc}", exception=exc)
            return {
                "ok": False,
                "server": server_name,
                "tool": tool_name,
                "message": f"MCP call error: {exc}",
            }

    def discover_tools(self, server_name: str, timeout: float = 45.0) -> dict[str, Any]:
        cfg, err = self._get_enabled_server(server_name)
        if err or cfg is None:
            return err or {"ok": False, "message": "Invalid server config."}
        try:
            return self._worker.submit(self._discover_tools_coro(server_name, cfg), timeout=timeout)
        except Exception as exc:
            return {"ok": False, "server": server_name, "message": f"MCP discovery timed out/failed: {exc}"}

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        args_payload = arguments or {}
        serialized = f"{tool_name} {json.dumps(args_payload, ensure_ascii=False)}"
        shield = check_hard_shields(serialized)
        if shield:
            return {"ok": False, "blocked": True, "error_code": "SHIELD_BLOCKED", "message": shield}

        cfg, err = self._get_enabled_server(server_name)
        if err or cfg is None:
            return err or {"ok": False, "message": "Invalid server config."}
        try:
            return self._worker.submit(
                self._call_tool_coro(server_name, cfg, tool_name, args_payload),
                timeout=timeout,
            )
        except Exception as exc:
            return {"ok": False, "server": server_name, "tool": tool_name, "message": f"MCP call timed out/failed: {exc}"}

    def shutdown(self) -> None:
        self._worker.shutdown()


MCP_HUB = MCPClientHub()

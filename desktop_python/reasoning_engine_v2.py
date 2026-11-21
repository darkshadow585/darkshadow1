"""
DarkShadow Stage 5 Complete Engine: Decision-1 Router + LangGraph Plan-Verify-Replan
====================================================================================
Drop-in upgrade for `reasoning_engine.py` integrating ALL 4 requested technologies + Decision-1:
  - Stage 1: Playwright MCP (via MCP_HUB.call_tool("playwright", ...) & Edge CDP)
  - Stage 2: Windows-MCP (via MCP_HUB.call_tool("windows", ...) & WINDOWS_UIA_AGENT)
  - Stage 3: Composio (via COMPOSIO_BRIDGE.execute_action(...))
  - Stage 5: LangGraph StateGraph (route_entry -> plan -> decide -> safety_gate -> execute -> verify -> replan -> synthesize)
  - Brain Gate: `gemini-decision-1` decides command routing AND verifies every step outcome!
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, ValidationError

from autonomous_web_agent import AUTONOMOUS_WEB_AGENT, EDGE_AGENT
from composio_bridge import COMPOSIO_BRIDGE
from config import CHECKPOINT_DB_PATH, get_api_key, get_fast_model, get_reasoning_model, is_gemini_4_model
from decision_verifier import route_command_with_decision_1, verify_react_step_with_decision_1
from error_tracker import log_error
from instant_router import RATE_SHIELD
from living_memory_v3 import LIVING_MEMORY
from mcp_client_hub import MCP_HUB
from windows_tools import (
    check_hard_shields,
    get_system_health,
    open_allowlisted_app,
    set_monitor_brightness,
    set_system_volume,
)
from windows_uia_agent import WINDOWS_UIA_AGENT

ToolCategory = Literal[
    "playwright_mcp",
    "windows_mcp",
    "composio_action",
    "web_autonomous",
    "web_a11y_snapshot",
    "windows_uia_inspect",
    "windows_uia_click",
    "windows_uia_type",
    "windows_app_open",
    "windows_system",
    "memory_update",
    "memory_recall",
    "final_answer",
]


class PlanDraft(BaseModel):
    milestones: list[str] = Field(..., min_length=1, max_length=6)
    success_criteria: str = Field(..., min_length=4)


class NextActionDecision(BaseModel):
    thought: str = Field(..., min_length=2)
    tool: ToolCategory
    args_json: str = Field(default="{}")
    requires_confirmation: bool = Field(default=False)
    final_response: str = Field(default="")


class HierarchicalGraphState(TypedDict):
    goal: str
    context: str
    route_decision: dict[str, Any]
    milestones: list[str]
    current_milestone_idx: int
    success_criteria: str
    step_count: int
    next_action: dict[str, Any]
    step_logs: list[dict[str, Any]]
    last_verification: dict[str, Any]
    replan_count: int
    approved: bool
    hitl_confirmed: bool
    done: bool
    final_answer: str


_SENSITIVE_STEP_RE = re.compile(
    r"\b(delete|remove|format|send_whatsapp|send_email|gmail_send|create_issue|shutdown|restart|kill|terminate|rm\s+-rf)\b",
    re.IGNORECASE,
)
_COMPOSIO_MUTATING_RE = re.compile(
    r"(?:^|_)(?:SEND|CREATE|DELETE|REMOVE|UPDATE|PATCH|PUT|POST|REPLY|MERGE|CLOSE|INVITE|ARCHIVE|TRASH|MODIFY|INSERT|DROP)(?:$|_)",
    re.IGNORECASE,
)
MAX_STEPS = 12

_CLIENT_LOCK = threading.Lock()
_SHARED_GENAI_CLIENT: Any = None


def _get_genai_client() -> Any:
    global _SHARED_GENAI_CLIENT
    with _CLIENT_LOCK:
        if _SHARED_GENAI_CLIENT is None:
            api_key = get_api_key()
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY missing in .env")
            from google import genai  # type: ignore
            _SHARED_GENAI_CLIENT = genai.Client(api_key=api_key)
        return _SHARED_GENAI_CLIENT


def _call_gemini_structured(prompt: str, schema_cls: type[BaseModel]) -> BaseModel:
    from google.genai import types  # type: ignore
    client = _get_genai_client()
    last_err: Exception | None = None
    for model_id in RATE_SHIELD.choose_models([get_reasoning_model(), get_fast_model()]):
        for _ in range(2):
            try:
                cfg: dict[str, Any] = {
                    "response_mime_type": "application/json",
                    "response_schema": schema_cls,
                }
                if is_gemini_4_model(model_id) and hasattr(types, "ThinkingConfig") and hasattr(types, "ThinkingLevel"):
                    cfg["thinking_config"] = types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH)
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(**cfg),
                )
                return schema_cls.model_validate_json((resp.text or "").strip())
            except ValidationError as verr:
                prompt = f"{prompt}\n\nVALIDATION ERROR:\n{verr}\nReturn valid JSON only."
                last_err = verr
            except Exception as exc:
                last_err = exc
                if RATE_SHIELD.is_quota_error(exc):
                    RATE_SHIELD.mark_rate_limited(model_id, cooldown_seconds=45.0)
                    break
    raise RuntimeError(f"Structured reasoning failed: {last_err}")


def _parse_args_json(args_json: str) -> dict[str, Any]:
    try:
        data = json.loads(args_json or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _execute_unified_tool(tool: str, args: dict[str, Any], cancel_event: threading.Event | None = None) -> dict[str, Any]:
    if cancel_event and cancel_event.is_set():
        return {"ok": False, "error_code": "CANCELLED", "message": "Captain stopped task."}

    if tool == "playwright_mcp":
        return MCP_HUB.call_tool("playwright", str(args.get("tool_name", "")), dict(args.get("arguments") or {}))
    if tool == "windows_mcp":
        return MCP_HUB.call_tool("windows", str(args.get("tool_name", "")), dict(args.get("arguments") or {}))
    if tool == "composio_action":
        return COMPOSIO_BRIDGE.execute_action(
            action_slug=str(args.get("action_slug", "")),
            arguments=dict(args.get("arguments") or {}),
            confirmed=bool(args.get("confirmed", False)),
        )
    if tool == "web_autonomous":
        return AUTONOMOUS_WEB_AGENT.run_autonomous_goal(
            goal=str(args.get("goal", "")),
            max_steps=int(args.get("max_steps", 8)),
            start_url=args.get("start_url"),
            cancel_event=cancel_event,
        )
    if tool == "web_a11y_snapshot":
        if args.get("url"):
            EDGE_AGENT.navigate_active_tab(str(args["url"]))
        return AUTONOMOUS_WEB_AGENT.get_accessibility_tree(max_nodes=int(args.get("max_nodes", 75)))
    if tool == "windows_uia_inspect":
        return WINDOWS_UIA_AGENT.inspect_window(window_title=args.get("window_title"), max_elements=60)
    if tool == "windows_uia_click":
        return WINDOWS_UIA_AGENT.click_element(index=args.get("index"), name=args.get("name"), window_title=args.get("window_title"))
    if tool == "windows_uia_type":
        return WINDOWS_UIA_AGENT.type_into_element(
            text=str(args.get("text", "")),
            index=args.get("index"),
            name=args.get("name"),
            press_enter=bool(args.get("press_enter", False)),
            window_title=args.get("window_title"),
        )
    if tool == "windows_app_open":
        return open_allowlisted_app(str(args.get("app_name", "")))
    if tool == "windows_system":
        act = str(args.get("action", "status")).lower()
        if act == "volume":
            return set_system_volume(level=int(args.get("level", 50)))
        if act == "brightness":
            return set_monitor_brightness(int(args.get("level", 60)))
        return get_system_health()
    if tool == "memory_update":
        return LIVING_MEMORY.remember(str(args.get("content", "")))
    if tool == "memory_recall":
        return LIVING_MEMORY.recall(str(args.get("query", "")))
    return {"ok": False, "message": f"Unknown tool '{tool}'."}


class DarkShadowReasoningEngine:
    """Unified Decision-1 Router + LangGraph Plan-Execute-Verify-Replan Brain."""

    def __init__(self) -> None:
        self._cancel_event = threading.Event()
        self._last_goal = ""
        self._last_successful_trace: list[dict[str, Any]] = []
        self._sqlite_conn: sqlite3.Connection | None = None
        self._graph: Any = None
        self._langgraph_available = False
        self._build_langgraph()

    def _build_checkpointer(self):
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore
            CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
            self._sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            return SqliteSaver(self._sqlite_conn)
        except Exception:
            from langgraph.checkpoint.memory import MemorySaver  # type: ignore
            return MemorySaver()

    def _build_langgraph(self) -> None:
        try:
            from langgraph.graph import END, START, StateGraph  # type: ignore
            from langgraph.types import interrupt  # type: ignore
        except Exception as exc:
            log_error("reasoning_engine_v2", f"LangGraph not importable: {exc}")
            self._langgraph_available = False
            return

        def route_entry_node(state: HierarchicalGraphState) -> dict[str, Any]:
            try:
                routed = route_command_with_decision_1(state["goal"])
            except Exception as exc:
                routed = {"ok": False, "route_target": "langgraph_planner", "execution_mode": "autonomous_graph", "error": str(exc)}
            if routed.get("execution_mode") == "blocked":
                return {
                    "route_decision": routed,
                    "done": True,
                    "final_answer": "Captain, Gemini Decision-1 safety gate ne is command ko block kiya hai.",
                }
            return {"route_decision": routed}

        def plan_node(state: HierarchicalGraphState) -> dict[str, Any]:
            if state.get("done"):
                return {}
            route_hint = state["route_decision"].get("route_target", "langgraph_planner")
            pw_tools = MCP_HUB.discover_tools("playwright").get("tools", [])[:12]
            win_tools = MCP_HUB.discover_tools("windows").get("tools", [])[:12]
            prompt = (
                f"Create a concise 1-5 step milestone plan for DarkShadow.\n"
                f"Goal: {state['goal']}\n"
                f"Decision-1 Primary Subsystem Route: {route_hint}\n"
                f"Playwright MCP tools: {[t.get('name') for t in pw_tools]}\n"
                f"Windows-MCP tools: {[t.get('name') for t in win_tools]}\n"
                f"Composio SaaS apps ready: GMAIL, GITHUB, GOOGLECALENDAR, SLACK, NOTION"
            )
            try:
                draft = _call_gemini_structured(prompt, PlanDraft)
                assert isinstance(draft, PlanDraft)
                return {
                    "milestones": draft.milestones,
                    "current_milestone_idx": 0,
                    "success_criteria": draft.success_criteria,
                }
            except Exception:
                return {
                    "milestones": [state["goal"][:100]],
                    "current_milestone_idx": 0,
                    "success_criteria": "Goal execution completed.",
                }

        def decide_node(state: HierarchicalGraphState) -> dict[str, Any]:
            if state.get("done") or state["step_count"] >= MAX_STEPS or self._cancel_event.is_set():
                return {"done": True}
            milestone = (
                state["milestones"][state["current_milestone_idx"]]
                if state["current_milestone_idx"] < len(state["milestones"])
                else "Finalize goal"
            )
            obs = json.dumps(state["step_logs"][-4:], ensure_ascii=False)[:2400]
            prompt = (
                f"Goal: {state['goal']}\nActive Milestone: {milestone}\n"
                f"Preferred Route: {state['route_decision'].get('route_target')}\n"
                f"Observations: {obs}\n"
                "Choose next tool from: playwright_mcp, windows_mcp, composio_action, web_autonomous, "
                "windows_uia_inspect, windows_uia_click, windows_uia_type, windows_app_open, windows_system, final_answer."
            )
            try:
                dec = _call_gemini_structured(prompt, NextActionDecision)
                assert isinstance(dec, NextActionDecision)
                if dec.tool == "final_answer":
                    return {"done": True, "final_answer": dec.final_response or "Captain, task complete ho gaya.", "next_action": dec.model_dump()}
                return {"next_action": dec.model_dump()}
            except Exception as exc:
                return {
                    "done": True,
                    "final_answer": f"Decision error: {exc}",
                    "next_action": {"tool": "final_answer", "thought": "Error fallback", "args_json": "{}"},
                }

        def safety_gate_node(state: HierarchicalGraphState) -> dict[str, Any]:
            if state.get("done"):
                return {}
            act = state["next_action"]
            tool, args_str = str(act.get("tool", "")), str(act.get("args_json", "{}"))
            parsed_args = _parse_args_json(args_str)
            shield = check_hard_shields(f"{tool} {args_str}")
            if shield:
                return {"done": True, "approved": False, "hitl_confirmed": False, "final_answer": f"Shield blocked: {shield}"}
            hitl_prob = float(state["route_decision"].get("requires_hitl_prob", 0.0))
            is_mutating_composio = (
                tool == "composio_action"
                and bool(_COMPOSIO_MUTATING_RE.search(str(parsed_args.get("action_slug", ""))))
            )
            needs_hitl = bool(
                act.get("requires_confirmation")
                or hitl_prob >= 0.7
                or is_mutating_composio
                or _SENSITIVE_STEP_RE.search(f"{tool} {args_str}")
            )
            if needs_hitl:
                ok = interrupt({"type": "captain_approval_required", "tool": tool, "args": parsed_args})
                if not bool(ok):
                    return {
                        "done": True,
                        "approved": False,
                        "hitl_confirmed": False,
                        "final_answer": "Captain ne step cancel kar diya.",
                    }
                return {"approved": True, "hitl_confirmed": True}
            return {"approved": True, "hitl_confirmed": False}

        def execute_node(state: HierarchicalGraphState) -> dict[str, Any]:
            if state.get("done"):
                return {}
            act = state["next_action"]
            tool = str(act.get("tool", ""))
            args = _parse_args_json(str(act.get("args_json", "{}")))
            # Only pass confirmed=True to Composio when Captain explicitly approved via HITL interrupt
            if tool == "composio_action":
                if state.get("hitl_confirmed"):
                    args["confirmed"] = True
                else:
                    args["confirmed"] = False
            res = _execute_unified_tool(tool, args, cancel_event=self._cancel_event)
            logs = list(state["step_logs"])
            logs.append({"step": state["step_count"] + 1, "tool": tool, "args": args, "result": res})
            return {"step_logs": logs, "step_count": state["step_count"] + 1, "hitl_confirmed": False}

        def verify_step_node(state: HierarchicalGraphState) -> dict[str, Any]:
            if state.get("done") or not state["step_logs"]:
                return {}
            latest = state["step_logs"][-1]
            try:
                verdict = verify_react_step_with_decision_1(state["goal"], latest["tool"], latest["args"], latest["result"])
            except Exception as exc:
                verdict = {"step_succeeded_prob": 1.0 if latest["result"].get("ok") else 0.1, "needs_replan_prob": 0.0, "error": str(exc)}
            advance = verdict.get("step_succeeded_prob", 0.0) >= 0.6
            next_idx = min(state["current_milestone_idx"] + (1 if advance else 0), len(state["milestones"]))
            return {"last_verification": verdict, "current_milestone_idx": next_idx}

        def replan_node(state: HierarchicalGraphState) -> dict[str, Any]:
            prompt = (
                f"Previous step failed/stalled for goal: {state['goal']}\n"
                f"Verification: {json.dumps(state['last_verification'])}\n"
                f"Logs: {json.dumps(state['step_logs'][-3:], ensure_ascii=False)[:1800]}\n"
                "Provide updated remaining milestones."
            )
            try:
                draft = _call_gemini_structured(prompt, PlanDraft)
                assert isinstance(draft, PlanDraft)
                return {
                    "milestones": draft.milestones,
                    "current_milestone_idx": 0,
                    "replan_count": state["replan_count"] + 1,
                }
            except Exception:
                return {"replan_count": state["replan_count"] + 1}

        def synthesize_node(state: HierarchicalGraphState) -> dict[str, Any]:
            if state.get("final_answer"):
                return {}
            lines = [f"Step {l['step']} [{l['tool']}]: {'OK' if l['result'].get('ok') else 'FAIL'}" for l in state["step_logs"]]
            return {"final_answer": "Captain, task complete:\n" + "\n".join(lines)}

        builder = StateGraph(HierarchicalGraphState)
        for name, fn in [
            ("route_entry", route_entry_node),
            ("plan", plan_node),
            ("decide", decide_node),
            ("safety_gate", safety_gate_node),
            ("execute", execute_node),
            ("verify", verify_step_node),
            ("replan", replan_node),
            ("synthesize", synthesize_node),
        ]:
            builder.add_node(name, fn)

        builder.add_edge(START, "route_entry")
        builder.add_conditional_edges("route_entry", lambda s: "synthesize" if s.get("done") else "plan", {"plan": "plan", "synthesize": "synthesize"})
        builder.add_edge("plan", "decide")
        builder.add_conditional_edges("decide", lambda s: "synthesize" if s.get("done") else "safety_gate", {"safety_gate": "safety_gate", "synthesize": "synthesize"})
        builder.add_conditional_edges("safety_gate", lambda s: "synthesize" if s.get("done") else "execute", {"execute": "execute", "synthesize": "synthesize"})
        builder.add_edge("execute", "verify")
        builder.add_conditional_edges(
            "verify",
            lambda s: "synthesize"
            if (s.get("done") or s["step_count"] >= MAX_STEPS or s["current_milestone_idx"] >= len(s["milestones"]))
            else ("replan" if s.get("last_verification", {}).get("needs_replan_prob", 0.0) >= 0.65 and s["replan_count"] < 3 else "decide"),
            {"replan": "replan", "decide": "decide", "synthesize": "synthesize"},
        )
        builder.add_edge("replan", "decide")
        builder.add_edge("synthesize", END)

        self._graph = builder.compile(checkpointer=self._build_checkpointer())
        self._langgraph_available = True

    def cancel_active(self) -> None:
        self._cancel_event.set()

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "engine": "reasoning_engine_v2",
            "langgraph_available": self._langgraph_available,
            "sqlite_checkpoint_active": self._sqlite_conn is not None,
            "last_goal": self._last_goal,
            "last_trace_steps": len(self._last_successful_trace),
        }

    def get_last_successful_trace(self) -> tuple[str, list[dict[str, Any]]]:
        return self._last_goal, list(self._last_successful_trace)

    def shutdown(self) -> None:
        self._cancel_event.set()
        if self._sqlite_conn is not None:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass
            self._sqlite_conn = None

    def _format_graph_outcome(self, tid: str, config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        try:
            snapshot = self._graph.get_state(config)
            if snapshot and getattr(snapshot, "next", None):
                interrupt_payload: Any = {}
                tasks = getattr(snapshot, "tasks", None) or []
                for task in tasks:
                    interrupts = getattr(task, "interrupts", None) or []
                    if interrupts:
                        interrupt_payload = getattr(interrupts[0], "value", interrupts[0])
                        break
                tool_name = (
                    interrupt_payload.get("tool", "sensitive_action")
                    if isinstance(interrupt_payload, dict)
                    else "sensitive_action"
                )
                return {
                    "ok": True,
                    "needs_approval": True,
                    "thread_id": tid,
                    "approval_details": interrupt_payload,
                    "message": (
                        f"Captain, '{tool_name}' chalane ke liye aapki approval chahiye "
                        f"(thread_id: {tid}). Approve karne ke liye resume_approve bolein ya cancel karein."
                    ),
                }
        except Exception:
            pass

        step_logs = result.get("step_logs") or []
        successful = [
            {"tool": s.get("tool", ""), "args": s.get("args", {})}
            for s in step_logs
            if isinstance(s, dict) and isinstance(s.get("result"), dict) and s["result"].get("ok")
        ]
        if successful:
            self._last_goal = str(result.get("goal") or self._last_goal)
            self._last_successful_trace = successful

        return {
            "ok": True,
            "thread_id": tid,
            "route": result.get("route_decision"),
            "steps_executed": len(step_logs),
            "message": result.get("final_answer", "") or "Captain, task complete ho gaya.",
        }

    def run_goal(self, goal: str, thread_id: str | None = None) -> dict[str, Any]:
        self._cancel_event.clear()
        if not self._langgraph_available or self._graph is None:
            from reasoning_engine import REASONING_ENGINE as LEGACY_RE
            return LEGACY_RE.run_goal(goal, thread_id=thread_id)

        tid = thread_id or f"ds-{uuid.uuid4().hex[:8]}"
        init_state: HierarchicalGraphState = {
            "goal": goal,
            "context": LIVING_MEMORY.build_system_context_block(current_query=goal),
            "route_decision": {},
            "milestones": [],
            "current_milestone_idx": 0,
            "success_criteria": "",
            "step_count": 0,
            "next_action": {},
            "step_logs": [],
            "last_verification": {},
            "replan_count": 0,
            "approved": True,
            "hitl_confirmed": False,
            "done": False,
            "final_answer": "",
        }
        cfg = {"configurable": {"thread_id": tid}}
        try:
            result = self._graph.invoke(init_state, config=cfg)
            return self._format_graph_outcome(tid, cfg, result if isinstance(result, dict) else {})
        except Exception as exc:
            log_error("reasoning_engine_v2", f"LangGraph execution error: {exc}", exception=exc)
            return {"ok": False, "error_code": "GRAPH_EXEC_ERROR", "message": f"Graph execution error: {exc}"}

    def resume_approval(self, thread_id: str, approved: bool) -> dict[str, Any]:
        if not thread_id or not thread_id.strip():
            return {"ok": False, "error_code": "MISSING_THREAD_ID", "message": "Resume ke liye thread_id zaroori hai."}
        if not self._langgraph_available or self._graph is None:
            from reasoning_engine import REASONING_ENGINE as LEGACY_RE
            return LEGACY_RE.resume_approval(thread_id, approved=approved)
        try:
            from langgraph.types import Command  # type: ignore
            cfg = {"configurable": {"thread_id": thread_id.strip()}}
            result = self._graph.invoke(Command(resume=bool(approved)), config=cfg)
            return self._format_graph_outcome(thread_id.strip(), cfg, result if isinstance(result, dict) else {})
        except Exception as exc:
            log_error("reasoning_engine_v2", f"LangGraph resume error: {exc}", exception=exc)
            return {"ok": False, "error_code": "GRAPH_RESUME_ERROR", "message": f"Resume error: {exc}"}


REASONING_ENGINE_V2 = DarkShadowReasoningEngine()

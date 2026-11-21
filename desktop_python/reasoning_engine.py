"""
B-All (Upgraded & Fixed): Dynamic ReAct Reasoning Engine (100% FREE-TIER GEMINI)
================================================================================
Uses ONLY Free-Tier Friendly Gemini Models:
  - Primary: `gemini-4-hydrogen` with `ThinkingLevel.HIGH` (NO paid gemini-4-neon/carbon!)
  - Fallback: `gemini-3.1-flash-lite`
  - ZERO deprecated `temperature` parameter on Gemini 4 models!

Fixes applied:
  1. Replaced static upfront 6-step blind planning with a TRUE Dynamic ReAct loop:
     `decide_next_step` -> `safety_gate (HITL)` -> `execute_step` -> `decide_next_step` ...
     Now Step 2 SEES the exact UIA element IDs / A11y tree returned by Step 1!
  2. Replaced `args: dict[str, Any]` with `args_json: str` so Gemini Structured Output
     NEVER throws `400 INVALID_ARGUMENT: properties should be non-empty for OBJECT type`!
  3. Fixed `resume_approval()` to check `snapshot.next` for chained interrupts!
  4. Added `check_hard_shields()` + `_SENSITIVE_STEP_RE` to the pure-Python fallback too!
  5. Uses persistent `SqliteSaver` checkpointer (if installed) with automatic `MemorySaver` fallback.
  6. Reuses singleton `genai.Client` and supports emergency Kill Switch (`cancel_event`).
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
from config import (
    CHECKPOINT_DB_PATH,
    get_api_key,
    get_fast_model,
    get_reasoning_model,
    is_gemini_4_model,
)
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

# ---------------------------------------------------------------------------
# 1. Gemini-Compatible Strict Pydantic v2 Schemas (NO empty dict OBJECTs!)
# ---------------------------------------------------------------------------

ToolCategory = Literal[
    "web_autonomous",
    "web_a11y_snapshot",
    "windows_uia_inspect",
    "windows_uia_click",
    "windows_uia_type",
    "windows_app_open",
    "windows_system",
    "mcp_hub_call",
    "memory_update",
    "memory_recall",
    "final_answer",
]


class NextActionDecision(BaseModel):
    """Dynamic ReAct decision: observes all previous step outputs before choosing the next action."""
    thought: str = Field(..., min_length=2, description="Brief reasoning based on latest observations")
    tool: ToolCategory = Field(..., description="Next tool to execute, or 'final_answer' when goal is done")
    args_json: str = Field(
        default="{}",
        description="Valid JSON object string containing arguments for the chosen tool",
    )
    requires_confirmation: bool = Field(
        default=False,
        description="True if step deletes files, sends external messages, or modifies sensitive settings",
    )
    final_response: str = Field(
        default="",
        description="Populated ONLY when tool is 'final_answer' — crisp summary for Captain",
    )


class WebAutonomousArgs(BaseModel):
    goal: str = Field(..., min_length=3)
    start_url: str | None = None
    max_steps: int = Field(default=8, ge=1, le=20)


class WindowsUIAClickArgs(BaseModel):
    index: int | None = Field(default=None, ge=1)
    name: str | None = None
    window_title: str | None = None


class WindowsUIATypeArgs(BaseModel):
    text: str = Field(..., min_length=1)
    index: int | None = Field(default=None, ge=1)
    name: str | None = None
    press_enter: bool = False
    window_title: str | None = None


class MCPHubCallArgs(BaseModel):
    server_name: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdateArgs(BaseModel):
    mode: Literal["remember", "core_append", "core_replace"] = "remember"
    content: str = Field(..., min_length=2)
    block: str = "preferences"
    old_text: str = ""


_SENSITIVE_STEP_RE = re.compile(
    r"\b(delete|remove|format|send_whatsapp|send email|shutdown|restart|kill|terminate|rm\s+-rf)\b",
    re.IGNORECASE,
)

MAX_REACT_STEPS = 8


# ---------------------------------------------------------------------------
# 2. LangGraph Dynamic ReAct State
# ---------------------------------------------------------------------------

class AgentGraphState(TypedDict):
    goal: str
    context: str
    step_count: int
    next_action: dict[str, Any]
    step_logs: list[dict[str, Any]]
    approved: bool
    done: bool
    final_answer: str


# ---------------------------------------------------------------------------
# 3. Singleton Free-Tier Gemini Structured Caller (ZERO temperature on Gemini 4!)
# ---------------------------------------------------------------------------

_CLIENT_LOCK = threading.Lock()
_SHARED_GENAI_CLIENT: Any = None


def _get_genai_client() -> Any:
    global _SHARED_GENAI_CLIENT
    with _CLIENT_LOCK:
        if _SHARED_GENAI_CLIENT is None:
            api_key = get_api_key()
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY not found in .env")
            from google import genai  # type: ignore
            _SHARED_GENAI_CLIENT = genai.Client(api_key=api_key)
        return _SHARED_GENAI_CLIENT


def _call_gemini_structured(prompt: str, schema_cls: type[BaseModel]) -> BaseModel:
    """
    Calls free-tier `gemini-4-hydrogen` (ThinkingLevel.HIGH, NO temperature!) with
    automatic fallback to `gemini-3.1-flash-lite` on 503/429.
    """
    from google.genai import types  # type: ignore

    client = _get_genai_client()
    primary = get_reasoning_model()
    fallback = get_fast_model()
    last_err: Exception | None = None

    for model_id in RATE_SHIELD.choose_models([primary, fallback]):
        for _attempt in range(2):
            try:
                cfg_kwargs: dict[str, Any] = {
                    "response_mime_type": "application/json",
                    "response_schema": schema_cls,
                }
                if is_gemini_4_model(model_id):
                    if hasattr(types, "ThinkingConfig") and hasattr(types, "ThinkingLevel"):
                        cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH
                        )
                else:
                    cfg_kwargs["temperature"] = 0.15

                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(**cfg_kwargs),
                )
                raw = (resp.text or "").strip()
                return schema_cls.model_validate_json(raw)
            except ValidationError as verr:
                prompt = (
                    f"{prompt}\n\nPREVIOUS OUTPUT FAILED PYDANTIC VALIDATION:\n{verr}\n"
                    "Return ONLY valid JSON matching the exact schema."
                )
                last_err = verr
            except Exception as exc:
                last_err = exc
                if RATE_SHIELD.is_quota_error(exc):
                    RATE_SHIELD.mark_rate_limited(model_id, cooldown_seconds=45.0)
                    break
                if any(tok in str(exc) for tok in ("503", "UNAVAILABLE")):
                    break
                continue

    raise RuntimeError(f"Structured reasoning failed: {last_err}")


def _parse_args_json(args_json: str) -> dict[str, Any]:
    if not args_json or not args_json.strip():
        return {}
    try:
        parsed = json.loads(args_json)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 4. Deterministic Validated Step Executor
# ---------------------------------------------------------------------------

def _execute_validated_step(
    tool: str,
    args: dict[str, Any],
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if cancel_event and cancel_event.is_set():
        return {"ok": False, "error_code": "CANCELLED", "message": "Captain ne emergency stop trigger kiya."}

    try:
        if tool == "web_autonomous":
            v = WebAutonomousArgs.model_validate(args)
            return AUTONOMOUS_WEB_AGENT.run_autonomous_goal(
                goal=v.goal, max_steps=v.max_steps, start_url=v.start_url, cancel_event=cancel_event
            )

        if tool == "web_a11y_snapshot":
            url = args.get("url")
            if url:
                EDGE_AGENT.navigate_active_tab(str(url))
            return AUTONOMOUS_WEB_AGENT.get_accessibility_tree(
                max_nodes=int(args.get("max_nodes", 75))
            )

        if tool == "windows_uia_inspect":
            return WINDOWS_UIA_AGENT.inspect_window(
                window_title=args.get("window_title"),
                max_elements=int(args.get("max_elements", 60)),
            )

        if tool == "windows_uia_click":
            v = WindowsUIAClickArgs.model_validate(args)
            return WINDOWS_UIA_AGENT.click_element(
                index=v.index, name=v.name, window_title=v.window_title
            )

        if tool == "windows_uia_type":
            v = WindowsUIATypeArgs.model_validate(args)
            return WINDOWS_UIA_AGENT.type_into_element(
                text=v.text,
                index=v.index,
                name=v.name,
                press_enter=v.press_enter,
                window_title=v.window_title,
            )

        if tool == "windows_app_open":
            return open_allowlisted_app(str(args.get("app_name", "")))

        if tool == "windows_system":
            action = str(args.get("action", "status")).lower()
            if action == "volume":
                return set_system_volume(level=int(args.get("level", 50)))
            if action == "brightness":
                return set_monitor_brightness(int(args.get("level", 60)))
            return get_system_health()

        if tool == "mcp_hub_call":
            v = MCPHubCallArgs.model_validate(args)
            return MCP_HUB.call_tool(v.server_name, v.tool_name, v.arguments)

        if tool == "memory_update":
            v = MemoryUpdateArgs.model_validate(args)
            if v.mode == "core_append":
                return LIVING_MEMORY.core_memory_append(v.block, v.content)
            if v.mode == "core_replace":
                return LIVING_MEMORY.core_memory_replace(v.block, v.old_text, v.content)
            return LIVING_MEMORY.remember(v.content)

        if tool == "memory_recall":
            return LIVING_MEMORY.recall(str(args.get("query", "")))

        if tool == "final_answer":
            return {"ok": True, "message": str(args.get("answer", "Completed."))}

        return {"ok": False, "message": f"Unknown tool '{tool}'."}

    except ValidationError as verr:
        return {"ok": False, "validation_error": str(verr), "message": f"Invalid arguments: {verr}"}
    except Exception as exc:
        log_error("reasoning_engine", f"Step '{tool}' error: {exc}", exception=exc)
        return {"ok": False, "message": f"Execution error: {exc}"}


def _build_react_prompt(goal: str, context: str, step_logs: list[dict[str, Any]], step_num: int) -> str:
    obs_lines = []
    for log in step_logs[-6:]:
        res_preview = json.dumps(log.get("result", {}), ensure_ascii=False)[:1400]
        obs_lines.append(f"Step {log['step']} [{log['tool']}({log['args']})]: {res_preview}")
    obs_text = "\n".join(obs_lines) if obs_lines else "(No steps executed yet.)"

    return (
        "You are DarkShadow's Dynamic ReAct Agent for Windows 11.\n"
        f"{context}\n\n"
        f"USER GOAL: {goal}\n"
        f"CURRENT STEP: {step_num} / {MAX_REACT_STEPS}\n\n"
        f"OBSERVATIONS SO FAR:\n{obs_text}\n\n"
        "Choose ONLY the SINGLE NEXT best action based on the latest observations. "
        "When the goal is achieved (or cannot proceed), choose tool='final_answer' and fill `final_response`.\n"
        "Available tools & expected `args_json`:\n"
        '- web_autonomous: {"goal": "...", "start_url": "...", "max_steps": 8}\n'
        '- web_a11y_snapshot: {"url": "...", "max_nodes": 75}\n'
        '- windows_uia_inspect: {"window_title": "..."}\n'
        '- windows_uia_click: {"index": 1, "name": "...", "window_title": "..."}\n'
        '- windows_uia_type: {"text": "...", "index": 1, "name": "...", "press_enter": true, "window_title": "..."}\n'
        '- windows_app_open: {"app_name": "..."}\n'
        '- windows_system: {"action": "status|volume|brightness", "level": 60}\n'
        '- mcp_hub_call: {"server_name": "playwright", "tool_name": "...", "arguments": {}}\n'
        '- memory_update: {"mode": "remember|core_append|core_replace", "content": "...", "block": "preferences"}\n'
        '- memory_recall: {"query": "..."}\n'
        '- final_answer: {"answer": "..."}\n'
        "Set requires_confirmation=true for any risky/delete/send action."
    )


# ---------------------------------------------------------------------------
# 5. LangGraph Dynamic ReAct Engine (with Persistent Checkpointer & Chained HITL)
# ---------------------------------------------------------------------------

class DarkShadowReasoningEngine:
    """Dynamic `Decide Next Step -> Safety Gate (HITL) -> Execute -> Loop -> Synthesize` engine."""

    def __init__(self) -> None:
        self._langgraph_available = False
        self._checkpointer_type = "none"
        self._graph: Any = None
        self._checkpointer: Any = None
        self._sqlite_conn: sqlite3.Connection | None = None
        self._cancel_event = threading.Event()
        self._last_goal: str = ""
        self._last_successful_trace: list[dict[str, Any]] = []
        self._build_langgraph()

    def get_last_successful_trace(self) -> tuple[str, list[dict[str, Any]]]:
        """Returns (goal, step_logs) from the latest completed multi-step run for Playbook learning."""
        return self._last_goal, list(self._last_successful_trace)

    def cancel_active(self) -> None:
        """Signal any active reasoning loop to abort safely (Emergency Kill Switch)."""
        self._cancel_event.set()

    def _build_checkpointer(self):
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore
            CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_conn = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
            self._sqlite_conn.execute("PRAGMA journal_mode=WAL;")
            self._checkpointer_type = "sqlite"
            return SqliteSaver(self._sqlite_conn)
        except Exception:
            from langgraph.checkpoint.memory import MemorySaver  # type: ignore
            self._checkpointer_type = "memory"
            return MemorySaver()

    def _build_langgraph(self) -> None:
        try:
            from langgraph.graph import END, START, StateGraph  # type: ignore
            from langgraph.types import interrupt  # type: ignore
        except Exception:
            self._langgraph_available = False
            return

        def decide_node(state: AgentGraphState) -> dict[str, Any]:
            if self._cancel_event.is_set():
                return {"done": True, "final_answer": "Captain ke Emergency Stop par autonomous task rok diya gaya."}
            if state["step_count"] >= MAX_REACT_STEPS:
                return {"done": True}

            prompt = _build_react_prompt(
                state["goal"], state["context"], state["step_logs"], state["step_count"] + 1
            )
            decision = _call_gemini_structured(prompt, NextActionDecision)
            assert isinstance(decision, NextActionDecision)

            if decision.tool == "final_answer":
                ans = decision.final_response.strip() or _parse_args_json(decision.args_json).get("answer", "")
                return {
                    "done": True,
                    "final_answer": str(ans or "Captain, task complete ho gaya."),
                    "next_action": decision.model_dump(),
                }

            return {
                "next_action": decision.model_dump(),
                "done": False,
            }

        def safety_gate_node(state: AgentGraphState) -> dict[str, Any]:
            if state.get("done"):
                return {}
            act = state.get("next_action") or {}
            tool = str(act.get("tool", ""))
            args_str = str(act.get("args_json", "{}"))
            req_conf = bool(act.get("requires_confirmation", False))

            shield_reason = check_hard_shields(f"{tool} {args_str}")
            if shield_reason:
                return {
                    "done": True,
                    "approved": False,
                    "final_answer": f"Captain, Safety Shield ne risky step block kar diya: {shield_reason}",
                }

            needs_hitl = req_conf or bool(_SENSITIVE_STEP_RE.search(f"{tool} {args_str}"))
            if needs_hitl:
                decision = interrupt(
                    {
                        "type": "captain_approval_required",
                        "step": state["step_count"] + 1,
                        "tool": tool,
                        "args": _parse_args_json(args_str),
                        "message": f"Captain, kya main step {state['step_count'] + 1} ({tool}) execute karoon?",
                    }
                )
                if not bool(decision):
                    return {
                        "done": True,
                        "approved": False,
                        "final_answer": f"Captain ke instruction par step {state['step_count'] + 1} cancel kar diya gaya.",
                    }
            return {"approved": True}

        def execute_node(state: AgentGraphState) -> dict[str, Any]:
            if state.get("done"):
                return {}
            act = state.get("next_action") or {}
            tool = str(act.get("tool", ""))
            args = _parse_args_json(str(act.get("args_json", "{}")))
            res = _execute_validated_step(tool, args, cancel_event=self._cancel_event)
            step_num = state["step_count"] + 1
            logs = list(state["step_logs"])
            logs.append({"step": step_num, "tool": tool, "args": args, "result": res})
            return {"step_logs": logs, "step_count": step_num}

        def synthesize_node(state: AgentGraphState) -> dict[str, Any]:
            if state.get("final_answer"):
                return {}
            summary_lines = [
                f"Step {l['step']} ({l['tool']}): {'OK' if l['result'].get('ok') else 'FAIL'} — {str(l['result'].get('message', ''))[:240]}"
                for l in state["step_logs"]
            ]
            answer = "Captain, autonomous task complete:\n" + "\n".join(summary_lines)
            return {"final_answer": answer}

        def route_after_decide(state: AgentGraphState) -> str:
            return "synthesize" if state.get("done") else "safety_gate"

        def route_after_safety(state: AgentGraphState) -> str:
            return "synthesize" if state.get("done") else "execute"

        def route_after_execute(state: AgentGraphState) -> str:
            if state.get("done") or state["step_count"] >= MAX_REACT_STEPS or self._cancel_event.is_set():
                return "synthesize"
            return "decide"

        builder = StateGraph(AgentGraphState)
        builder.add_node("decide", decide_node)
        builder.add_node("safety_gate", safety_gate_node)
        builder.add_node("execute", execute_node)
        builder.add_node("synthesize", synthesize_node)

        builder.add_edge(START, "decide")
        builder.add_conditional_edges("decide", route_after_decide, {"safety_gate": "safety_gate", "synthesize": "synthesize"})
        builder.add_conditional_edges("safety_gate", route_after_safety, {"execute": "execute", "synthesize": "synthesize"})
        builder.add_conditional_edges("execute", route_after_execute, {"decide": "decide", "synthesize": "synthesize"})
        builder.add_edge("synthesize", END)

        self._checkpointer = self._build_checkpointer()
        self._graph = builder.compile(checkpointer=self._checkpointer)
        self._langgraph_available = True

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "langgraph_active": self._langgraph_available,
            "checkpointer": self._checkpointer_type,
            "model": get_reasoning_model(),
            "fallback_model": get_fast_model(),
            "free_tier_only": True,
        }

    def _format_graph_outcome(self, tid: str, config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Handles BOTH final completion AND chained Human-in-the-Loop interrupts cleanly!"""
        snapshot = self._graph.get_state(config)
        if getattr(snapshot, "next", None):
            interrupts = []
            for task in getattr(snapshot, "tasks", ()) or ():
                for intr in getattr(task, "interrupts", ()) or ():
                    interrupts.append(intr.value)
            return {
                "ok": True,
                "engine": "langgraph",
                "thread_id": tid,
                "needs_approval": True,
                "approval_details": interrupts,
                "message": (
                    interrupts[0].get("message")
                    if interrupts and isinstance(interrupts[0], dict)
                    else "Captain, risky step ke liye aapki approval chahiye."
                ),
            }
        logs = list(result.get("step_logs", []))
        if logs:
            self._last_goal = str(result.get("goal", ""))
            self._last_successful_trace = logs
        return {
            "ok": True,
            "engine": "langgraph",
            "thread_id": tid,
            "needs_approval": False,
            "steps_executed": len(logs),
            "logs": logs,
            "message": result.get("final_answer", "Task completed."),
        }

    def run_goal(self, goal: str, thread_id: str | None = None) -> dict[str, Any]:
        """Runs a complex multi-step goal via dynamic ReAct using free-tier gemini-4-hydrogen."""
        self._cancel_event.clear()
        context = LIVING_MEMORY.build_system_context_block(current_query=goal)
        tid = thread_id or f"ds-{uuid.uuid4().hex[:8]}"

        initial_state: AgentGraphState = {
            "goal": goal,
            "context": context,
            "step_count": 0,
            "next_action": {},
            "step_logs": [],
            "approved": True,
            "done": False,
            "final_answer": "",
        }

        if self._langgraph_available and self._graph is not None:
            try:
                config = {"configurable": {"thread_id": tid}}
                result = self._graph.invoke(initial_state, config=config)
                return self._format_graph_outcome(tid, config, result)
            except Exception as exc:
                log_error("reasoning_engine", f"LangGraph run error: {exc}", exception=exc)
                return {"ok": False, "engine": "langgraph", "message": f"Reasoning error: {exc}"}

        # Pure-Python Dynamic ReAct Fallback (with FULL Safety Shields & HITL!)
        try:
            logs: list[dict[str, Any]] = []
            for step_num in range(1, MAX_REACT_STEPS + 1):
                if self._cancel_event.is_set():
                    return {"ok": False, "engine": "python_fallback", "message": "Captain ne task cancel kar diya."}
                prompt = _build_react_prompt(goal, context, logs, step_num)
                decision = _call_gemini_structured(prompt, NextActionDecision)
                assert isinstance(decision, NextActionDecision)

                if decision.tool == "final_answer":
                    if logs:
                        self._last_goal = goal
                        self._last_successful_trace = list(logs)
                    ans = decision.final_response.strip() or _parse_args_json(decision.args_json).get("answer", "")
                    return {
                        "ok": True,
                        "engine": "python_fallback",
                        "steps_executed": len(logs),
                        "logs": logs,
                        "message": str(ans or "Captain, task complete ho gaya."),
                    }

                shield = check_hard_shields(f"{decision.tool} {decision.args_json}")
                if shield:
                    return {"ok": False, "engine": "python_fallback", "error_code": "SHIELD_BLOCKED", "message": shield}

                if decision.requires_confirmation or _SENSITIVE_STEP_RE.search(f"{decision.tool} {decision.args_json}"):
                    return {
                        "ok": False,
                        "engine": "python_fallback",
                        "needs_approval": True,
                        "message": f"Captain, risky step ({decision.tool}) paused. Confirm explicitly before proceeding.",
                    }

                args = _parse_args_json(decision.args_json)
                res = _execute_validated_step(decision.tool, args, cancel_event=self._cancel_event)
                logs.append({"step": step_num, "tool": decision.tool, "args": args, "result": res})

            if logs:
                self._last_goal = goal
                self._last_successful_trace = list(logs)
            return {
                "ok": True,
                "engine": "python_fallback",
                "steps_executed": len(logs),
                "logs": logs,
                "message": "Captain, task complete: " + "; ".join(
                    str(l["result"].get("message", ""))[:180] for l in logs
                ),
            }
        except Exception as exc:
            log_error("reasoning_engine", f"Fallback planner error: {exc}", exception=exc)
            return {"ok": False, "message": f"Reasoning failed: {exc}"}

    def resume_approval(self, thread_id: str, approved: bool) -> dict[str, Any]:
        """Resumes a paused LangGraph HITL workflow AND detects any subsequent chained interrupts!"""
        if not self._langgraph_available or self._graph is None:
            return {"ok": False, "message": "LangGraph checkpointer not active."}
        try:
            from langgraph.types import Command  # type: ignore
            self._cancel_event.clear()
            config = {"configurable": {"thread_id": thread_id}}
            result = self._graph.invoke(Command(resume=bool(approved)), config=config)
            outcome = self._format_graph_outcome(thread_id, config, result)
            outcome["approved"] = bool(approved)
            return outcome
        except Exception as exc:
            log_error("reasoning_engine", f"resume_approval failed: {exc}", exception=exc)
            return {"ok": False, "message": f"Resume failed: {exc}"}

    def shutdown(self) -> None:
        self.cancel_active()
        if self._sqlite_conn is not None:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass


REASONING_ENGINE = DarkShadowReasoningEngine()

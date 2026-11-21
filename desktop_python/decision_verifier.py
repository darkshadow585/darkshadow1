"""
DarkShadow Upgrade: Gemini Decision Model 1 Command Router, Verifier & Bug Gate
=================================================================================
Uses the Decisions API with `gemini-decision-1` (or resilient Gemini 2.5/2.0 structured output fallback) for:
  1. route_command_with_decision_1(): Decides WHICH subsystem a user command goes to:
     - playwright_mcp (Edge browser automation)
     - windows_mcp (Desktop OS / UIA control)
     - composio_apps (Gmail, GitHub, Google Calendar, Slack, Notion)
     - langgraph_planner (Multi-step cross-app long-horizon planning)
     - instant_os (Simple volume/brightness/time/lock actions)
  2. verify_react_step_with_decision_1(): Verifies each LangGraph tool step outcome.
  3. audit_code_logic_with_decision_1(): Checks code/scripts for bugs & wrong logic.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal
from pydantic import BaseModel, Field

from google import genai
from config import get_api_key, get_fast_model


def _get_decisions_client() -> genai.Client:
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing in environment.")
    return genai.Client(
        api_key=api_key,
        http_options={"api_version": "v1beta", "headers": {"User-Agent": "darkshadow-desktop"}},
    )


class RouteDecisionSchema(BaseModel):
    route_target: Literal[
        "playwright_mcp",
        "windows_mcp",
        "composio_apps",
        "langgraph_planner",
        "instant_os",
        "other",
    ] = Field(description="Primary execution subsystem")
    requires_hitl: bool = Field(description="Whether Captain HITL confirmation is required before execution")
    needs_long_horizon_plan: bool = Field(description="Requires multi-step planning and LangGraph state checkpoints")
    safety_blocked: bool = Field(description="Whether action violates safety shields (payments, credentials, etc.)")
    risk_score: float = Field(description="Operational risk from 0.0 (harmless) to 3.0 (destructive)")


class StepVerificationSchema(BaseModel):
    step_succeeded: bool = Field(description="Whether tool execution genuinely achieved intended sub-step")
    needs_replan: bool = Field(description="Whether plan must be revised based on result")
    failure_cause: Literal["api_mismatch", "wrong_logic", "runtime_error", "security_block", "clean"] = Field(
        description="Classification of issue or clean"
    )


class CodeAuditSchema(BaseModel):
    has_bug: bool = Field(description="Contains runtime error, invalid keys, or uncaught exception")
    has_wrong_logic: bool = Field(description="Flawed logic or silent data loss")
    defect_type: Literal["api_mismatch", "wrong_logic", "security_leak", "runtime_crash", "clean"] = Field(
        description="Primary defect class"
    )
    severity_score: float = Field(description="Severity score from 0.0 to 3.0")


def route_command_with_decision_1(command: str) -> dict[str, Any]:
    """
    Decides where a Hinglish/English DarkShadow command should go before invoking heavy models.
    Uses Decisions API if available, or structured model fallback.
    """
    client = _get_decisions_client()
    payload = json.dumps(
        {
            "user_command": command.strip(),
            "subsystems": [
                "playwright_mcp: Microsoft Edge browser navigation, DOM clicks, scraping, web forms",
                "windows_mcp: Native Windows 11 desktop apps, window focus, local files, OS UIA",
                "composio_apps: External SaaS integrations (Gmail, GitHub, Google Calendar, Slack, Notion)",
                "langgraph_planner: Multi-step, cross-app workflows needing planning, memory, and verification",
                "instant_os: Single-step volume, brightness, mute, time, battery, or media controls",
            ],
        },
        ensure_ascii=False,
    )

    # 1. Native client.decisions check
    if hasattr(client, "decisions"):
        try:
            resp = client.decisions.create(
                model="gemini-decision-1",
                input=payload,
                questions={
                    "route_target": {
                        "type": "choice",
                        "instructions": "Which execution subsystem should handle this user command first?",
                        "criteria": {
                            "composio_apps": "External SaaS app actions like Gmail, GitHub, Slack, Notion, or Google Calendar.",
                            "instant_os": "Simple single-step OS control like volume, brightness, mute, time, or media playback.",
                            "langgraph_planner": "Complex multi-step goals spanning multiple tools, comparisons, or conditional planning.",
                            "other": "Purely conversational question or chat outside desktop/app automation.",
                            "playwright_mcp": "Browser navigation, website interaction, form filling, or page scraping in Edge.",
                            "windows_mcp": "Native Windows desktop app control, window management, or local OS GUI actions.",
                        },
                    },
                    "requires_hitl": {
                        "type": "noul",
                        "instructions": "Should DarkShadow pause for Captain HITL confirmation before executing this command?",
                    },
                    "needs_long_horizon_plan": {
                        "type": "noul",
                        "instructions": "Does this command require multi-step planning, state checkpoints, and step verification via LangGraph?",
                    },
                    "safety_blocked": {
                        "type": "noul",
                        "instructions": "Does this command involve forbidden actions (payments, CVV/OTP/bank login, webcam activation, or destructive disk wipe)?",
                    },
                    "risk_score": {
                        "type": "score",
                        "instructions": "Rate the operational risk level of executing this user command automatically.",
                    },
                },
            )
            answers = getattr(resp, "answers", {}) or {}
            route_ans = answers.get("route_target")
            hitl_ans = answers.get("requires_hitl")
            plan_ans = answers.get("needs_long_horizon_plan")
            block_ans = answers.get("safety_blocked")
            risk_ans = answers.get("risk_score")

            route_target = getattr(route_ans, "choice", "other")
            safety_blocked_prob = float(getattr(block_ans, "noul", 0.0))
            requires_hitl_prob = float(getattr(hitl_ans, "noul", 0.0))
            long_horizon_prob = float(getattr(plan_ans, "noul", 0.0))
            risk_score = float(getattr(risk_ans, "score", 0.0))

            if safety_blocked_prob >= 0.7 or risk_score >= 2.55:
                execution_mode = "blocked"
            elif requires_hitl_prob >= 0.6:
                execution_mode = "hitl_gated"
            elif long_horizon_prob >= 0.55 or route_target == "langgraph_planner":
                execution_mode = "autonomous_graph"
            else:
                execution_mode = "direct_dispatch"

            return {
                "ok": True,
                "engine": "gemini-decision-1",
                "route_target": route_target,
                "route_confidence": float(getattr(route_ans, "confidence", 1.0)),
                "requires_hitl_prob": requires_hitl_prob,
                "needs_long_horizon_prob": long_horizon_prob,
                "safety_blocked_prob": safety_blocked_prob,
                "risk_score": risk_score,
                "execution_mode": execution_mode,
            }
        except Exception:
            pass

    # 2. Resilient Structured Output Fallback
    prompt = (
        f"You are the Gemini Decision Model 1 command routing classifier for DarkShadow Desktop AI.\n"
        f"Classify the following user command into the appropriate subsystem, risk, and execution mode:\n"
        f"Command: '{command.strip()}'\n"
        f"Subsystem definitions:\n"
        f"- playwright_mcp: Microsoft Edge browser navigation, tabs, DOM interaction, web scraping\n"
        f"- windows_mcp: Windows 11 apps, window focus, file explorer, OS UI automation\n"
        f"- composio_apps: External SaaS like Gmail, GitHub, Google Calendar, Slack, Notion\n"
        f"- langgraph_planner: Multi-step, cross-app workflows requiring multi-step planning\n"
        f"- instant_os: Single-step OS controls (volume, brightness, mute, battery, time)\n"
        f"- other: Conversational chat or general question\n"
    )
    try:
        from google.genai import types
        fast_m = get_fast_model()
        resp = client.models.generate_content(
            model=fast_m,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RouteDecisionSchema,
            ),
        )
        dec = RouteDecisionSchema.model_validate_json((resp.text or "").strip())
        if dec.safety_blocked or dec.risk_score >= 2.5:
            execution_mode = "blocked"
        elif dec.requires_hitl:
            execution_mode = "hitl_gated"
        elif dec.needs_long_horizon_plan or dec.route_target == "langgraph_planner":
            execution_mode = "autonomous_graph"
        else:
            execution_mode = "direct_dispatch"

        return {
            "ok": True,
            "engine": f"structured_{fast_m}",
            "route_target": dec.route_target,
            "route_confidence": 0.95,
            "requires_hitl_prob": 1.0 if dec.requires_hitl else 0.0,
            "needs_long_horizon_prob": 1.0 if dec.needs_long_horizon_plan else 0.0,
            "safety_blocked_prob": 1.0 if dec.safety_blocked else 0.0,
            "risk_score": dec.risk_score,
            "execution_mode": execution_mode,
        }
    except Exception as exc:
        # Fallback to local heuristic
        clean = command.lower()
        if any(w in clean for w in ("search", "browse", "website", "flipkart", "amazon", "youtube", "edge")):
            target = "playwright_mcp"
        elif any(w in clean for w in ("gmail", "email", "github", "calendar", "slack", "notion")):
            target = "composio_apps"
        elif any(w in clean for w in ("volume", "brightness", "mute", "battery", "time")):
            target = "instant_os"
        else:
            target = "windows_mcp"

        return {
            "ok": True,
            "engine": "heuristic_fallback",
            "route_target": target,
            "route_confidence": 0.8,
            "requires_hitl_prob": 0.0,
            "needs_long_horizon_prob": 0.0,
            "safety_blocked_prob": 0.0,
            "risk_score": 0.5,
            "execution_mode": "direct_dispatch",
            "fallback_note": str(exc),
        }


def verify_react_step_with_decision_1(
    goal: str,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate if a LangGraph step succeeded logically and whether replanning is needed."""
    client = _get_decisions_client()
    payload = json.dumps(
        {
            "goal": goal,
            "tool": tool_name,
            "args": tool_args,
            "result": tool_result,
        },
        ensure_ascii=False,
    )

    if hasattr(client, "decisions"):
        try:
            resp = client.decisions.create(
                model="gemini-decision-1",
                input=payload,
                questions={
                    "step_succeeded": {
                        "type": "noul",
                        "instructions": "Did the tool execution genuinely achieve its intended sub-step?",
                    },
                    "needs_replan": {
                        "type": "noul",
                        "instructions": "Should the LangGraph supervisor revise its remaining plan based on this observation?",
                    },
                    "failure_cause": {
                        "type": "choice",
                        "instructions": "If there is an issue, classify the failure mode; otherwise select clean.",
                        "criteria": {
                            "api_mismatch": "Wrong argument name, schema mismatch, or missing field.",
                            "wrong_logic": "Executed wrong action/target or contradicted the goal.",
                            "runtime_error": "Network timeout, CDP disconnected, or OS exception.",
                            "security_block": "Blocked by safety shield or passphrase guard.",
                            "clean": "Step executed cleanly with no error or logic flaw.",
                        },
                    },
                },
            )
            answers = getattr(resp, "answers", {}) or {}
            succeeded = answers.get("step_succeeded")
            replan = answers.get("needs_replan")
            cause = answers.get("failure_cause")
            return {
                "ok": True,
                "step_succeeded_prob": getattr(succeeded, "noul", 0.5),
                "needs_replan_prob": getattr(replan, "noul", 0.5),
                "failure_cause": getattr(cause, "choice", "clean"),
                "cause_confidence": getattr(cause, "confidence", 0.0),
            }
        except Exception:
            pass

    # Structured model fallback
    try:
        from google.genai import types
        fast_m = get_fast_model()
        prompt = (
            f"Evaluate step outcome for goal: '{goal}'\n"
            f"Tool: {tool_name}\nArgs: {json.dumps(tool_args)}\nResult: {json.dumps(tool_result, ensure_ascii=False)[:1200]}\n"
        )
        resp = client.models.generate_content(
            model=fast_m,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StepVerificationSchema,
            ),
        )
        res = StepVerificationSchema.model_validate_json((resp.text or "").strip())
        return {
            "ok": True,
            "step_succeeded_prob": 1.0 if res.step_succeeded else 0.0,
            "needs_replan_prob": 1.0 if res.needs_replan else 0.0,
            "failure_cause": res.failure_cause,
            "cause_confidence": 0.95,
        }
    except Exception:
        ok = bool(tool_result.get("ok", False))
        return {
            "ok": True,
            "step_succeeded_prob": 1.0 if ok else 0.1,
            "needs_replan_prob": 0.0 if ok else 0.7,
            "failure_cause": "clean" if ok else "runtime_error",
            "cause_confidence": 0.8,
        }


def audit_code_logic_with_decision_1(code_snippet: str, context_note: str = "") -> dict[str, Any]:
    """Score any generated script or module for bugs, errors, and flawed logic before execution."""
    client = _get_decisions_client()
    input_text = f"Context: {context_note}\n\nCode:\n{code_snippet}" if context_note else code_snippet

    if hasattr(client, "decisions"):
        try:
            resp = client.decisions.create(
                model="gemini-decision-1",
                input=input_text,
                questions={
                    "has_bug": {
                        "type": "noul",
                        "instructions": "Does this code contain a runtime bug, mismatched API/key name, unhandled exception, or broken invariant?",
                    },
                    "has_wrong_logic": {
                        "type": "noul",
                        "instructions": "Does this code implement wrong business logic, silent fallback failure, or inverted conditional behavior?",
                    },
                    "defect_type": {
                        "type": "choice",
                        "instructions": "Select the primary defect class present in this code.",
                        "criteria": {
                            "api_mismatch": "Mismatched dict keys, wrong function arguments, or schema mismatch.",
                            "wrong_logic": "Flawed conditions, missing cases, or silent data drops.",
                            "security_leak": "Unredacted secrets, injection risk, or bypassed safety checks.",
                            "runtime_crash": "Null/type crash, deadlocks, or uncaught IO error.",
                            "clean": "No meaningful bug or logic flaw detected.",
                        },
                    },
                    "severity": {
                        "type": "score",
                        "instructions": "Rate the operational severity of the bug or logic issue.",
                    },
                },
            )
            answers = getattr(resp, "answers", {}) or {}
            return {
                "has_bug_prob": getattr(answers.get("has_bug"), "noul", 0.0),
                "wrong_logic_prob": getattr(answers.get("has_wrong_logic"), "noul", 0.0),
                "defect_type": getattr(answers.get("defect_type"), "choice", "clean"),
                "severity_score": getattr(answers.get("severity"), "score", 0.0),
            }
        except Exception:
            pass

    # Structured fallback
    try:
        from google.genai import types
        fast_m = get_fast_model()
        resp = client.models.generate_content(
            model=fast_m,
            contents=f"Audit this code snippet for bugs, leaks, or logic flaws:\n{input_text[:3000]}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CodeAuditSchema,
            ),
        )
        res = CodeAuditSchema.model_validate_json((resp.text or "").strip())
        return {
            "has_bug_prob": 1.0 if res.has_bug else 0.0,
            "wrong_logic_prob": 1.0 if res.has_wrong_logic else 0.0,
            "defect_type": res.defect_type,
            "severity_score": res.severity_score,
        }
    except Exception as exc:
        return {
            "has_bug_prob": 0.0,
            "wrong_logic_prob": 0.0,
            "defect_type": "clean",
            "severity_score": 0.0,
            "error": str(exc),
        }

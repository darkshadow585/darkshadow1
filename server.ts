/**
 * DarkShadow Upgraded Full-Stack Server (Express + Vite Middleware / Static Production)
 * - Fixed Express 5 SPA fallback (zero PathError crash)
 * - Complete 12-file Drop-In Windows Upgrade ZIP (never overwrites .env, memory.db, contacts.json!)
 * - Session-scoped conversation history (prevents multi-tab context leakage)
 * - Hybrid Gemini Tool Calling + Live Google Search Grounding + Automatic 503 Fallback
 */

import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";
import type { Request, Response } from "express";
import { handleDeterministicAutomation } from "./server/automation.ts";
import {
  generateHybridAgentReply,
  getCasualModel,
  getIntelligentModel,
  getTtsModel,
  getTtsVoice,
  isGeminiConfigured,
  synthesizeSpeechWav,
} from "./server/gemini.ts";
import type { ConversationTurn, PersonaMode } from "./server/gemini.ts";
import { handleMemoryCommand, MemoryStore } from "./server/memory.ts";
import {
  CAMERA_BLOCKED_MESSAGE,
  ensureCaptainAddress,
  isDangerousTerminalCommand,
  isPaymentOrCheckoutIntent,
  isPhysicalCameraIntent,
  PAYMENT_BLOCKED_MESSAGE,
  speechFriendlyText,
} from "./server/safety.ts";
import { buildZipBuffer } from "./server/zip.ts";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT || 3000);
const MAX_HISTORY_TURNS = Math.max(2, Number(process.env.DARKSHADOW_HISTORY_TURNS || 10));
const MAX_SESSIONS = 40;

const memoryStore = new MemoryStore();
const sessionHistories = new Map<string, ConversationTurn[]>();
let lastModelUsed: string | null = null;
let totalInputTokens = 0;
let totalOutputTokens = 0;

function getSessionHistory(sessionId: string): ConversationTurn[] {
  const key = sessionId.slice(0, 64) || "default";
  let hist = sessionHistories.get(key);
  if (!hist) {
    if (sessionHistories.size >= MAX_SESSIONS) {
      const oldestKey = sessionHistories.keys().next().value;
      if (oldestKey) sessionHistories.delete(oldestKey);
    }
    hist = [];
    sessionHistories.set(key, hist);
  }
  return hist;
}

const DESKTOP_UPGRADE_FILES: Record<string, { contentType: string; summary: string }> = {
  "reasoning_engine.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "[B-1 & B-2] LangGraph Cyclic Planner + Human-in-the-Loop interrupt() + Pydantic-AI Type-Safe Schemas",
  },
  "windows_uia_agent.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "[A-3] Native Windows 11 UI Automation Accessibility Tree (Windows-MCP / Windows-Use style, DPI-proof)",
  },
  "autonomous_web_agent.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "[A-1 & A-2] Playwright Accessibility Tree CDP + browser-use Autonomous Multi-Step Edge Agent",
  },
  "living_memory_v3.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "[C-All] Mem0 Living Facts + Letta-Style Editable Core RAM Blocks + Existing SQLite Fallback",
  },
  "mcp_client_hub.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "[D-1] Official Universal MCP Python SDK Client Hub with Centralized Safety Shield",
  },
  "mcp_servers.json": {
    contentType: "application/json; charset=utf-8",
    summary: "[D-1 & A-1/A-3] Plug-and-play MCP config for @playwright/mcp, windows-mcp & filesystem",
  },
  "voice_pipeline.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "[D-2] Adaptive Noise-Floor VAD + Multilingual Semantic Turn Detection & Smart Barge-In",
  },
  "gemini_live_engine.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Non-blocking Gemini 3.8 Live Engine wired with SemanticVoicePipeline & LivingMemoryV3",
  },
  "mcp_bridge.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Unified 16-Tool FastMCP Registry integrating LangGraph, UIA, browser-use, MCP Hub & Core RAM",
  },
  "browser_agent.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Microsoft Edge CDP + DOM interactive click/type/play agent for active tabs",
  },
  "memory_engine.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Contradiction-free SQLite Semantic Memory + episodic archive (backwards-compatible with memory.db)",
  },
  "windows_tools.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Clean verified Win32/pycaw/psutil primitives, allowlisted app launcher & refined safety shields",
  },
  "darkshadow_desktop.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Upgraded PySide6 desktop overlay wired to particle_engine_v2.html, personas & episodic turns",
  },
  "particle_engine_v2.html": {
    contentType: "text/html; charset=utf-8",
    summary: "Next-gen 7,000-particle WebGL2 core with zero-tilt solar spin, standby dim fix & magnetic cursor",
  },
  "sentinel_monitor.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Background sentinel for due reminders and low-battery alerts",
  },
  "error_tracker.py": {
    contentType: "text/x-python; charset=utf-8",
    summary: "Centralized JSONL runtime error logger wired directly into tool & Live WebSocket handlers",
  },
  "windows_requirements.txt": {
    contentType: "text/plain; charset=utf-8",
    summary: "Complete Python requirements (langgraph, pydantic-ai, browser-use, uiautomation, mem0ai, mcp)",
  },
  "Launch_Edge_Debug.bat": {
    contentType: "application/x-bat; charset=utf-8",
    summary: "One-click launcher for Microsoft Edge with CDP port 9222 enabled",
  },
  "update_install_deps.bat": {
    contentType: "application/x-bat; charset=utf-8",
    summary: "Updates all Next-Gen packages safely inside your existing .venv without touching .env or memory.db",
  },
  "UPGRADE_README.txt": {
    contentType: "text/plain; charset=utf-8",
    summary: "Safe drop-in merge guide for the complete A + B + C + D Pure Python suite",
  },
};

function buildHelpText(): string {
  return [
    "Captain, DarkShadow Upgraded Commands:",
    "• Natural Tool Calling: '10 minute baad paani peene ka remind karo', 'remember I prefer Edge', 'YouTube par Arijit Singh chalao'",
    "• Live Grounding: Ask weather, latest news, scores, or prices (auto Google Search citations)",
    "• Persona Switch: Use Standard, Bhojpuri, Witty, or Beedu mode anytime",
    "• /status — runtime, model fallback & shield status",
    "• /memories, /notes, /reminders — inspect saved vault",
    "• /clear — clear current session context",
  ].join("\n");
}

function buildStatusSummary(sessionId: string): string {
  const hist = getSessionHistory(sessionId);
  return [
    `Models: primary=${getIntelligentModel()} -> fallback=${getCasualModel()}`,
    `Last model: ${lastModelUsed ?? "none yet"} | Tokens: ${totalInputTokens + totalOutputTokens} (in=${totalInputTokens}, out=${totalOutputTokens})`,
    `Tool Engine: Hybrid Google Search + Function Calling (multi-turn verified)`,
    `Voice TTS: ${getTtsModel()} (${getTtsVoice()}) + Browser Web Speech fallback`,
    `Session turns: ${hist.length}/${MAX_HISTORY_TURNS} | Memories: ${memoryStore.listItems().length} | Pending reminders: ${memoryStore.listPendingReminders().length}`,
    "Shields: Payment Exclusion ACTIVE | Zero-Camera Privacy ACTIVE | Shell Injection Shield ACTIVE",
  ].join("\n");
}

async function startServer() {
  const app = express();
  app.use(express.json({ limit: "1mb" }));

  // Public static assets
  app.use("/assets", express.static(path.join(__dirname, "public", "assets")));

  // List available drop-in desktop upgrade files
  app.get("/api/desktop-files", (_req: Request, res: Response) => {
    const dir = path.join(__dirname, "desktop_python");
    const files = Object.entries(DESKTOP_UPGRADE_FILES)
      .filter(([name]) => fs.existsSync(path.join(dir, name)))
      .map(([name, meta]) => ({
        name,
        summary: meta.summary,
        bytes: fs.statSync(path.join(dir, name)).size,
      }));
    res.json({
      zipUrl: "/api/desktop-files/DarkShadow-Upgrade-Pack.zip",
      untouchedFiles: [".env", ".venv/", ".darkshadow/memory.db", "contacts.json"],
      files,
    });
  });

  // 1-Click Drop-In Upgrade Pack ZIP (NEVER contains .env, memory.db, or contacts.json)
  app.get("/api/desktop-files/DarkShadow-Upgrade-Pack.zip", (_req: Request, res: Response) => {
    const dir = path.join(__dirname, "desktop_python");
    const entries = Object.keys(DESKTOP_UPGRADE_FILES)
      .filter((name) => fs.existsSync(path.join(dir, name)))
      .map((name) => ({
        name: `DarkShadow-Upgrade/${name}`,
        data: fs.readFileSync(path.join(dir, name)),
      }));
    const zip = buildZipBuffer(entries);
    res.setHeader("Content-Type", "application/zip");
    res.setHeader("Content-Disposition", 'attachment; filename="DarkShadow-Upgrade-Pack.zip"');
    res.send(zip);
  });

  // Individual desktop file download or preview
  app.get("/api/desktop-files/:filename", (req: Request, res: Response) => {
    const filename = String(req.params.filename || "");
    const meta = DESKTOP_UPGRADE_FILES[filename];
    if (!meta) {
      res.status(404).json({ error: "File not found" });
      return;
    }
    const filePath = path.join(__dirname, "desktop_python", filename);
    if (!fs.existsSync(filePath)) {
      res.status(404).json({ error: "File missing on disk" });
      return;
    }
    res.setHeader("Content-Type", meta.contentType);
    if (req.query.preview !== "1") {
      res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    }
    res.sendFile(filePath);
  });

  app.get("/api/status", (req: Request, res: Response) => {
    const sessionId = String(req.query.sessionId || "default");
    const hist = getSessionHistory(sessionId);
    res.json({
      geminiConfigured: isGeminiConfigured(),
      intelligentModel: getIntelligentModel(),
      casualModel: getCasualModel(),
      lastModelUsed,
      ttsModel: getTtsModel(),
      ttsVoice: getTtsVoice(),
      searchMode: "hybrid_google_search_tools",
      historyTurns: hist.length,
      maxHistoryTurns: MAX_HISTORY_TURNS,
      memoryCount: memoryStore.listItems().length,
      pendingReminderCount: memoryStore.listPendingReminders().length,
      summary: buildStatusSummary(sessionId),
    });
  });

  app.get("/api/reminders", (_req: Request, res: Response) => {
    const due = memoryStore.popDueReminders();
    const pending = memoryStore.listPendingReminders();
    res.json({ pending, due });
  });

  app.delete("/api/reminders/:id", (req: Request, res: Response) => {
    const id = Number.parseInt(String(req.params.id), 10);
    if (Number.isNaN(id)) {
      res.status(400).json({ error: "Invalid reminder id" });
      return;
    }
    const result = memoryStore.deleteReminder(id);
    res.json({ result, pending: memoryStore.listPendingReminders() });
  });

  app.get("/api/memories", (_req: Request, res: Response) => {
    res.json({ items: memoryStore.listItems() });
  });

  app.delete("/api/memories/:id", (req: Request, res: Response) => {
    const id = Number.parseInt(String(req.params.id), 10);
    if (Number.isNaN(id)) {
      res.status(400).json({ error: "Invalid memory id" });
      return;
    }
    const result = memoryStore.forgetItem(id);
    res.json({ result, items: memoryStore.listItems() });
  });

  app.post("/api/clear", (req: Request, res: Response) => {
    const sessionId = typeof req.body?.sessionId === "string" ? req.body.sessionId : "default";
    sessionHistories.set(sessionId.slice(0, 64) || "default", []);
    const msg = "Captain, is session ka conversation context clear kar diya hai.";
    res.json({
      displayText: msg,
      speechText: speechFriendlyText(msg),
      intent: "clear",
    });
  });

  app.post("/api/tts", async (req: Request, res: Response) => {
    const text = typeof req.body?.text === "string" ? req.body.text.trim() : "";
    if (!text) {
      res.status(400).json({ error: "Text is required" });
      return;
    }
    try {
      const audioBase64 = await synthesizeSpeechWav(text);
      if (!audioBase64) {
        res.status(503).json({ error: "Cloud TTS unavailable" });
        return;
      }
      res.json({ audioBase64, mimeType: "audio/wav", voice: getTtsVoice() });
    } catch (err) {
      res.status(502).json({ error: err instanceof Error ? err.message : "TTS failed" });
    }
  });

  app.post("/api/chat", async (req: Request, res: Response) => {
    const rawMessage = typeof req.body?.message === "string" ? req.body.message.trim() : "";
    const privacyMode = Boolean(req.body?.privacyMode);
    const sessionId = typeof req.body?.sessionId === "string" ? req.body.sessionId : "default";
    const personaRaw = typeof req.body?.persona === "string" ? req.body.persona : "default";
    const persona: PersonaMode = (["default", "bhojpuri", "witty", "beedu"].includes(personaRaw)
      ? personaRaw
      : "default") as PersonaMode;

    if (!rawMessage) {
      res.status(400).json({ error: "Message is required" });
      return;
    }

    // 1. Unbypassable Hard Safety Shields (zero LLM tokens spent)
    if (isPaymentOrCheckoutIntent(rawMessage)) {
      const displayText = ensureCaptainAddress(PAYMENT_BLOCKED_MESSAGE);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "payment_blocked",
        suggestions: ["Compare options instead", "/help"],
        sources: [],
        toolTrace: [],
        error: "payment_blocked",
      });
      return;
    }

    if (isPhysicalCameraIntent(rawMessage)) {
      const displayText = ensureCaptainAddress(CAMERA_BLOCKED_MESSAGE);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "camera_blocked",
        suggestions: ["/status", "/help"],
        sources: [],
        toolTrace: [],
        error: "camera_blocked",
      });
      return;
    }

    const terminalCheck = isDangerousTerminalCommand(rawMessage);
    if (terminalCheck.blocked) {
      const displayText = ensureCaptainAddress(terminalCheck.reason);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "security_blocked",
        suggestions: [],
        sources: [],
        toolTrace: [],
        error: "security_blocked",
      });
      return;
    }

    const history = getSessionHistory(sessionId);

    // 2. Core Slash Commands
    const lower = rawMessage.toLowerCase();
    if (lower === "/help") {
      res.json({
        displayText: buildHelpText(),
        speechText: speechFriendlyText("Captain, commands list screen par dikha di hai."),
        intent: "help",
        suggestions: ["/status", "/memories", "/reminders"],
        sources: [],
        toolTrace: [],
      });
      return;
    }

    if (lower === "/clear") {
      history.length = 0;
      const displayText = "Captain, is session ki conversation history clear kar di hai.";
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "clear",
        suggestions: ["Namaste DarkShadow", "/status"],
        sources: [],
        toolTrace: [],
        clearHistory: true,
      });
      return;
    }

    if (lower === "/status") {
      const displayText = ensureCaptainAddress(buildStatusSummary(sessionId));
      res.json({
        displayText,
        speechText: speechFriendlyText("Captain, DarkShadow status report ready hai."),
        intent: "status",
        suggestions: ["/help", "/reminders"],
        sources: [],
        toolTrace: [],
      });
      return;
    }

    // 3. Explicit Slash Memory Commands
    const activeMemory = privacyMode ? null : memoryStore;
    const memoryRes = handleMemoryCommand(rawMessage, activeMemory);
    if (memoryRes) {
      const displayText = ensureCaptainAddress(memoryRes.message);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: memoryRes.action,
        suggestions: ["/memories", "/reminders"],
        sources: [],
        toolTrace: [
          {
            name: `slash:${memoryRes.action}`,
            args: { command: rawMessage },
            ok: memoryRes.success,
            summary: memoryRes.message.slice(0, 120),
          },
        ],
        reminders: memoryStore.listPendingReminders(),
        error: memoryRes.error,
      });
      return;
    }

    // 4. Instant Deterministic Local Commands & Sandbox Boundaries
    const autoRes = handleDeterministicAutomation(rawMessage);
    if (autoRes) {
      const displayText = ensureCaptainAddress(autoRes.message);
      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: autoRes.action,
        suggestions: [],
        sources: [],
        toolTrace: [
          {
            name: autoRes.action,
            args: { input: rawMessage },
            ok: autoRes.success,
            summary: autoRes.message.slice(0, 120),
          },
        ],
        actionLink: autoRes.actionLink,
        error: autoRes.error,
      });
      return;
    }

    // 5. Hybrid Gemini Agent (Google Search Grounding + Custom Function Calling + Auto 503 Fallback)
    if (!isGeminiConfigured()) {
      const displayText =
        "Captain, GEMINI_API_KEY configured nahi mila. Settings > Secrets mein apni Gemini API key check kijiye; local commands (/help, /status, /memories, /reminders) abhi bhi available hain.";
      res.status(503).json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: "configuration",
        suggestions: ["/help", "/status"],
        sources: [],
        toolTrace: [],
        error: "missing_api_key",
      });
      return;
    }

    try {
      const recalled = activeMemory ? activeMemory.recallRelevant(rawMessage, 4) : [];
      const reply = await generateHybridAgentReply({
        message: rawMessage,
        history,
        recalledMemories: recalled,
        memoryStore: activeMemory,
        persona,
      });

      const displayText = ensureCaptainAddress(reply.text);
      lastModelUsed = reply.modelUsed;
      totalInputTokens += reply.inputTokens;
      totalOutputTokens += reply.outputTokens;

      history.push({ userText: rawMessage, assistantText: displayText });
      if (history.length > MAX_HISTORY_TURNS) {
        history.splice(0, history.length - MAX_HISTORY_TURNS);
      }

      res.json({
        displayText,
        speechText: speechFriendlyText(displayText),
        intent: reply.toolTrace.length > 0 ? "agent_tool_call" : "chat",
        suggestions:
          reply.sources.length > 0
            ? ["Aur detail batao", "Hindi mein samjhao"]
            : ["Save as note", "Set 10 min reminder"],
        sources: reply.sources,
        toolTrace: reply.toolTrace,
        actionLink: reply.actionLink,
        modelUsed: reply.modelUsed,
        reminders: memoryStore.listPendingReminders(),
      });
    } catch (err) {
      const rawError = err instanceof Error ? err.message : String(err);
      let friendly =
        "Captain, AI engine se connect karte waqt error aaya. Kripya thodi der baad dobara try kijiye.";
      if (/API_KEY_INVALID|PERMISSION_DENIED|403|401/i.test(rawError)) {
        friendly =
          "Captain, Gemini API key invalid ya unauthorized lag rahi hai. Kripya Settings > Secrets panel mein key check kijiye.";
      } else if (/RESOURCE_EXHAUSTED|429/i.test(rawError)) {
        friendly =
          "Captain, Gemini API rate limit hit ho gayi hai. Ek minute ruk kar dobara try kijiye.";
      }
      res.status(502).json({
        displayText: friendly,
        speechText: speechFriendlyText(friendly),
        intent: "error",
        suggestions: ["Retry"],
        sources: [],
        toolTrace: [],
        error: rawError,
      });
    }
  });

  // Frontend middleware (Vite in dev, dist/ static in production with Express 5-safe SPA fallback)
  if (process.env.NODE_ENV === "production") {
    const distDir = path.join(__dirname, "dist");
    app.use(express.static(distDir));
    app.use((_req: Request, res: Response) => {
      res.sendFile(path.join(distDir, "index.html"));
    });
  } else {
    const { createServer: createViteServer } = await import("vite");
    const vite = await createViteServer({
      server: { middlewareMode: true, hmr: false },
      appType: "spa",
    });
    app.use(vite.middlewares);
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`DarkShadow Upgraded Web Server listening on http://0.0.0.0:${PORT}`);
  });
}

startServer().catch((err) => {
  console.error("Failed to start DarkShadow server:", err);
  process.exit(1);
});

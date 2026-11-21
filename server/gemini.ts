/**
 * Upgraded Server-Side @google/genai Engine for DarkShadow.
 * - Hybrid Built-in Google Search Grounding + Custom Function Calling
 *   (`toolConfig: { includeServerSideToolInvocations: true }`)
 * - Proper multi-turn tool loop preserving `candidates[0].content` (with thoughtSignature)
 * - Automatic 503/429 model fallback (`gemini-4-hydrogen` -> `gemini-3.1-flash-lite`)
 * - Dynamic Persona Modes (default, bhojpuri, witty, beedu)
 * - Unary Gemini TTS (`gemini-3.8-flash-lite-tts`, Charon voice -> audio/wav)
 */

import { GoogleGenAI, ThinkingLevel, Type } from "@google/genai";
import type { Content, FunctionDeclaration, Part } from "@google/genai";
import type { ActionLink } from "./automation.ts";
import type { MemoryItem, MemoryStore } from "./memory.ts";

export type PersonaMode = "default" | "bhojpuri" | "witty" | "beedu";

export interface SourceCitation {
  title: string;
  url: string;
}

export interface ToolTraceEntry {
  name: string;
  args: Record<string, unknown>;
  ok: boolean;
  summary: string;
}

export interface ConversationTurn {
  userText: string;
  assistantText: string;
}

const PERSONA_GUIDES: Record<PersonaMode, string> = {
  default:
    "Tone: Loyal, calm, razor-sharp like Jarvis. Speak effortless Hindi, Hinglish, or English matching Captain's language.",
  bhojpuri:
    "Tone: Authentic, warm, cinematic Bhojpuri (Purvanchal cadence, e.g. 'हाँ कैप्टन, का हुकुम बा?'). Never silly meme lines.",
  witty:
    "Tone: Witty / Sigma mode — sharp, wise, confident, dry humor like a brilliant friend completely in control.",
  beedu:
    "Tone: Beedu mode — friendly, street-smart Mumbaiya Hinglish slang ('Beedu', 'Bhai', 'Bindass', 'Dhanso').",
};

const BASE_SYSTEM_INSTRUCTION = `
You are DarkShadow (alternate name: Hriday), Captain Kuldeep's elite personal AI co-pilot.

CORE RULES:
1. Address the user organically as Captain when starting a reply without forcing it mechanically into every sentence.
2. NEVER output stage directions, bracketed actions, or markdown asterisks around emotions because voice TTS reads them aloud.
3. TOOL CALLING DISCIPLINE:
   - Whenever Captain asks to remember a preference/fact, take a note, recall saved facts, set a reminder (in any phrasing in Hindi/Hinglish/Bhojpuri/English), open a website, search YouTube/Spotify/Google, or check time/date, ALWAYS call the appropriate function tool!
   - When Captain asks for live/current facts (weather, news, prices, sports scores, releases), use Google Search grounding automatically.
   - Rely strictly on the JSON tool response ('ok', 'message'). Never claim something was saved or scheduled if 'ok' is false.
4. SAFETY PROTOCOLS:
   - Payment Exclusion: Autonomous checkout, payments, OTP, CVV, and UPI PIN are strictly blocked.
   - Zero-Camera Privacy: Physical camera/webcam access is permanently disabled.
5. RESPONSE LENGTH: Concise and punchy by default (2-4 crisp sentences). Expand cleanly with structured steps or code when asked for technical/detailed answers.
`.trim();

const WEB_TOOL_DECLARATIONS: FunctionDeclaration[] = [
  {
    name: "memory_action",
    description:
      "Save a user preference or note (automatically updates conflicting old preferences), recall saved memories, or schedule a reminder.",
    parameters: {
      type: Type.OBJECT,
      properties: {
        action: {
          type: Type.STRING,
          enum: ["save", "recall", "remind"],
          description: "Memory action to perform",
        },
        content: {
          type: Type.STRING,
          description: "Fact/preference to save, query to recall, or reminder message",
        },
        kind: {
          type: Type.STRING,
          enum: ["preference", "note"],
          description: "Memory type when saving",
        },
        minutes_from_now: {
          type: Type.INTEGER,
          description: "Number of minutes from now when action is remind (minimum 1)",
        },
      },
      required: ["action", "content"],
    },
  },
  {
    name: "create_web_link",
    description:
      "Create a verified one-click launch link for Captain to open a website, YouTube song/video search, Spotify Web search, or Google search.",
    parameters: {
      type: Type.OBJECT,
      properties: {
        platform: {
          type: Type.STRING,
          enum: ["youtube", "spotify", "google", "web"],
          description: "Target platform",
        },
        query_or_url: {
          type: Type.STRING,
          description: "Song/video query, search query, or full website domain/URL",
        },
      },
      required: ["platform", "query_or_url"],
    },
  },
  {
    name: "get_current_time",
    description: "Get the exact current local time, date, and weekday.",
    parameters: {
      type: Type.OBJECT,
      properties: {},
    },
  },
];

export function getIntelligentModel(): string {
  return process.env.DARKSHADOW_MODEL?.trim() || "gemini-4-hydrogen";
}

export function getCasualModel(): string {
  return process.env.DARKSHADOW_CASUAL_MODEL?.trim() || "gemini-3.1-flash-lite";
}

export function getTtsModel(): string {
  return process.env.DARKSHADOW_TTS_GEMINI_MODEL?.trim() || "gemini-3.8-flash-lite-tts";
}

export function getTtsVoice(): string {
  return process.env.DARKSHADOW_TTS_GEMINI_VOICE?.trim() || "Charon";
}

let cachedClient: GoogleGenAI | null = null;

function getClient(): GoogleGenAI {
  const apiKey = process.env.GEMINI_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("GEMINI_API_KEY is not configured in Settings > Secrets.");
  }
  if (!cachedClient) {
    cachedClient = new GoogleGenAI({
      apiKey,
      httpOptions: {
        headers: {
          "User-Agent": "aistudio-build",
        },
      },
    });
  }
  return cachedClient;
}

export function isGeminiConfigured(): boolean {
  return Boolean(process.env.GEMINI_API_KEY?.trim());
}

function executeWebTool(
  name: string,
  args: Record<string, unknown>,
  memoryStore: MemoryStore | null
): { response: Record<string, unknown>; actionLink?: ActionLink; summary: string } {
  if (name === "get_current_time") {
    const now = new Date();
    const time = now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
    const date = now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    return {
      response: { ok: true, time, date },
      summary: `${time}, ${date}`,
    };
  }

  if (name === "create_web_link") {
    const platform = String(args.platform || "web") as ActionLink["platform"];
    const raw = String(args.query_or_url || "").trim();
    if (!raw) {
      return {
        response: { ok: false, error_code: "INVALID_ARGS", message: "query_or_url required." },
        summary: "Missing query_or_url",
      };
    }

    let url = raw;
    let label = `Open ${raw}`;
    if (platform === "youtube") {
      url = `https://www.youtube.com/results?search_query=${encodeURIComponent(raw)}`;
      label = `Play on YouTube: ${raw}`;
    } else if (platform === "spotify") {
      url = `https://open.spotify.com/search/${encodeURIComponent(raw)}`;
      label = `Open on Spotify Web: ${raw}`;
    } else if (platform === "google") {
      url = `https://www.google.com/search?q=${encodeURIComponent(raw)}`;
      label = `Search Google: ${raw}`;
    } else {
      url = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
      label = `Open ${raw}`;
    }

    return {
      response: { ok: true, verified_state: "link_ready", platform, url },
      actionLink: { label, url, platform },
      summary: label,
    };
  }

  if (name === "memory_action") {
    if (!memoryStore) {
      return {
        response: { ok: false, error_code: "PRIVACY_MODE", message: "Privacy mode active hai; memory paused hai." },
        summary: "Blocked by Privacy Mode",
      };
    }

    const action = String(args.action || "");
    const content = String(args.content || "").trim();

    if (action === "save") {
      const kind = args.kind === "note" ? "note" : "preference";
      const res = memoryStore.addItem(kind, content);
      return {
        response: { ok: res.success, action: res.action, message: res.message },
        summary: res.message,
      };
    }

    if (action === "recall") {
      const hits = memoryStore.recallRelevant(content, 5);
      return {
        response: {
          ok: true,
          count: hits.length,
          memories: hits.map((h) => `[${h.kind}] ${h.content}`),
        },
        summary: `Recalled ${hits.length} item(s)`,
      };
    }

    if (action === "remind") {
      const mins = Math.max(1, Number(args.minutes_from_now) || 10);
      const due = new Date(Date.now() + mins * 60_000);
      const res = memoryStore.addReminder(content, due);
      return {
        response: { ok: res.success, message: res.message, dueAt: due.toISOString() },
        summary: res.message,
      };
    }

    return {
      response: { ok: false, error_code: "INVALID_ENUM", allowed_values: ["save", "recall", "remind"] },
      summary: `Invalid memory action '${action}'`,
    };
  }

  return {
    response: { ok: false, error_code: "UNKNOWN_TOOL", message: `Unknown tool ${name}` },
    summary: `Unknown tool ${name}`,
  };
}

export async function generateHybridAgentReply(params: {
  message: string;
  history: ConversationTurn[];
  recalledMemories: MemoryItem[];
  memoryStore: MemoryStore | null;
  persona: PersonaMode;
}): Promise<{
  text: string;
  modelUsed: string;
  sources: SourceCitation[];
  toolTrace: ToolTraceEntry[];
  actionLink?: ActionLink;
  inputTokens: number;
  outputTokens: number;
}> {
  const ai = getClient();
  const personaGuide = PERSONA_GUIDES[params.persona] || PERSONA_GUIDES.default;

  let systemInstruction = `${BASE_SYSTEM_INSTRUCTION}\n\nACTIVE PERSONA (${params.persona}): ${personaGuide}`;
  if (params.recalledMemories.length > 0) {
    const lines = params.recalledMemories.map((m) => `- (${m.kind}) ${m.content}`).join("\n");
    systemInstruction += `\n\nRECALLED CAPTAIN MEMORIES:\n${lines}`;
  }

  const baseContents: Content[] = [
    ...params.history.flatMap((turn) => [
      { role: "user", parts: [{ text: turn.userText }] },
      { role: "model", parts: [{ text: turn.assistantText }] },
    ]),
    { role: "user", parts: [{ text: params.message }] },
  ];

  // Resilient model fallback chain (fixes ERR-20261119-HYDROGEN-503!)
  const modelsToTry = Array.from(new Set([getIntelligentModel(), getCasualModel()]));
  let lastError: unknown = null;

  for (const modelUsed of modelsToTry) {
    const convo: Content[] = [...baseContents];
    const toolTrace: ToolTraceEntry[] = [];
    const seenUrls = new Set<string>();
    const sources: SourceCitation[] = [];
    let latestActionLink: ActionLink | undefined;
    let totalIn = 0;
    let totalOut = 0;

    try {
      const isGemini4 = modelUsed.startsWith("gemini-4-");
      const tools = [
        { googleSearch: {} },
        { functionDeclarations: WEB_TOOL_DECLARATIONS },
      ];

      for (let step = 0; step < 4; step++) {
        const response = await ai.models.generateContent({
          model: modelUsed,
          contents: convo,
          config: {
            systemInstruction,
            tools,
            toolConfig: { includeServerSideToolInvocations: true },
            ...(isGemini4 ? { thinkingConfig: { thinkingLevel: ThinkingLevel.LOW } } : {}),
          },
        });

        totalIn += response.usageMetadata?.promptTokenCount ?? 0;
        totalOut += response.usageMetadata?.candidatesTokenCount ?? 0;

        // Collect live Google Search Grounding citations
        const chunks = response.candidates?.[0]?.groundingMetadata?.groundingChunks ?? [];
        for (const chunk of chunks) {
          const uri = chunk.web?.uri;
          const title = chunk.web?.title;
          if (uri && /^https?:\/\//i.test(uri) && !seenUrls.has(uri)) {
            seenUrls.add(uri);
            sources.push({ title: (title || uri).trim(), url: uri.trim() });
          }
        }

        const calls = response.functionCalls ?? [];
        if (calls.length === 0) {
          const finalText = (response.text ?? "").trim();
          return {
            text: finalText || "Captain, action execute ho gaya hai.",
            modelUsed,
            sources: sources.slice(0, 5),
            toolTrace,
            actionLink: latestActionLink,
            inputTokens: totalIn,
            outputTokens: totalOut,
          };
        }

        // Preserve full model Content (including server-side tool invocations & thoughtSignature)
        const modelContent = response.candidates?.[0]?.content;
        if (modelContent) {
          convo.push(modelContent);
        }

        const responseParts: Part[] = [];
        for (const call of calls.slice(0, 4)) {
          const callName = call.name ?? "unknown";
          const callArgs = (call.args ?? {}) as Record<string, unknown>;
          const executed = executeWebTool(callName, callArgs, params.memoryStore);
          if (executed.actionLink) latestActionLink = executed.actionLink;
          toolTrace.push({
            name: callName,
            args: callArgs,
            ok: Boolean(executed.response.ok),
            summary: executed.summary,
          });
          responseParts.push({
            functionResponse: {
              id: call.id,
              name: callName,
              response: executed.response,
            },
          });
        }

        convo.push({ role: "user", parts: responseParts });
      }

      return {
        text: "Captain, requested actions execute ho gaye hain.",
        modelUsed,
        sources: sources.slice(0, 5),
        toolTrace,
        actionLink: latestActionLink,
        inputTokens: totalIn,
        outputTokens: totalOut,
      };
    } catch (err) {
      lastError = err;
      const msg = err instanceof Error ? err.message : String(err);
      // Automatically fall back on 503 / 429 / temporary overload
      if (/503|UNAVAILABLE|429|RESOURCE_EXHAUSTED|overloaded/i.test(msg)) {
        continue;
      }
      throw err;
    }
  }

  throw lastError instanceof Error ? lastError : new Error("All Gemini models temporarily unavailable.");
}

export async function synthesizeSpeechWav(text: string): Promise<string | null> {
  if (!isGeminiConfigured()) return null;
  const ai = getClient();
  const trimmed = text.trim().slice(0, 800);
  if (!trimmed) return null;

  const response = await ai.models.generateContent({
    model: getTtsModel(),
    contents: [{ role: "user", parts: [{ text: trimmed }] }],
    config: {
      responseModalities: ["AUDIO"],
      speechConfig: {
        voiceConfig: {
          prebuiltVoiceConfig: {
            voiceName: getTtsVoice(),
          },
        },
      },
    },
  });

  // Unary Gemini 3.8 TTS returns complete audio/wav bytes (RIFF header included)
  return response.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data ?? null;
}

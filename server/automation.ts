/**
 * Deterministic safe local/web slash and instant commands.
 * Natural-language memory, reminders, web links, and live search now route
 * through Gemini's Hybrid Function Calling + Google Search Grounding in server/gemini.ts!
 */

export interface ActionLink {
  label: string;
  url: string;
  platform: "web" | "youtube" | "google" | "spotify";
}

export interface AutomationResult {
  success: boolean;
  action: string;
  message: string;
  actionLink?: ActionLink;
  error?: string;
}

export function handleDeterministicAutomation(message: string): AutomationResult | null {
  const cleaned = message.trim();
  if (!cleaned || cleaned.startsWith("/")) return null;

  if (/^(?:current\s+time|what(?:'s| is)\s+the\s+time|time\s+kya\s+hua|kitne\s+baje\s+hain|abhi\s+time\s+kya\s+hai)[?!.]*$/i.test(cleaned)) {
    const formatted = new Date().toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    });
    return { success: true, action: "current_time", message: `Abhi time ${formatted} hai.` };
  }

  if (/^(?:today'?s?\s+date|what(?:'s| is)\s+(?:today'?s?\s+)?date|aaj\s+kya\s+date\s+hai|aaj\s+ki\s+tarikh)[?!.]*$/i.test(cleaned)) {
    const formatted = new Date().toLocaleDateString("en-IN", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    });
    return { success: true, action: "todays_date", message: `Aaj ${formatted} hai.` };
  }

  if (/^(?:system\s+status|pc\s+status|status\s+check)[?!.]*$/i.test(cleaned)) {
    const mem = process.memoryUsage();
    const mb = (bytes: number) => `${Math.round(bytes / 1024 / 1024)} MB`;
    return {
      success: true,
      action: "system_status",
      message: `DarkShadow Web Core healthy hai — Node ${process.version}, Heap ${mb(mem.heapUsed)} / ${mb(mem.heapTotal)}, Uptime ${Math.floor(process.uptime())}s.`,
    };
  }

  // Honest boundary for Windows-native OS controls inside browser sandbox
  if (
    /^(?:set\s+volume|volume\s+(?:up|down)|awaz\s+(?:badhao|kam\s+karo)|mute|unmute|set\s+brightness|brightness\s+(?:up|down)|lock\s+(?:pc|screen|workstation)|screen\s+lock\s+karo)$/i.test(cleaned) ||
    /^open\s+(?:notepad|calculator|chrome|edge|vs\s*code|vscode|file\s+explorer|paint|windows\s+terminal|whatsapp)$/i.test(cleaned)
  ) {
    return {
      success: false,
      action: "desktop_only_boundary",
      message:
        "Yeh Windows 11 native OS control browser sandbox mein directly accessible nahi hai. Desktop par yeh command chalane ke liye upar 'Desktop Upgrade Pack' se upgraded Python files download kijiye.",
      error: "desktop_runtime_required",
    };
  }

  return null;
}

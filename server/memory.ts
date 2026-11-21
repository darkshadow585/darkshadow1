/**
 * Persistent Contradiction-Free Memory & Reminders Store.
 * Persists BOTH memories AND reminders to .darkshadow/ so nothing is lost on server restart.
 */

import fs from "node:fs";
import path from "node:path";
import { containsSensitiveData } from "./safety.ts";

export interface MemoryItem {
  id: number;
  kind: "preference" | "note";
  content: string;
  createdAt: string;
}

export interface ReminderItem {
  id: number;
  message: string;
  dueAt: string;
  createdAt: string;
  deliveredAt: string | null;
}

export interface MemoryCommandResult {
  success: boolean;
  action: string;
  message: string;
  error?: string;
}

const TOKEN_ALIASES: Record<string, string> = {
  favourite: "favorite",
  colour: "color",
  pasand: "favorite",
  pasandida: "favorite",
  dost: "friend",
  yaar: "friend",
  janamdin: "birthday",
  bday: "birthday",
};

const NEGATION_WORDS = new Set(["nahi", "not", "never", "mat", "hate", "dislike", "bilkul", "no"]);

const STOP_WORDS = new Set([
  "the", "this", "that", "what", "who", "when", "tell", "about",
  "hai", "hain", "kaun", "kon", "kya", "kab", "mera", "meri",
  "mere", "mujhe", "batao", "bata", "ye", "is", "are", "was",
]);

function normalizeContent(text: string): string {
  return text.toLowerCase().trim().replace(/\s+/g, " ");
}

function memoryTokens(text: string): Set<string> {
  const tokens = new Set<string>();
  const matches = normalizeContent(text).match(/[a-z0-9\u0900-\u097f]+/g) ?? [];
  for (const raw of matches) {
    const mapped = TOKEN_ALIASES[raw] ?? raw;
    if (mapped.length >= 2 && !STOP_WORDS.has(mapped)) {
      tokens.add(mapped);
    }
  }
  return tokens;
}

const DEFAULT_CAPTAIN_MEMORIES: MemoryItem[] = [
  {
    id: 1,
    kind: "preference",
    content: "Captain's full name is Kuldeep Sonkar and city is Prayagraj.",
    createdAt: "2026-09-03T14:12:31.000Z",
  },
  {
    id: 2,
    kind: "preference",
    content: "Captain prefers Microsoft Edge and reusing existing active browser tabs.",
    createdAt: "2026-09-06T05:15:29.000Z",
  },
  {
    id: 3,
    kind: "preference",
    content: "Captain's favorite singer is Arijit Singh and prefers Lofi Chill Beats while coding.",
    createdAt: "2026-09-03T09:42:16.000Z",
  },
  {
    id: 4,
    kind: "preference",
    content: "Captain loves speaking in natural Hindi, Hinglish, and authentic Bhojpuri.",
    createdAt: "2026-09-11T12:11:30.000Z",
  },
];

export class MemoryStore {
  private items: MemoryItem[] = [];
  private reminders: ReminderItem[] = [];
  private nextItemId = 1;
  private nextReminderId = 1;

  constructor() {
    this.loadPersisted();
  }

  private getDataDir(): string {
    return path.join(process.cwd(), ".darkshadow");
  }

  private loadPersisted(): void {
    const dir = this.getDataDir();
    const memPath = path.join(dir, "user_memories.json");
    const remPath = path.join(dir, "user_reminders.json");

    try {
      if (fs.existsSync(memPath)) {
        const parsed = JSON.parse(fs.readFileSync(memPath, "utf-8"));
        if (Array.isArray(parsed) && parsed.length > 0) {
          this.items = parsed;
        }
      }
    } catch {
      // Fallback to default starter memories
    }

    if (this.items.length === 0) {
      this.items = [...DEFAULT_CAPTAIN_MEMORIES];
    }
    this.nextItemId = this.items.reduce((max, i) => Math.max(max, i.id || 0), 0) + 1;

    try {
      if (fs.existsSync(remPath)) {
        const parsedRem = JSON.parse(fs.readFileSync(remPath, "utf-8"));
        if (Array.isArray(parsedRem)) {
          this.reminders = parsedRem;
          this.nextReminderId =
            this.reminders.reduce((max, r) => Math.max(max, r.id || 0), 0) + 1;
        }
      }
    } catch {
      // Ignore corrupt reminder store
    }
  }

  private savePersisted(): void {
    try {
      const dir = this.getDataDir();
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(
        path.join(dir, "user_memories.json"),
        JSON.stringify(this.items, null, 2),
        "utf-8"
      );
      fs.writeFileSync(
        path.join(dir, "user_reminders.json"),
        JSON.stringify(this.reminders, null, 2),
        "utf-8"
      );
    } catch {
      // Ignore write errors in read-only sandboxes
    }
  }

  listItems(kind?: "preference" | "note"): MemoryItem[] {
    if (!kind) return [...this.items];
    return this.items.filter((i) => i.kind === kind);
  }

  listPendingReminders(): ReminderItem[] {
    return this.reminders
      .filter((r) => r.deliveredAt === null)
      .sort((a, b) => new Date(a.dueAt).getTime() - new Date(b.dueAt).getTime());
  }

  popDueReminders(now = new Date()): ReminderItem[] {
    const due: ReminderItem[] = [];
    const nowMs = now.getTime();
    let changed = false;
    for (const r of this.reminders) {
      if (r.deliveredAt === null && new Date(r.dueAt).getTime() <= nowMs) {
        r.deliveredAt = now.toISOString();
        due.push({ ...r });
        changed = true;
      }
    }
    if (changed) this.savePersisted();
    return due;
  }

  addItem(kind: "preference" | "note", rawContent: string): MemoryCommandResult {
    const content = rawContent.trim();
    if (!content) {
      return { success: false, action: "remember", message: "Empty content save nahi kiya.", error: "empty_content" };
    }
    if (content.length > 400) {
      return { success: false, action: "remember", message: "Content maximum 400 characters ka ho sakta hai.", error: "content_too_long" };
    }
    if (containsSensitiveData(content)) {
      return {
        success: false,
        action: "remember",
        message: "Sensitive data memory mein save nahi kiya. API keys, passwords, OTPs aur payment data blocked hain.",
        error: "sensitive_data",
      };
    }

    const normalized = normalizeContent(content);
    const exact = this.items.find(
      (i) => i.kind === kind && normalizeContent(i.content) === normalized
    );
    if (exact) {
      return {
        success: true,
        action: kind === "note" ? "note" : "remember",
        message: `Yeh ${kind} pehle se saved hai (#${exact.id}): ${exact.content}`,
      };
    }

    // Contradiction-free upsert for preferences (e.g. replacing "chai pasand hai" with "chai nahi pasand")
    if (kind === "preference") {
      const newToks = memoryTokens(content);
      const newHasNeg = [...newToks].some((t) => NEGATION_WORDS.has(t));
      const subjectNew = new Set([...newToks].filter((t) => !NEGATION_WORDS.has(t)));

      const conflicting = this.items.find((item) => {
        if (item.kind !== "preference") return false;
        const oldToks = memoryTokens(item.content);
        const oldHasNeg = [...oldToks].some((t) => NEGATION_WORDS.has(t));
        const shared = [...subjectNew].filter((t) => oldToks.has(t));
        return shared.length >= 2 && newHasNeg !== oldHasNeg;
      });

      if (conflicting) {
        conflicting.content = content;
        conflicting.createdAt = new Date().toISOString();
        this.savePersisted();
        return {
          success: true,
          action: "remember_updated",
          message: `Preference #${conflicting.id} update kar di gayi (purani conflicting entry replace ho gayi): ${content}`,
        };
      }
    }

    const item: MemoryItem = {
      id: this.nextItemId++,
      kind,
      content,
      createdAt: new Date().toISOString(),
    };
    this.items.push(item);
    this.savePersisted();
    return {
      success: true,
      action: kind === "note" ? "note" : "remember",
      message: `${kind === "note" ? "Note" : "Preference"} save kar liya (#${item.id}): ${item.content}`,
    };
  }

  forgetItem(id?: number, content?: string): MemoryCommandResult {
    if (typeof id === "number") {
      const idx = this.items.findIndex((i) => i.id === id);
      if (idx === -1) {
        return { success: false, action: "forget", message: `Memory #${id} nahi mili.`, error: "not_found" };
      }
      const [removed] = this.items.splice(idx, 1);
      this.savePersisted();
      return { success: true, action: "forget", message: `Memory #${removed.id} delete kar di: ${removed.content}` };
    }

    if (content && content.trim()) {
      const target = normalizeContent(content);
      const idx = this.items.findIndex((i) => normalizeContent(i.content).includes(target));
      if (idx === -1) {
        return { success: false, action: "forget", message: `"${content.trim()}" se match karne wali memory nahi mili.`, error: "not_found" };
      }
      const [removed] = this.items.splice(idx, 1);
      this.savePersisted();
      return { success: true, action: "forget", message: `Memory #${removed.id} delete kar di: ${removed.content}` };
    }

    return {
      success: false,
      action: "forget",
      message: "Delete karne ke liye `/forget <id>` ya `forget this: <text>` use kijiye.",
      error: "missing_target",
    };
  }

  addReminder(message: string, dueAt: Date): MemoryCommandResult {
    const cleaned = message.trim();
    if (!cleaned) {
      return { success: false, action: "remind", message: "Reminder message empty nahi ho sakta.", error: "empty_content" };
    }
    if (containsSensitiveData(cleaned)) {
      return {
        success: false,
        action: "remind",
        message: "Sensitive data reminder mein save nahi kiya.",
        error: "sensitive_data",
      };
    }

    const reminder: ReminderItem = {
      id: this.nextReminderId++,
      message: cleaned,
      dueAt: dueAt.toISOString(),
      createdAt: new Date().toISOString(),
      deliveredAt: null,
    };
    this.reminders.push(reminder);
    this.savePersisted();
    const formattedTime = dueAt.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
    return {
      success: true,
      action: "remind",
      message: `Reminder #${reminder.id} set kar diya (${formattedTime}): ${reminder.message}`,
    };
  }

  deleteReminder(id: number): MemoryCommandResult {
    const idx = this.reminders.findIndex((r) => r.id === id);
    if (idx === -1) {
      return { success: false, action: "delete_reminder", message: `Reminder #${id} nahi mila.`, error: "not_found" };
    }
    const [removed] = this.reminders.splice(idx, 1);
    this.savePersisted();
    return { success: true, action: "delete_reminder", message: `Reminder #${removed.id} delete kar diya: ${removed.message}` };
  }

  recallRelevant(query: string, limit = 4): MemoryItem[] {
    const qTokens = memoryTokens(query);
    if (qTokens.size === 0 || this.items.length === 0) return [];
    const scored = this.items
      .map((item) => {
        const iTokens = memoryTokens(item.content);
        let overlap = 0;
        for (const t of qTokens) {
          if (iTokens.has(t)) overlap++;
        }
        return { item, overlap };
      })
      .filter((entry) => entry.overlap > 0)
      .sort((a, b) => b.overlap - a.overlap);

    return scored.slice(0, limit).map((e) => e.item);
  }
}

function parseReminderCommand(
  text: string,
  now: Date
): { message: string; dueAt: Date } | { error: string } | null {
  const prefix = text.match(/^(?:\/remind|remind\s+me)\s+(.+)$/i);
  if (!prefix) return null;
  const body = prefix[1].trim();

  const relMatch = body.match(/^in\s+(\d+)\s+(min(?:ute)?s?|hours?|hrs?|sec(?:ond)?s?)\s+(?:to\s+)?(.+)$/i);
  if (relMatch) {
    const amount = Number.parseInt(relMatch[1], 10);
    const unit = relMatch[2].toLowerCase();
    const message = relMatch[3].trim();
    if (amount > 0 && message) {
      const ms = unit.startsWith("h")
        ? amount * 3600_000
        : unit.startsWith("m")
          ? amount * 60_000
          : amount * 1000;
      return { message, dueAt: new Date(now.getTime() + ms) };
    }
  }

  const absMatch =
    body.match(/^(?:on\s+)?(today|tomorrow|\d{4}-\d{2}-\d{2})\s+(?:at\s+)?(\d{1,2}):(\d{2})(?:\s*(am|pm))?\s+(?:to\s+)?(.+)$/i) ||
    body.match(/^at\s+(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?:\s*(am|pm))?\s+(?:to\s+)?(.+)$/i);

  if (!absMatch) {
    return { error: "Format: remind me tomorrow at 09:00 to call Rahul (ya: remind me in 10 minutes to stretch)" };
  }

  const dateToken = absMatch[1].toLowerCase();
  let hour = Number.parseInt(absMatch[2], 10);
  const minute = Number.parseInt(absMatch[3], 10);
  const meridiem = absMatch[4]?.toLowerCase();
  const message = absMatch[5].trim();

  if (meridiem === "pm" && hour < 12) hour += 12;
  if (meridiem === "am" && hour === 12) hour = 0;
  if (hour > 23 || minute > 59 || !message) {
    return { error: "Reminder date/time invalid hai." };
  }

  const dueAt = new Date(now);
  if (dateToken === "tomorrow") {
    dueAt.setDate(dueAt.getDate() + 1);
  } else if (dateToken !== "today") {
    const [y, m, d] = dateToken.split("-").map((n) => Number.parseInt(n, 10));
    dueAt.setFullYear(y, m - 1, d);
  }
  dueAt.setHours(hour, minute, 0, 0);
  return { message, dueAt };
}

export function handleMemoryCommand(
  text: string,
  store: MemoryStore | null
): MemoryCommandResult | null {
  const cleaned = text.trim();
  if (!cleaned) return null;

  const isSlashOrExplicit =
    /^\/(?:memories|notes|reminders|remember|note|forget|remind|delete-reminder)\b/i.test(cleaned) ||
    /^(?:show notes|list notes|show reminders|list reminders|delete\s+reminder\b)/i.test(cleaned);

  if (!isSlashOrExplicit) return null;

  if (!store) {
    return {
      success: false,
      action: "memory_paused",
      message: "Privacy mode active hai — persistent memory access is session ke liye paused hai.",
      error: "privacy_mode",
    };
  }

  if (/^\/memories$/i.test(cleaned)) {
    const items = store.listItems();
    if (items.length === 0) {
      return { success: true, action: "list_memories", message: "Abhi koi explicit preference ya note saved nahi hai." };
    }
    return {
      success: true,
      action: "list_memories",
      message: `Saved memories (${items.length}):\n${items.map((i) => `#${i.id} [${i.kind}] ${i.content}`).join("\n")}`,
    };
  }

  if (/^(?:\/notes|show notes|list notes)$/i.test(cleaned)) {
    const notes = store.listItems("note");
    if (notes.length === 0) {
      return { success: true, action: "list_notes", message: "Abhi koi notes saved nahi hain." };
    }
    return {
      success: true,
      action: "list_notes",
      message: `Saved notes (${notes.length}):\n${notes.map((n) => `#${n.id} ${n.content}`).join("\n")}`,
    };
  }

  if (/^(?:\/reminders|show reminders|list reminders)$/i.test(cleaned)) {
    const pending = store.listPendingReminders();
    if (pending.length === 0) {
      return { success: true, action: "list_reminders", message: "Koi pending reminders nahi hain." };
    }
    return {
      success: true,
      action: "list_reminders",
      message: `Pending reminders (${pending.length}):\n${pending
        .map((r) => `#${r.id} [${new Date(r.dueAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}] ${r.message}`)
        .join("\n")}`,
    };
  }

  const rememberMatch = cleaned.match(/^\/remember\s+(.+)$/i);
  if (rememberMatch) return store.addItem("preference", rememberMatch[1]);

  const noteMatch = cleaned.match(/^\/note\s+(.+)$/i);
  if (noteMatch) return store.addItem("note", noteMatch[1]);

  const forgetIdMatch = cleaned.match(/^\/forget(?:\s+(?:memory|note))?\s+#?(\d+)$/i);
  if (forgetIdMatch) return store.forgetItem(Number.parseInt(forgetIdMatch[1], 10));

  const deleteReminderMatch = cleaned.match(/^(?:\/delete-reminder|delete\s+reminder)\s+#?(\d+)$/i);
  if (deleteReminderMatch) return store.deleteReminder(Number.parseInt(deleteReminderMatch[1], 10));

  const reminderParsed = parseReminderCommand(cleaned, new Date());
  if (reminderParsed) {
    if ("error" in reminderParsed) {
      return { success: false, action: "invalid_reminder", message: reminderParsed.error, error: "invalid_reminder" };
    }
    return store.addReminder(reminderParsed.message, reminderParsed.dueAt);
  }

  return null;
}

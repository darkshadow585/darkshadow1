export type PersonaMode = "default" | "bhojpuri" | "witty" | "beedu";

export type CoreState = "idle" | "listening" | "thinking" | "speaking";

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

export interface ActionLink {
  label: string;
  url: string;
  platform: "web" | "youtube" | "google" | "spotify";
}

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

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  speechText?: string;
  timestamp: string;
  intent?: string;
  modelUsed?: string;
  sources?: SourceCitation[];
  toolTrace?: ToolTraceEntry[];
  actionLink?: ActionLink;
  suggestions?: string[];
  error?: string;
}

export interface DesktopFileMeta {
  name: string;
  summary: string;
  bytes: number;
}

export interface DesktopManifest {
  zipUrl: string;
  untouchedFiles: string[];
  files: DesktopFileMeta[];
}

export interface ChatApiResponse {
  displayText: string;
  speechText: string;
  intent: string;
  suggestions?: string[];
  sources?: SourceCitation[];
  toolTrace?: ToolTraceEntry[];
  actionLink?: ActionLink;
  modelUsed?: string;
  reminders?: ReminderItem[];
  clearHistory?: boolean;
  error?: string;
}

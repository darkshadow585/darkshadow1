export type AssistantState =
  | "idle"
  | "listening"
  | "processing"
  | "speaking"
  | "success"
  | "error";

export const STATE_TEXT: Record<AssistantState, string> = {
  idle: "Ready",
  listening: "Listening…",
  processing: "Thinking…",
  speaking: "Speaking…",
  success: "Done",
  error: "Something went wrong",
};

export const STATE_PALETTES: Record<AssistantState, [string, string, string]> = {
  idle: ["#6C55FF", "#334BCE", "#1B276B"],
  listening: ["#8B6CFF", "#477BFF", "#00D2FF"],
  processing: ["#CE56FF", "#765CFF", "#3D42D8"],
  speaking: ["#00D2FF", "#745DFF", "#9E68FF"],
  success: ["#00D2FF", "#35BFD7", "#426CFF"],
  error: ["#FF4560", "#FF6B8B", "#8A1830"],
};

export const STATE_LABEL_COLOR: Record<AssistantState, string> = {
  idle: "#8A90A4",
  listening: "#00D2FF",
  processing: "#B86CFF",
  speaking: "#00D2FF",
  success: "#00D2FF",
  error: "#FF4560",
};

export interface SourceCitation {
  title: string;
  url: string;
}

export interface ActionLink {
  label: string;
  url: string;
  platform: "web" | "youtube" | "google" | "spotify";
}

export interface ReminderItem {
  id: number;
  message: string;
  dueAt: string;
  createdAt: string;
  deliveredAt: string | null;
}

export interface MemoryItem {
  id: number;
  kind: "preference" | "note";
  content: string;
  createdAt: string;
}

export interface ChatTurn {
  id: string;
  prompt: string;
  response: string;
  intent: string;
  sources: SourceCitation[];
  actionLink?: ActionLink;
  modelUsed?: string;
  timestamp: string;
}

export interface ChatApiResponse {
  displayText: string;
  speechText: string;
  intent: string;
  emotion?: string;
  suggestions?: string[];
  sources?: SourceCitation[];
  actionLink?: ActionLink;
  modelUsed?: string;
  reminders?: ReminderItem[];
  clearHistory?: boolean;
  error?: string;
}

export interface RuntimeStatus {
  geminiConfigured: boolean;
  intelligentModel: string;
  casualModel: string;
  lastModelUsed: string | null;
  ttsModel: string;
  ttsVoice: string;
  searchMode: string;
  historyTurns: number;
  maxHistoryTurns: number;
  memoryCount: number;
  pendingReminderCount: number;
  summary: string;
}

import { Bell, Brain, Shield, Trash2, X } from "lucide-react";
import type { MemoryItem, ReminderItem } from "../types/darkshadow";

interface VaultDrawerProps {
  open: boolean;
  onClose: () => void;
  memories: MemoryItem[];
  reminders: ReminderItem[];
  privacyMode: boolean;
  onTogglePrivacy: () => void;
  onDeleteMemory: (id: number) => void;
  onDeleteReminder: (id: number) => void;
  onClearSession: () => void;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function VaultDrawer({
  open,
  onClose,
  memories,
  reminders,
  privacyMode,
  onTogglePrivacy,
  onDeleteMemory,
  onDeleteReminder,
  onClearSession,
}: VaultDrawerProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="DarkShadow Memory and Reminders Vault"
    >
      <div className="w-full max-w-md h-full bg-[#07090f] border-l border-white/12 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-sky-400" />
            <h2 className="text-sm font-semibold tracking-wide text-white uppercase">
              Living Memory Vault
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            aria-label="Close vault"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Privacy & Session Controls */}
        <div className="px-5 py-3.5 border-b border-white/10 flex items-center justify-between gap-3 bg-[#0a0e18]">
          <button
            type="button"
            onClick={onTogglePrivacy}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
              privacyMode
                ? "bg-amber-500/15 border-amber-400/40 text-amber-300"
                : "bg-white/5 border-white/10 text-zinc-300 hover:bg-white/10"
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            {privacyMode ? "Privacy Mode: ON" : "Privacy Mode: OFF"}
          </button>

          <button
            type="button"
            onClick={onClearSession}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-300 transition-colors cursor-pointer"
          >
            Reset Context
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
          {/* Reminders */}
          <section>
            <div className="flex items-center justify-between mb-2.5">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                <Bell className="w-3.5 h-3.5 text-sky-400" />
                Pending Reminders ({reminders.length})
              </h3>
            </div>
            {reminders.length === 0 ? (
              <p className="text-xs text-zinc-500 border border-white/8 rounded-lg px-3.5 py-3 bg-black/30">
                No active reminders. Try saying: &ldquo;10 minute baad paani peene ka remind karo&rdquo;.
              </p>
            ) : (
              <ul className="space-y-2">
                {reminders.map((rem) => (
                  <li
                    key={rem.id}
                    className="flex items-start justify-between gap-3 px-3.5 py-2.5 rounded-lg bg-white/[0.03] border border-white/10"
                  >
                    <div className="min-w-0">
                      <p className="text-xs text-zinc-100 leading-snug">{rem.message}</p>
                      <p className="mt-1 text-[11px] font-mono text-sky-400">
                        Due {formatTime(rem.dueAt)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => onDeleteReminder(rem.id)}
                      className="p-1 text-zinc-500 hover:text-rose-400 transition-colors cursor-pointer shrink-0"
                      aria-label={`Delete reminder ${rem.message}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Living Memories */}
          <section>
            <div className="flex items-center justify-between mb-2.5">
              <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
                <Brain className="w-3.5 h-3.5 text-sky-400" />
                Saved Preferences &amp; Notes ({memories.length})
              </h3>
            </div>
            {memories.length === 0 ? (
              <p className="text-xs text-zinc-500 border border-white/8 rounded-lg px-3.5 py-3 bg-black/30">
                Vault is empty. Say &ldquo;Yaad rakhna mujhe dark mode aur Edge pasand hai&rdquo; to test contradiction-free memory.
              </p>
            ) : (
              <ul className="space-y-2">
                {memories.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-start justify-between gap-3 px-3.5 py-2.5 rounded-lg bg-white/[0.03] border border-white/10"
                  >
                    <div className="min-w-0">
                      <span className="text-[10px] font-mono uppercase tracking-wider text-sky-400">
                        {item.kind}
                      </span>
                      <p className="mt-0.5 text-xs text-zinc-100 leading-snug">{item.content}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => onDeleteMemory(item.id)}
                      className="p-1 text-zinc-500 hover:text-rose-400 transition-colors cursor-pointer shrink-0"
                      aria-label={`Forget memory ${item.id}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

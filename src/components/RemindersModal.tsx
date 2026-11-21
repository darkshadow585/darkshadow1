import { useState } from "react";
import { Trash2 } from "lucide-react";
import type { MemoryItem, ReminderItem } from "../types.ts";

interface RemindersModalProps {
  open: boolean;
  reminders: ReminderItem[];
  memories: MemoryItem[];
  privacyMode: boolean;
  onClose: () => void;
  onDeleteReminder: (id: number) => void;
  onDeleteMemory: (id: number) => void;
}

/**
 * Upcoming reminders & explicit memory vault modal ported from ui.py's ReminderDialog.
 */
export function RemindersModal({
  open,
  reminders,
  memories,
  privacyMode,
  onClose,
  onDeleteReminder,
  onDeleteMemory,
}: RemindersModalProps) {
  const [tab, setTab] = useState<"reminders" | "memories">("reminders");

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[460px] rounded-2xl bg-[#000000] border border-[#181E2C] p-6 shadow-2xl space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-[18px] font-semibold text-[#F8F9FD]">
            {tab === "reminders" ? "Upcoming reminders" : "Saved memories & notes"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[#8A90A4] hover:text-white px-2 py-1 text-lg leading-none cursor-pointer"
            aria-label="Close modal"
          >
            ×
          </button>
        </div>

        <div className="flex gap-2 border-b border-[#181E2C] pb-2">
          <button
            type="button"
            onClick={() => setTab("reminders")}
            className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors cursor-pointer ${
              tab === "reminders"
                ? "bg-[#765CFF]/20 text-[#F8F9FD] border border-[#765CFF]/50"
                : "text-[#8A90A4] hover:text-white"
            }`}
          >
            Reminders ({reminders.length})
          </button>
          <button
            type="button"
            onClick={() => setTab("memories")}
            className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors cursor-pointer ${
              tab === "memories"
                ? "bg-[#765CFF]/20 text-[#F8F9FD] border border-[#765CFF]/50"
                : "text-[#8A90A4] hover:text-white"
            }`}
          >
            Memories &amp; Notes ({privacyMode ? "Paused" : memories.length})
          </button>
        </div>

        <div className="max-h-[280px] overflow-y-auto space-y-2 pr-1">
          {tab === "reminders" ? (
            reminders.length === 0 ? (
              <p className="text-[12.5px] text-[#8A90A4] py-4 leading-relaxed">
                No upcoming reminders. Try typing:{" "}
                <span className="text-[#80D8FF]">
                  &ldquo;Remind me tomorrow at 09:00 to call Rahul&rdquo;
                </span>{" "}
                or{" "}
                <span className="text-[#80D8FF]">
                  &ldquo;Remind me in 5 minutes to drink water&rdquo;
                </span>
              </p>
            ) : (
              reminders.map((r) => (
                <div
                  key={r.id}
                  className="flex items-start justify-between gap-3 rounded-xl bg-[#070A10] border border-[#181E2C] p-3"
                >
                  <div className="min-w-0">
                    <div className="text-[11px] text-[#00D2FF] font-medium">
                      #{r.id} •{" "}
                      {new Date(r.dueAt).toLocaleString("en-IN", {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </div>
                    <div className="text-[13px] text-[#F8F9FD] mt-0.5 break-words">
                      {r.message}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => onDeleteReminder(r.id)}
                    title="Delete reminder"
                    className="p-1.5 rounded-lg text-[#8A90A4] hover:text-[#FF4560] hover:bg-[#1B1018] transition-colors cursor-pointer shrink-0"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))
            )
          ) : privacyMode ? (
            <p className="text-[12.5px] text-[#8A90A4] py-4">
              Privacy mode is active — saved memory access is paused for this session.
            </p>
          ) : memories.length === 0 ? (
            <p className="text-[12.5px] text-[#8A90A4] py-4 leading-relaxed">
              No explicit memories saved yet. Try:{" "}
              <span className="text-[#80D8FF]">
                &ldquo;remember this: I prefer concise answers&rdquo;
              </span>{" "}
              or{" "}
              <span className="text-[#80D8FF]">&ldquo;/note Call the office&rdquo;</span>
            </p>
          ) : (
            memories.map((m) => (
              <div
                key={m.id}
                className="flex items-start justify-between gap-3 rounded-xl bg-[#070A10] border border-[#181E2C] p-3"
              >
                <div className="min-w-0">
                  <div className="text-[10.5px] uppercase tracking-wider text-[#765CFF] font-semibold">
                    #{m.id} • {m.kind}
                  </div>
                  <div className="text-[13px] text-[#F8F9FD] mt-0.5 break-words">
                    {m.content}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onDeleteMemory(m.id)}
                  title="Forget item"
                  className="p-1.5 rounded-lg text-[#8A90A4] hover:text-[#FF4560] hover:bg-[#1B1018] transition-colors cursor-pointer shrink-0"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))
          )}
        </div>

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-[#070A10] border border-[#181E2C] hover:border-[#765CFF] text-[12px] text-[#F8F9FD] transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

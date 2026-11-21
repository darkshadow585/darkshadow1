import { useEffect, useState } from "react";
import type { RuntimeStatus } from "../types.ts";

interface ControlCenterModalProps {
  open: boolean;
  voiceEnabled: boolean;
  reducedMotion: boolean;
  privacyMode: boolean;
  sttLanguage: "hi-IN" | "en-IN";
  status: RuntimeStatus | null;
  onClose: () => void;
  onApply: (prefs: {
    voiceEnabled: boolean;
    reducedMotion: boolean;
    privacyMode: boolean;
    sttLanguage: "hi-IN" | "en-IN";
  }) => void;
  onClearChat: () => void;
}

/**
 * Control Center modal ported from ui.py's ControlCenterDialog.
 * Never displays API keys or raw memory contents.
 */
export function ControlCenterModal({
  open,
  voiceEnabled,
  reducedMotion,
  privacyMode,
  sttLanguage,
  status,
  onClose,
  onApply,
  onClearChat,
}: ControlCenterModalProps) {
  const [localVoice, setLocalVoice] = useState(voiceEnabled);
  const [localMotion, setLocalMotion] = useState(reducedMotion);
  const [localPrivacy, setLocalPrivacy] = useState(privacyMode);
  const [localLang, setLocalLang] = useState<"hi-IN" | "en-IN">(sttLanguage);

  useEffect(() => {
    if (open) {
      setLocalVoice(voiceEnabled);
      setLocalMotion(reducedMotion);
      setLocalPrivacy(privacyMode);
      setLocalLang(sttLanguage);
    }
  }, [open, voiceEnabled, reducedMotion, privacyMode, sttLanguage]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-xs p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[440px] rounded-2xl bg-[#000000] border border-[#181E2C] p-6 shadow-2xl space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-[18px] font-semibold text-[#F8F9FD]">
            Settings &amp; privacy
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-[#8A90A4] hover:text-white px-2 py-1 text-lg leading-none cursor-pointer"
            aria-label="Close settings"
          >
            ×
          </button>
        </div>

        <div className="rounded-xl bg-[#070A10] border border-[#181E2C] p-3 text-[11.5px] leading-relaxed text-[#8A90A4] whitespace-pre-line">
          {status?.summary ?? "Loading DarkShadow runtime status…"}
        </div>

        <div className="space-y-3 pt-1">
          <label className="flex items-center gap-3 text-[13px] text-[#F8F9FD] cursor-pointer">
            <input
              type="checkbox"
              checked={localVoice}
              onChange={(e) => setLocalVoice(e.target.checked)}
              className="w-4 h-4 accent-[#765CFF] rounded cursor-pointer"
            />
            <span>Speak assistant replies</span>
          </label>

          <label className="flex items-center gap-3 text-[13px] text-[#F8F9FD] cursor-pointer">
            <input
              type="checkbox"
              checked={localMotion}
              onChange={(e) => setLocalMotion(e.target.checked)}
              className="w-4 h-4 accent-[#765CFF] rounded cursor-pointer"
            />
            <span>Reduce orb motion</span>
          </label>

          <label className="flex items-center gap-3 text-[13px] text-[#F8F9FD] cursor-pointer">
            <input
              type="checkbox"
              checked={localPrivacy}
              onChange={(e) => setLocalPrivacy(e.target.checked)}
              className="w-4 h-4 accent-[#765CFF] rounded cursor-pointer"
            />
            <span>Privacy mode (pause persistent memory access)</span>
          </label>

          <div className="flex items-center justify-between pt-1">
            <span className="text-[12px] text-[#8A90A4]">Voice input locale</span>
            <select
              value={localLang}
              onChange={(e) => setLocalLang(e.target.value as "hi-IN" | "en-IN")}
              className="bg-[#070A10] border border-[#181E2C] rounded-lg px-2.5 py-1.5 text-[12px] text-[#F8F9FD] focus:outline-none focus:border-[#765CFF]"
            >
              <option value="hi-IN">Hindi / Hinglish (hi-IN)</option>
              <option value="en-IN">English India (en-IN)</option>
            </select>
          </div>
        </div>

        <p className="text-[11px] text-[#8A90A4] leading-relaxed">
          Privacy mode affects this app session only. API keys and saved memory
          contents are never shown here.
        </p>

        <div className="flex items-center justify-between pt-2">
          <button
            type="button"
            onClick={() => {
              onClearChat();
              onClose();
            }}
            className="px-3.5 py-2 rounded-lg bg-[#070A10] border border-[#181E2C] hover:border-[#765CFF] hover:bg-[#0F1422] text-[12px] text-[#F8F9FD] transition-colors cursor-pointer"
          >
            Clear chat context
          </button>

          <button
            type="button"
            onClick={() => {
              onApply({
                voiceEnabled: localVoice,
                reducedMotion: localMotion,
                privacyMode: localPrivacy,
                sttLanguage: localLang,
              });
              onClose();
            }}
            className="px-5 py-2 rounded-lg bg-[#765CFF] hover:bg-[#8670FF] text-[12px] font-semibold text-white transition-colors cursor-pointer"
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}

import { Clock, Download, Settings } from "lucide-react";

interface TitleBarProps {
  pendingReminders: number;
  privacyMode: boolean;
  onOpenReminders: () => void;
  onOpenSettings: () => void;
  onOpenDesktopDownload: () => void;
}

/**
 * Custom TitleBar with AppMark orb glyph matching ui.py + Windows Python Desktop download action.
 */
export function TitleBar({
  pendingReminders,
  privacyMode,
  onOpenReminders,
  onOpenSettings,
  onOpenDesktopDownload,
}: TitleBarProps) {
  return (
    <header className="h-[52px] shrink-0 flex items-center justify-between px-4 sm:px-5 border-b border-[#181E2C]/70 select-none z-20 relative bg-black/60 backdrop-blur-xs">
      <div className="flex items-center gap-2.5">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <defs>
            <linearGradient id="ds-mark-grad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#00D2FF" />
              <stop offset="45%" stopColor="#765CFF" />
              <stop offset="80%" stopColor="#A95BFF" />
              <stop offset="100%" stopColor="#00D2FF" />
            </linearGradient>
          </defs>
          <circle cx="12" cy="12" r="8" fill="#080B16" stroke="url(#ds-mark-grad)" strokeWidth="2.2" />
          <circle cx="12" cy="12" r="2.2" fill="#7869FF" />
        </svg>
        <span className="text-[13px] font-semibold tracking-wide text-[#F8F9FD]">
          DarkShadow
        </span>
        {privacyMode && (
          <span className="ml-2 text-[11px] text-[#8A90A4] border border-[#181E2C] bg-[#070A10] px-2 py-0.5 rounded-md">
            Privacy Mode
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={onOpenDesktopDownload}
          className="flex items-center gap-1.5 px-3 h-8 rounded-lg bg-[#070A10] border border-[#00D2FF]/40 hover:border-[#00D2FF] hover:bg-[#0F1422] text-[11.5px] font-medium text-[#80D8FF] transition-colors cursor-pointer mr-1"
        >
          <Download className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Windows Python (.py)</span>
          <span className="sm:hidden">.py</span>
        </button>

        <button
          type="button"
          onClick={onOpenReminders}
          title="Reminders & Memories"
          aria-label="Reminders and memories"
          className="relative flex items-center justify-center w-10 h-9 rounded-lg text-[#AEB4C6] hover:text-white hover:bg-[#0F1422] transition-colors cursor-pointer"
        >
          <Clock className="w-[17px] h-[17px]" />
          {pendingReminders > 0 && (
            <span className="absolute top-1.5 right-1.5 min-w-[14px] h-[14px] px-1 rounded-full bg-[#765CFF] text-[9px] font-semibold text-white flex items-center justify-center">
              {pendingReminders}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={onOpenSettings}
          title="Settings and privacy"
          aria-label="Settings and privacy"
          className="flex items-center justify-center w-10 h-9 rounded-lg text-[#AEB4C6] hover:text-white hover:bg-[#0F1422] transition-colors cursor-pointer"
        >
          <Settings className="w-[17px] h-[17px]" />
        </button>
      </div>
    </header>
  );
}

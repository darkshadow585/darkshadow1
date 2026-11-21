import { Download, Package, Terminal } from "lucide-react";

interface DesktopExportModalProps {
  open: boolean;
  onClose: () => void;
}

const SUITE_FILES = [
  { name: "darkshadow_desktop.py", desc: "Main Option B PySide6 QWebEngineView desktop-layer overlay (stays behind open apps, no overlap) + Gemini AI + System Tray" },
  { name: "particle_engine.html", desc: "Upgrade #5: 6,000-particle WebGL2 shader (Sphere, DNA Helix, Plasma Torus, Shield Cube + 3-band FFT)" },
  { name: "voice_engine.py", desc: "Upgrade #1: Offline wake-word (openWakeWord/STT) + real-time 3-band FFT + interruptible TTS" },
  { name: "windows_tools.py", desc: "Upgrade #2: Screen Vision (mss), Windows OS tools, Zero-Camera & Payment Exclusion Shields" },
  { name: "memory_engine.py", desc: "Upgrade #3: SQLite + gemini-embedding-2 semantic recall + auto episodic summaries" },
  { name: "sentinel_monitor.py", desc: "Upgrade #4: Proactive desktop sentinel for due reminders & low-battery alerts" },
  { name: "windows_requirements.txt", desc: "All Windows 11 Python dependencies (PySide6, PySide6-Addons, sounddevice, google-genai, mss...)" },
  { name: "run_darkshadow_desktop.bat", desc: "One-click Windows launcher (auto venv + pip install + boots overlay)" },
  { name: ".env.example", desc: "Template for GEMINI_API_KEY and model settings" },
];

export function DesktopExportModal({ open, onClose }: DesktopExportModalProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-xs p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[580px] max-h-[88vh] flex flex-col rounded-2xl bg-[#000000] border border-[#181E2C] p-6 shadow-2xl space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-[#00D2FF]" />
            <h2 className="text-[17px] font-semibold text-[#F8F9FD]">
              DarkShadow Desktop Suite — Option B (5 Upgrades)
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[#8A90A4] hover:text-white px-2 py-1 text-lg leading-none cursor-pointer"
            aria-label="Close modal"
          >
            ×
          </button>
        </div>

        {/* 1-Click Full ZIP Bundle */}
        <a
          href="/api/desktop-files/DarkShadow-Desktop-Python.zip"
          download="DarkShadow-Desktop-Python.zip"
          className="shrink-0 flex items-center justify-between px-4 py-3.5 rounded-xl bg-gradient-to-r from-[#765CFF]/25 to-[#00D2FF]/20 border border-[#00D2FF]/60 hover:border-[#00D2FF] transition-colors"
        >
          <div className="flex items-center gap-3">
            <Package className="w-5 h-5 text-[#00D2FF] shrink-0" />
            <div>
              <div className="text-[13.5px] font-semibold text-white">
                Download Full Windows Suite (DarkShadow-Desktop-Python.zip)
              </div>
              <div className="text-[11px] text-[#80D8FF]">
                All 9 files • PySide6 + Embedded Transparent WebGL2 + All 5 Upgrades
              </div>
            </div>
          </div>
          <Download className="w-4 h-4 text-[#00D2FF] shrink-0 ml-3" />
        </a>

        {/* Individual Files */}
        <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5 pr-1">
          {SUITE_FILES.map((file) => (
            <a
              key={file.name}
              href={`/api/desktop-files/${encodeURIComponent(file.name)}`}
              download={file.name}
              className="flex items-center justify-between px-3.5 py-2 rounded-xl bg-[#070A10] border border-[#181E2C] hover:border-[#765CFF] transition-colors"
            >
              <div className="min-w-0">
                <div className="text-[12.5px] font-mono font-medium text-[#F8F9FD]">
                  {file.name}
                </div>
                <div className="text-[11px] text-[#8A90A4] truncate">
                  {file.desc}
                </div>
              </div>
              <Download className="w-3.5 h-3.5 text-[#8A90A4] shrink-0 ml-3" />
            </a>
          ))}
        </div>

        <div className="shrink-0 rounded-xl bg-[#070A10] border border-[#181E2C] p-3 text-[11.5px] text-[#AEB4C6] space-y-1 font-mono">
          <div className="text-[#80D8FF] font-sans font-semibold text-[11px] uppercase tracking-wider mb-1">
            Windows 11 Setup (3 Steps)
          </div>
          <div>1. Extract DarkShadow-Desktop-Python.zip</div>
          <div>2. Copy .env.example → .env and paste your GEMINI_API_KEY</div>
          <div>3. Double-click run_darkshadow_desktop.bat (say &ldquo;Hey Dark Shadow&rdquo;!)</div>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import {
  Check,
  Copy,
  Download,
  FileCode2,
  FolderCheck,
  Package,
  ShieldCheck,
  X,
} from "lucide-react";
import type { DesktopFileMeta, DesktopManifest } from "../types/darkshadow";

interface DesktopUpgradeModalProps {
  open: boolean;
  onClose: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function DesktopUpgradeModal({ open, onClose }: DesktopUpgradeModalProps) {
  const [manifest, setManifest] = useState<DesktopManifest | null>(null);
  const [selectedFile, setSelectedFile] = useState<DesktopFileMeta | null>(null);
  const [fileCode, setFileCode] = useState<string>("");
  const [loadingCode, setLoadingCode] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) return;
    let active = true;
    fetch("/api/desktop-files")
      .then((res) => res.json())
      .then((data: DesktopManifest) => {
        if (!active) return;
        setManifest(data);
        if (data.files.length > 0) {
          setSelectedFile((prev) => prev ?? data.files[0]);
        }
      })
      .catch(() => {
        /* ignore */
      });
    return () => {
      active = false;
    };
  }, [open]);

  useEffect(() => {
    if (!open || !selectedFile) return;
    let active = true;
    setLoadingCode(true);
    fetch(`/api/desktop-files/${encodeURIComponent(selectedFile.name)}?preview=1`)
      .then((res) => res.text())
      .then((text) => {
        if (!active) return;
        setFileCode(text);
        setLoadingCode(false);
      })
      .catch(() => {
        if (!active) return;
        setFileCode("# Failed to preview file.");
        setLoadingCode(false);
      });
    return () => {
      active = false;
    };
  }, [open, selectedFile]);

  if (!open) return null;

  const handleCopy = async () => {
    if (!fileCode) return;
    try {
      await navigator.clipboard.writeText(fileCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* ignore */
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label="DarkShadow Windows Drop-In Upgrade Pack"
    >
      <div className="relative flex flex-col w-full max-w-5xl max-h-[90vh] bg-[#07090f] border border-white/12 rounded-xl overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-white/10">
          <div>
            <div className="flex items-center gap-2.5">
              <Package className="w-5 h-5 text-sky-400 shrink-0" />
              <h2 className="text-base sm:text-lg font-semibold tracking-tight text-white">
                DarkShadow Windows 11 Drop-In Upgrade Pack
              </h2>
            </div>
            <p className="mt-1 text-xs sm:text-sm text-zinc-400">
              All 5 Upgrades + Critical Bug Fixes — seedhe apne purane{" "}
              <span className="font-mono text-zinc-200">desktop_python</span> folder mein Copy &amp; Replace karein.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            aria-label="Close upgrade modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Safe Merge Guarantee + 1-Click ZIP CTA */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 px-5 py-4 bg-[#0a0e18] border-b border-white/10">
          <div className="lg:col-span-8 space-y-2.5">
            <div className="flex items-center gap-2 text-emerald-400 text-xs sm:text-sm font-medium">
              <ShieldCheck className="w-4 h-4 shrink-0" />
              <span>
                100% Safe Upgrade: Aapki API Key, Virtual Env aur purani Memory bilkul touch nahi hogi
              </span>
            </div>
            <div className="flex flex-wrap gap-2 text-xs font-mono text-zinc-300">
              {(manifest?.untouchedFiles ?? [".env", ".venv/", ".darkshadow/memory.db", "contacts.json"]).map(
                (safeFile) => (
                  <span
                    key={safeFile}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-emerald-500/10 border border-emerald-500/25 text-emerald-300"
                  >
                    <FolderCheck className="w-3.5 h-3.5" />
                    {safeFile} untouched
                  </span>
                ),
              )}
            </div>
            <ol className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1 text-xs text-zinc-400">
              <li className="bg-black/40 border border-white/8 rounded-lg px-3 py-2">
                <span className="text-sky-400 font-semibold">Step 1:</span> ZIP download karke Extract karein.
              </li>
              <li className="bg-black/40 border border-white/8 rounded-lg px-3 py-2">
                <span className="text-sky-400 font-semibold">Step 2:</span> Saari files apne purane{" "}
                <span className="font-mono text-zinc-200">desktop_python</span> folder mein Paste &amp; Replace karein.
              </li>
              <li className="bg-black/40 border border-white/8 rounded-lg px-3 py-2">
                <span className="text-sky-400 font-semibold">Step 3:</span>{" "}
                <span className="font-mono text-zinc-200">update_install_deps.bat</span> chalayein, phir{" "}
                <span className="font-mono text-zinc-200">darkshadow_desktop.py</span> start karein.
              </li>
            </ol>
          </div>

          <div className="lg:col-span-4 flex flex-col justify-center gap-2">
            <a
              href={manifest?.zipUrl ?? "/api/desktop-files/DarkShadow-Upgrade-Pack.zip"}
              download="DarkShadow-Upgrade-Pack.zip"
              className="inline-flex items-center justify-center gap-2.5 px-4 py-3 rounded-lg bg-sky-500 hover:bg-sky-400 text-black font-semibold text-sm transition-colors"
            >
              <Download className="w-4 h-4" />
              Download Upgrade ZIP ({manifest?.files.length ?? 13} files)
            </a>
            <p className="text-[11px] text-zinc-500 text-center">
              Includes Edge CDP Launcher, V2 WebGL2 Core, Unified MCP Bridge &amp; Non-Blocking Live Engine
            </p>
          </div>
        </div>

        {/* File Inspector */}
        <div className="grid grid-cols-1 md:grid-cols-12 flex-1 min-h-0 overflow-hidden">
          {/* File list */}
          <div className="md:col-span-4 border-b md:border-b-0 md:border-r border-white/10 overflow-y-auto max-h-56 md:max-h-none">
            {manifest?.files.map((file) => {
              const isSelected = selectedFile?.name === file.name;
              return (
                <button
                  key={file.name}
                  type="button"
                  onClick={() => setSelectedFile(file)}
                  className={`w-full text-left px-4 py-3 border-b border-white/6 transition-colors cursor-pointer ${
                    isSelected ? "bg-sky-500/12 border-l-2 border-l-sky-400" : "hover:bg-white/4"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-2 font-mono text-xs text-zinc-100 truncate">
                      <FileCode2 className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                      {file.name}
                    </span>
                    <span className="text-[11px] font-mono text-zinc-500 shrink-0">
                      {formatBytes(file.bytes)}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-snug text-zinc-400 line-clamp-2">
                    {file.summary}
                  </p>
                </button>
              );
            })}
          </div>

          {/* Code preview */}
          <div className="md:col-span-8 flex flex-col min-h-0 bg-black">
            {selectedFile && (
              <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-white/10 bg-[#070a12]">
                <div className="min-w-0">
                  <div className="font-mono text-xs text-white truncate">{selectedFile.name}</div>
                  <div className="text-[11px] text-zinc-400 truncate">{selectedFile.summary}</div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-white/8 hover:bg-white/14 text-xs text-zinc-200 transition-colors cursor-pointer"
                  >
                    {copied ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-emerald-400" />
                        Copied
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        Copy
                      </>
                    )}
                  </button>
                  <a
                    href={`/api/desktop-files/${encodeURIComponent(selectedFile.name)}`}
                    download={selectedFile.name}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/30 text-xs text-sky-300 transition-colors"
                  >
                    <Download className="w-3.5 h-3.5" />
                    File
                  </a>
                </div>
              </div>
            )}

            <div className="flex-1 overflow-auto p-4 font-mono text-xs leading-relaxed text-zinc-300">
              {loadingCode ? (
                <div className="text-zinc-500">Loading file source...</div>
              ) : (
                <pre className="whitespace-pre-wrap break-words">{fileCode}</pre>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

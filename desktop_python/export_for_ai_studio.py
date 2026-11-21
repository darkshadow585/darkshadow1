"""
DarkShadow — Codebase Exporter for Google AI Studio (Gemini 4 Hydrogen / Argon / Neon / Pro)
=============================================================================================
Bundles the complete DarkShadow desktop codebase into a single, clean bundle file
formatted specifically for Google AI Studio's 2,000,000 token context window.
"""

import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_TXT = BASE_DIR / "DarkShadow_AI_Studio_Prompt.txt"
OUTPUT_MD = BASE_DIR / "DarkShadow_AI_Studio_Bundle.md"

DOWNLOADS_DIR = Path(r"C:\Users\user\Downloads")
DESKTOP_DIR = Path(r"C:\Users\user\OneDrive\Desktop")
if not DESKTOP_DIR.exists():
    DESKTOP_DIR = Path(r"C:\Users\user\Desktop")

FILES_TO_BUNDLE = [
    "darkshadow_desktop.py",
    "mcp_bridge.py",
    "gemini_live_engine.py",
    "browser_agent.py",
    "windows_tools.py",
    "windows_uia_agent.py",
    "mcp_client_hub.py",
    "autonomous_web_agent.py",
    "reasoning_engine.py",
    "living_memory_v3.py",
    "memory_engine.py",
    "config.py",
    "security_guard.py",
    "instant_router.py",
    "knowledge_vault.py",
    "playbook_engine.py",
    "visual_clicker.py",
    "focus_sentinel.py",
    "sentinel_monitor.py",
    "error_tracker.py",
    "mcp_servers.json",
    "windows_requirements.txt",
    "Launch_Edge_Debug.bat",
    "run_darkshadow_desktop.bat",
]

HEADER = """# =====================================================================
# SYSTEM PROMPT: DARKSHADOW DESKTOP AI ARCHITECT & CO-PILOT
# Target Environment: Google AI Studio (Gemini 4 Hydrogen / Argon / Neon / 2.5 Pro)
# Target Application: Windows 11 Desktop Agent (FastMCP + Edge CDP + Gemini Live)
# =====================================================================

You are the Lead Core Architect of "DarkShadow Desktop AI", an autonomous Windows 11
AI Co-Pilot that runs natively on the user's PC.

Below is the complete, live codebase of the project, including all tool definitions,
OS interaction primitives, memory systems, browser automation, and UI logic.

Your role in this conversation:
1. Understand the architecture deeply.
2. Review, troubleshoot, improve, or write new features when asked by the Captain.
3. Whenever providing code modifications, provide precise, drop-in replacement snippets
   or full updated module code that respects the existing dependencies and safety shields.
4. Maintain Microsoft Edge (via CDP port 9222) as the default browser and ensure single-window
   behavior without spawning duplicate browser tabs.
5. Respect Windows 11 native desktop app protocols (e.g. instagram:, whatsapp:, ms-settings:)
   before falling back to web URLs.

=====================================================================
# COMPLETE CODEBASE FILES
=====================================================================
"""

def bundle():
    print("Bundling full DarkShadow codebase for Google AI Studio...")
    
    # 1. Text format
    with open(OUTPUT_TXT, "w", encoding="utf-8") as out:
        out.write(HEADER)
        for fname in FILES_TO_BUNDLE:
            fpath = BASE_DIR / fname
            if not fpath.exists():
                continue
            out.write(f"\n\n{'='*75}\n")
            out.write(f"FILE: {fname}\n")
            out.write(f"{'='*75}\n\n")
            out.write(fpath.read_text(encoding="utf-8"))
            out.write("\n")

    # 2. Markdown format (Optimal for AI Studio & Gemini web)
    with open(OUTPUT_MD, "w", encoding="utf-8") as out:
        out.write(HEADER)
        for fname in FILES_TO_BUNDLE:
            fpath = BASE_DIR / fname
            if not fpath.exists():
                continue
            ext = fname.split(".")[-1]
            lang = "python" if ext == "py" else ("json" if ext == "json" else ("bat" if ext == "bat" else "text"))
            out.write(f"\n\n## File: `{fname}`\n\n```{lang}\n")
            out.write(fpath.read_text(encoding="utf-8"))
            out.write("\n```\n")

    size_txt_kb = os.path.getsize(OUTPUT_TXT) / 1024
    size_md_kb = os.path.getsize(OUTPUT_MD) / 1024
    print(f"[SUCCESS] TXT size: {size_txt_kb:.1f} KB | MD size: {size_md_kb:.1f} KB")

    # Copy to Downloads and Desktop
    for dest_dir in [DOWNLOADS_DIR, DESKTOP_DIR]:
        if dest_dir.exists():
            try:
                shutil.copy2(OUTPUT_MD, dest_dir / "DarkShadow_AI_Studio_Bundle.md")
                shutil.copy2(OUTPUT_TXT, dest_dir / "DarkShadow_AI_Studio_Bundle.txt")
                print(f"[COPIED] -> {dest_dir}")
            except Exception as e:
                print(f"[WARNING] Copy to {dest_dir} failed: {e}")

if __name__ == "__main__":
    bundle()

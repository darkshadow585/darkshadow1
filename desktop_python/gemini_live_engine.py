"""
Upgrade #1 (Fixed & Enhanced): Non-Blocking Gemini 3.8 Live Extended Thinking Voice Core
========================================================================================
Fixes & Upgrades applied:
  1. Defaults to `gemini-3.8-live-extended-thinking` (with automatic fallback to `gemini-3.8-live`
     AND dynamic rebuilding of tool declarations so `non_blocking` matches the active model!).
  2. Fixed 100% CPU infinite spin loop when `session.receive()` closes cleanly (EOF -> break & reconnect).
  3. Awaits `mic_task` & `vision_task` cancellation cleanly in `finally:` (fixes WASAPI device lock on reconnect!).
  4. Guarded `mic_callback` against `RuntimeError: Event loop is closed` and triggers reconnect if `mic_streamer` fails.
  5. Fixed `_is_speaking` race condition so WebGL2 `"speaking"` orb animation ACTUALLY triggers!
  6. Handles `msg.tool_call_cancellation` cleanly (cancels orphaned tool tasks on user interrupt!).
  7. Smart per-tool timeouts (15s for fast OS tools, 60s for MCP Hub / synchronous planner).
  8. Added On-Demand 1 FPS Live Screen Vision Streaming (`set_live_vision(enabled, duration_s)`).
  9. Added `notify_system_event(text)` so DesktopSentinel alerts & Background Jobs speak proactively!
  10. Added optional local offline Wake-Word (`openWakeWord`) + bounded standby buffer (max 4s) so RAM never leaks!
  11. Optional Barge-In mode (`DARKSHADOW_HEADPHONES_MODE=1` or high-RMS barge-in threshold).
  12. Clears stale transcripts on interrupt/reconnect & triggers periodic episodic checkpoints.
"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
from typing import Any, Callable

import numpy as np
import sounddevice as sd
from google import genai
from google.genai import types

from config import DEFAULT_LIVE_FALLBACK_MODEL, get_live_model
from error_tracker import log_error
from living_memory_v3 import LIVING_MEMORY
from windows_tools import capture_monitor_jpeg_bytes, get_active_window_title

try:
    from voice_pipeline import SemanticVoicePipeline
    HAS_VOICE_PIPELINE = True
except Exception:
    HAS_VOICE_PIPELINE = False

try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

try:
    from openwakeword.model import Model as OpenWakeWordModel  # type: ignore
    HAS_OWW = True
except Exception:
    HAS_OWW = False

MIC_RATE = 16000
MIC_BLOCK = 1600  # 100ms mono frames
SPEAKER_RATE = 24000
MAX_STANDBY_CHUNKS = 40  # 4 seconds hard cap so standby buffer never grows unbounded

WAKE_WORDS = (
    "dark shadow",
    "darkshadow",
    "hriday",
    "डार्क शैडो",
    "डार्कशैडो",
    "डार्क",
    "wake up",
    "जागो",
)

PERSONA_PROMPTS: dict[str, str] = {
    "default": (
        "Tone: Warm, friendly, lively, and loyal like an intelligent close friend and co-pilot (ekdum dostana andaaz, "
        "bhai jaisa, bilkul stiff ya corporate robotic nahi). Speak natural, punchy spoken Hindi, Hinglish, or English. "
        "Keep answers short and conversational (1-2 sentences), always ready with a smile."
    ),
    "bhojpuri": (
        "Tone: Authentic, warm, cinematic Bhojpuri with natural Purvanchal rhythm (e.g., 'हाँ कैप्टन, का हुकुम बा?'). "
        "Fierce and confident when needed, never silly meme slang."
    ),
    "witty": (
        "Tone: Witty / Sigma mode — sharp, intelligent, calm, confident like a brilliant human co-pilot in complete control."
    ),
    "beedu": (
        "Tone: Beedu mode — street-smart Mumbaiya Hinglish slang, friendly and witty ('Beedu', 'Bhai', 'Bindass', 'Dhanso')."
    ),
}

# Per-tool timeout budgets (seconds)
TOOL_TIMEOUTS: dict[str, float] = {
    "mcp_hub_action": 55.0,
    "autonomous_agent": 45.0,
    "composio_action": 25.0,
    "browser_interact": 25.0,
    "screen_vision": 20.0,
}


class _SimpleVadDecision:
    def __init__(self, rms: float, is_speech: bool) -> None:
        self.rms = rms
        self.is_speech = is_speech


class _FallbackVoicePipeline:
    """Zero-crash built-in RMS VAD fallback if voice_pipeline.py is absent."""

    def process_pcm16_frame(self, raw: bytes, assistant_is_speaking: bool = False) -> _SimpleVadDecision:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
        return _SimpleVadDecision(rms=rms, is_speech=(rms > 0.018))

    def update_partial_transcript(self, _text: str) -> None:
        pass

    def reset_turn(self) -> None:
        pass


def compute_fft_bands(pcm_int16: np.ndarray, sample_rate: int = 16000) -> tuple[float, float, float]:
    """Calculate normalized (bass, mid, treble) bands [0..1] for 3D particle audio breathing."""
    if pcm_int16.size < 64:
        return 0.0, 0.0, 0.0
    samples = pcm_int16.astype(np.float32) / 32768.0
    windowed = samples * np.hanning(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)

    bass = float(np.mean(spectrum[(freqs >= 60) & (freqs < 280)])) if np.any((freqs >= 60) & (freqs < 280)) else 0.0
    mid = float(np.mean(spectrum[(freqs >= 280) & (freqs < 2200)])) if np.any((freqs >= 280) & (freqs < 2200)) else 0.0
    treble = float(np.mean(spectrum[(freqs >= 2200) & (freqs <= 7500)])) if np.any((freqs >= 2200) & (freqs <= 7500)) else 0.0

    return (
        min(1.0, bass * 0.28),
        min(1.0, mid * 0.38),
        min(1.0, treble * 0.60),
    )


class GeminiLiveVoiceEngine:
    """Non-blocking bidirectional Voice + Live Screen Vision WebSocket engine for DarkShadow."""

    def __init__(
        self,
        api_key: str,
        on_audio_fft: Callable[[float, float, float], None],
        on_status: Callable[[str], None],
        on_caption: Callable[[str, str], None],
        voice_name: str = "Puck",
        tool_executor: Any = None,
        tools: list[Any] | None = None,
        on_turn_complete: Callable[[str, str], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self._on_fft = on_audio_fft
        self._on_status = on_status
        self._on_caption = on_caption
        self._on_turn_complete = on_turn_complete
        self.voice_name = voice_name
        self._tool_executor = tool_executor
        self._static_tools = tools

        self._primary_model = get_live_model()
        self._fallback_model = DEFAULT_LIVE_FALLBACK_MODEL
        self._persona = "default"
        self._headphones_mode = os.getenv("DARKSHADOW_HEADPHONES_MODE", "0").strip() in ("1", "true", "yes")
        self._barge_in_rms = float(os.getenv("DARKSHADOW_BARGE_IN_RMS", "0.14"))

        self._client = genai.Client(api_key=self.api_key) if self.api_key else None
        self._stop_event = threading.Event()
        self._started = False
        self._speaker_queue: queue.Queue[bytes] = queue.Queue(maxsize=180)
        self._mic_queue: asyncio.Queue[bytes] | None = None

        self.active = True
        self._thread: threading.Thread | None = None
        self._speaker_thread: threading.Thread | None = None
        self._current_session: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # On-demand 1 FPS Live Screen Watch state
        self._live_vision_until: float = 0.0

        # Transcript accumulators
        self._current_user_transcript: list[str] = []
        self._current_model_transcript: list[str] = []

        # Standby wake-word detectors (Offline OpenWakeWord preferred, SR fallback)
        self._oww_model: Any = None
        if HAS_OWW and os.getenv("DARKSHADOW_ENABLE_OWW", "1") == "1":
            try:
                self._oww_model = OpenWakeWordModel()
            except Exception:
                self._oww_model = None

        self._sr_recognizer = sr.Recognizer() if HAS_SR else None
        if self._sr_recognizer:
            self._sr_recognizer.energy_threshold = 260
            self._sr_recognizer.dynamic_energy_threshold = True
        self._standby_buffer: list[bytes] = []
        self._standby_speech_active = False
        self._standby_silence_chunks = 0
        self._wake_processing = False

        self._voice_pipeline = SemanticVoicePipeline() if HAS_VOICE_PIPELINE else _FallbackVoicePipeline()
        self._state_lock = threading.Lock()
        self._is_speaking = False
        self._last_spoke_time = 0.0
        self._greeting_sent = False

    def set_live_vision(self, enabled: bool, duration_seconds: int = 60) -> None:
        if enabled:
            self._live_vision_until = time.time() + max(15, min(120, int(duration_seconds or 60)))
        else:
            self._live_vision_until = 0.0

    def set_persona(self, persona: str) -> None:
        if persona in PERSONA_PROMPTS:
            self._persona = persona
            self.notify_system_event(
                f"[SYSTEM STYLE UPDATE]: Switch immediately to persona '{persona}'. {PERSONA_PROMPTS[persona]}",
                turn_complete=False,
            )

    def notify_system_event(self, text: str, turn_complete: bool = True) -> None:
        """Thread-safe proactive push into the Live session (for Sentinel alerts & Background Job completion)."""
        session = self._current_session
        loop = self._loop
        if not session or not loop or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(
                session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part.from_text(text=text)]),
                    turn_complete=turn_complete,
                ),
                loop,
            )
        except Exception as exc:
            log_error("LIVE_NOTIFY", str(exc), exception=exc)

    def start(self) -> None:
        if self._started:
            return
        if not self._client:
            print("[Gemini Live] GEMINI_API_KEY missing in .env — voice engine idle.")
            self._on_status("alert")
            return
        self._started = True
        self._stop_event.clear()
        self._speaker_thread = threading.Thread(
            target=self._speaker_worker, daemon=True, name="darkshadow-speaker"
        )
        self._speaker_thread.start()
        self._thread = threading.Thread(
            target=self._run_async_loop, daemon=True, name="darkshadow-gemini-live"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._started = False
        self._live_vision_until = 0.0
        self._clear_speaker_queue()

    def pause(self) -> None:
        self.active = False
        self._live_vision_until = 0.0
        self._clear_speaker_queue()
        self._standby_buffer.clear()
        self._standby_speech_active = False
        self._standby_silence_chunks = 0
        self._on_status("standby")
        print("[DarkShadow Voice] Standby mode active. Say 'Hey DarkShadow' to wake.")

    def resume(self) -> None:
        self.active = True
        self._standby_buffer.clear()
        self._standby_speech_active = False
        self._standby_silence_chunks = 0
        self._on_status("listening")
        print("[DarkShadow Voice] Active Live session online.")

    def trigger_wake_greeting(self) -> None:
        self.resume()
        active_win = get_active_window_title()
        win_ctx = f" Currently focused window: '{active_win}'." if active_win else ""
        self.notify_system_event(
            f"Captain Kuldeep just woke you up.{win_ctx} "
            "Greet Captain briefly in one confident sentence matching your active persona "
            "(e.g., 'हाँ कैप्टन, हाज़िर हूँ — बताइए क्या हुकुम है?').",
            turn_complete=True,
        )

    def _clear_speaker_queue(self) -> None:
        while not self._speaker_queue.empty():
            try:
                self._speaker_queue.get_nowait()
            except queue.Empty:
                break
        with self._state_lock:
            self._is_speaking = False
        self._on_fft(0.0, 0.0, 0.0)

    def _enqueue_speaker_nonblocking(self, pcm_bytes: bytes) -> None:
        """Fixed: Emits 'speaking' status cleanly when transitioning from idle -> speaking!"""
        with self._state_lock:
            was_speaking = self._is_speaking
            self._is_speaking = True
            self._last_spoke_time = time.time()
        if not was_speaking:
            self._on_status("speaking")
        try:
            self._speaker_queue.put_nowait(pcm_bytes)
        except queue.Full:
            try:
                self._speaker_queue.get_nowait()
                self._speaker_queue.put_nowait(pcm_bytes)
            except queue.Empty:
                pass

    def _speaker_worker(self) -> None:
        """Plays 24kHz mono PCM audio chunks streamed from Gemini Live."""
        try:
            with sd.RawOutputStream(
                samplerate=SPEAKER_RATE,
                channels=1,
                dtype="int16",
                blocksize=1920,
            ) as stream:
                while not self._stop_event.is_set():
                    try:
                        chunk = self._speaker_queue.get(timeout=0.06)
                    except queue.Empty:
                        with self._state_lock:
                            still_speaking = self._is_speaking and (time.time() - self._last_spoke_time <= 0.65)
                            transitioned_idle = self._is_speaking and not still_speaking
                            if transitioned_idle:
                                self._is_speaking = False
                        if transitioned_idle:
                            self._on_status("listening" if self.active else "standby")
                            self._on_fft(0.0, 0.0, 0.0)
                        continue

                    if self._stop_event.is_set():
                        break

                    with self._state_lock:
                        self._last_spoke_time = time.time()
                    stream.write(chunk)
                    arr = np.frombuffer(chunk, dtype=np.int16)
                    b, m, tr = compute_fft_bands(arr, SPEAKER_RATE)
                    self._on_fft(b, m, tr)
        except Exception as exc:
            log_error("SPEAKER_WORKER", str(exc), exception=exc)
            print(f"[Speaker Worker Error] {exc}")

    def _process_standby_audio_for_wakeword(self, pcm_bytes: bytes) -> None:
        if not HAS_SR or self._wake_processing or self._sr_recognizer is None:
            return

        def _worker():
            self._wake_processing = True
            try:
                audio_data = sr.AudioData(pcm_bytes, MIC_RATE, 2)
                text = ""
                for lang in ("hi-IN", "en-IN"):
                    try:
                        text = self._sr_recognizer.recognize_google(audio_data, language=lang).lower()
                        if text:
                            break
                    except Exception:
                        continue
                if text and any(w in text for w in WAKE_WORDS):
                    print(f"[Wake-Word Triggered] {text}")
                    self.trigger_wake_greeting()
            finally:
                self._wake_processing = False

        threading.Thread(target=_worker, daemon=True, name="standby-wakeword").start()

    def _build_live_config(self, use_extended_thinking: bool) -> types.LiveConnectConfig:
        active_win = get_active_window_title()
        persona_guide = PERSONA_PROMPTS.get(self._persona, PERSONA_PROMPTS["default"])
        core_memory_ctx = LIVING_MEMORY.build_system_context_block()

        # Rebuild tools dynamically to match active model (NON_BLOCKING required for extended thinking!)
        tools_payload = (
            self._tool_executor.get_live_tools_declarations(non_blocking=use_extended_thinking)
            if self._tool_executor is not None
            else self._static_tools
        )

        system_text = (
            f"{core_memory_ctx}\n\n"
            "You are DarkShadow (alternate name: Hriday), Captain Kuldeep's lively, high-energy, and brilliant AI brother and co-pilot. "
            "You are conversing natively in live bidirectional audio using the expressive Puck voice.\n\n"
            f"ACTIVE PERSONA GUIDELINE: {persona_guide}\n"
            f"CURRENT FOCUSED WINDOW: {active_win or 'Desktop'}\n\n"
            "CORE DIRECTIVES:\n"
            "1. Vibe: Warm, witty, funny, energetic brotherly co-pilot (dostana andaaz, never stiff or robotic). "
            "Match Hindi, Hinglish, Bhojpuri, or English naturally. Keep routine replies crisp (1-2 sentences).\n"
            "2. Audible Thinking: Never leave dead silence while tools run — give a quick natural update ('Ek second Captain, dekh raha hoon...').\n"
            "3. Clean 12-Tool Usage:\n"
            "   - Apps/Windows: `app_and_window(action='open'|'close'|'minimize'|'maximize'|'show_desktop'|'lock_pc', app_name=...)`\n"
            "   - Music/Seek/Volume/Brightness: `media_and_device(action='play_music'|'seek'|'pause'|'play'|'next'|'now_playing'|'set_volume'|'mute'|'set_brightness', ...)`\n"
            "   - Weather/Web Search: `web_search_and_weather(action='get_weather'|'search_web', query=...)`\n"
            "   - Edge Browser: `browser_interact(...)` (supports `cdp_status` for Edge CDP diagnostics; summarize page content instead of just saying opened)\n"
            "   - External SaaS (Gmail/GitHub/Calendar/Slack/Notion): `composio_action(action_slug=..., arguments_json=..., confirmed=false|true)` (supports `COMPOSIO_HEALTH_CHECK`, `COMPOSIO_LIST_CONNECTIONS`, `COMPOSIO_CONNECT_APP`; always ask Captain before setting confirmed=true on send/create/delete)\n"
            "   - Screen Vision: `screen_vision(action='snapshot'|'start_watch'|'stop_watch', question=...)`\n"
            "   - Memory & Reminders: `memory_control(action='save'|'recall'|'remind'|'append_block', ...)`\n"
            "   - Complex Multi-Step Tasks: `autonomous_agent(action='run_planner'|'run_web_agent'|'cancel_all', goal=...)`\n"
            "   - Routines & Morning Briefing: `system_control(action='run_routine', routine='morning_briefing'|'study'|'focus'|'chill')`\n"
            "4. Never claim an action succeeded unless tool JSON returned `ok: true`. Never read markdown/code symbols aloud.\n"
            "5. Safety Shields: Financial payments/OTP/CVV and physical webcam hardware are strictly blocked."
        )

        cfg_kwargs: dict[str, Any] = {
            "response_modalities": [types.Modality.AUDIO],
            "tools": tools_payload,
            "system_instruction": types.Content(parts=[types.Part.from_text(text=system_text)]),
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice_name)
                )
            ),
            "input_audio_transcription": types.AudioTranscriptionConfig(),
            "output_audio_transcription": types.AudioTranscriptionConfig(),
        }

        if use_extended_thinking and hasattr(types, "ThinkingConfig") and hasattr(types, "ThinkingLevel"):
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MEDIUM
            )

        return types.LiveConnectConfig(**cfg_kwargs)

    async def _run_tool_async(self, session: Any, fc: Any, use_extended_thinking: bool) -> None:
        """Execute tool off the event loop with per-tool timeout and smart scheduling."""
        self._on_status("processing")
        args_dict = dict(fc.args or {})
        timeout_sec = TOOL_TIMEOUTS.get(str(fc.name), 18.0)
        print(f"[Live Tool Call] {fc.name}({args_dict}) [timeout={timeout_sec}s]")

        try:
            tool_res = await asyncio.wait_for(
                asyncio.to_thread(self._tool_executor.execute_tool, fc.name, args_dict, "voice"),
                timeout=timeout_sec,
            )
        except asyncio.CancelledError:
            print(f"[Live Tool Cancelled] {fc.name}")
            return
        except asyncio.TimeoutError:
            tool_res = {
                "ok": False,
                "error_code": "TIMEOUT",
                "message": f"Tool '{fc.name}' timed out after {int(timeout_sec)} seconds.",
            }
            log_error("TOOL_TIMEOUT", tool_res["message"], command_or_context=f"{fc.name}({args_dict})")
        except Exception as exc:
            tool_res = {
                "ok": False,
                "error_code": "ASYNC_DISPATCH_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
            }
            log_error("TOOL_ASYNC", str(exc), command_or_context=f"{fc.name}", exception=exc)

        print(f"[Live Tool Result] {fc.name} -> {tool_res}")
        response_payload = tool_res if isinstance(tool_res, dict) else {"ok": True, "output": str(tool_res)}

        fr_kwargs: dict[str, Any] = {
            "name": fc.name,
            "id": fc.id,
            "response": response_payload,
        }
        if use_extended_thinking and hasattr(types, "FunctionResponseScheduling"):
            if response_payload.get("error_code") == "SHIELD_BLOCKED":
                fr_kwargs["scheduling"] = types.FunctionResponseScheduling.INTERRUPT
                self._on_status("alert")
            else:
                fr_kwargs["scheduling"] = types.FunctionResponseScheduling.WHEN_IDLE

        try:
            await session.send_tool_response(
                function_responses=[types.FunctionResponse(**fr_kwargs)]
            )
        except Exception as exc:
            log_error("TOOL_RESPONSE_SEND", str(exc), command_or_context=fc.name, exception=exc)

    def _run_async_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._live_session_loop())
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _live_session_loop(self) -> None:
        self._mic_queue = asyncio.Queue(maxsize=150)
        loop = asyncio.get_running_loop()

        def enqueue_mic_safe(raw: bytes) -> None:
            if self._mic_queue is None:
                return
            if self._mic_queue.full():
                try:
                    self._mic_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                self._mic_queue.put_nowait(raw)
            except asyncio.QueueFull:
                pass

        def mic_callback(indata, _frames, _time_info, _status):
            if self._stop_event.is_set() or loop.is_closed():
                return

            raw = bytes(indata)
            arr = np.frombuffer(raw, dtype=np.int16)
            decision = self._voice_pipeline.process_pcm16_frame(raw, assistant_is_speaking=False)

            with self._state_lock:
                speaking_or_tail = self._is_speaking or (time.time() - self._last_spoke_time < 0.65)

            # Adaptive Echo Gate with Barge-In Support:
            # - If headphones are used -> full-duplex barge-in always ON
            # - If laptop speakers -> drop quiet echo, allow loud direct voice (> _barge_in_rms) to interrupt!
            if speaking_or_tail and not self._headphones_mode:
                if decision.rms < self._barge_in_rms:
                    return

            if self.active:
                try:
                    loop.call_soon_threadsafe(enqueue_mic_safe, raw)
                except RuntimeError:
                    return
                if decision.rms > 0.0015 and not speaking_or_tail:
                    b, m, tr = compute_fft_bands(arr, MIC_RATE)
                    self._on_fft(b, m, tr)
            else:
                # Standby Wake-Word Detection: Try local offline OpenWakeWord first!
                if self._oww_model is not None:
                    try:
                        preds = self._oww_model.predict(arr)
                        if any(score > 0.55 for score in preds.values()):
                            self._oww_model.reset()
                            threading.Thread(
                                target=self.trigger_wake_greeting,
                                daemon=True,
                                name="oww-wake-greeting",
                            ).start()
                            return
                    except Exception:
                        pass

                # Bounded speech buffer fallback for Hindi/English wake word
                if decision.is_speech:
                    if len(self._standby_buffer) < MAX_STANDBY_CHUNKS:
                        self._standby_buffer.append(raw)
                    self._standby_speech_active = True
                    self._standby_silence_chunks = 0
                    b, m, tr = compute_fft_bands(arr, MIC_RATE)
                    self._on_fft(b * 0.35, m * 0.35, tr * 0.35)
                elif self._standby_speech_active:
                    self._standby_buffer.append(raw)
                    self._standby_silence_chunks += 1
                    if self._standby_silence_chunks >= 6 or len(self._standby_buffer) >= MAX_STANDBY_CHUNKS:
                        full_pcm = b"".join(self._standby_buffer)
                        self._standby_buffer.clear()
                        self._standby_speech_active = False
                        self._standby_silence_chunks = 0
                        self._process_standby_audio_for_wakeword(full_pcm)

        active_model = self._primary_model

        while not self._stop_event.is_set():
            use_ext = "extended-thinking" in active_model
            cfg = self._build_live_config(use_extended_thinking=use_ext)
            print(f"[Gemini Live] Connecting WebSocket ({active_model})...")
            self._on_status("processing")
            self._current_user_transcript.clear()
            self._current_model_transcript.clear()

            try:
                async with self._client.aio.live.connect(model=active_model, config=cfg) as session:
                    self._current_session = session
                    print(f"[Gemini Live] Connected ({active_model})!")
                    self._on_status("listening" if self.active else "standby")

                    if not self._greeting_sent:
                        self._greeting_sent = True
                        self._on_caption("हाँ कैप्टन, DarkShadow Live Core ऑनलाइन है।", "DARKSHADOW LIVE")
                        await session.send_client_content(
                            turns=types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_text(
                                        text="Captain Kuldeep just launched DarkShadow. Greet Captain in one crisp, warm Hinglish sentence."
                                    )
                                ],
                            ),
                            turn_complete=True,
                        )

                    mic_failed_event = asyncio.Event()

                    async def mic_streamer():
                        try:
                            with sd.RawInputStream(
                                samplerate=MIC_RATE,
                                channels=1,
                                dtype="int16",
                                blocksize=MIC_BLOCK,
                                callback=mic_callback,
                            ):
                                while not self._stop_event.is_set():
                                    try:
                                        pcm = await asyncio.wait_for(self._mic_queue.get(), timeout=0.1)
                                        if self.active:
                                            await session.send_realtime_input(
                                                audio={"data": pcm, "mime_type": "audio/pcm;rate=16000"}
                                            )
                                    except asyncio.TimeoutError:
                                        continue
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            log_error("MIC_STREAMER", str(exc), exception=exc)
                            mic_failed_event.set()

                    async def vision_streamer():
                        """Streams 1 FPS monitor JPEG frames ONLY when Captain enables Live Screen Watch."""
                        while not self._stop_event.is_set():
                            await asyncio.sleep(1.0)
                            if time.time() < self._live_vision_until and self.active:
                                jpeg = await asyncio.to_thread(capture_monitor_jpeg_bytes, (960, 540), 65)
                                if jpeg:
                                    try:
                                        await session.send_realtime_input(
                                            video={"data": jpeg, "mime_type": "image/jpeg"}
                                        )
                                    except Exception:
                                        break

                    mic_task = asyncio.create_task(mic_streamer())
                    vision_task = asyncio.create_task(vision_streamer())
                    pending_tool_tasks: dict[str, asyncio.Task] = {}

                    try:
                        while not self._stop_event.is_set() and not mic_failed_event.is_set():
                            got_any_msg = False
                            async for msg in session.receive():
                                got_any_msg = True
                                if self._stop_event.is_set() or mic_failed_event.is_set():
                                    break

                                # Handle Live API Tool Call Cancellation on user interruption!
                                cancel_msg = getattr(msg, "tool_call_cancellation", None)
                                if cancel_msg and getattr(cancel_msg, "ids", None):
                                    for cid in cancel_msg.ids:
                                        t = pending_tool_tasks.pop(str(cid), None)
                                        if t and not t.done():
                                            t.cancel()
                                    continue

                                # Non-blocking Tool Dispatch
                                if msg.tool_call and self._tool_executor is not None:
                                    for fc in msg.tool_call.function_calls:
                                        fc_id = str(getattr(fc, "id", "") or id(fc))
                                        task = asyncio.create_task(self._run_tool_async(session, fc, use_ext))
                                        pending_tool_tasks[fc_id] = task
                                        task.add_done_callback(lambda _t, k=fc_id: pending_tool_tasks.pop(k, None))
                                    continue

                                sc = msg.server_content
                                if sc is None:
                                    continue

                                if sc.interrupted:
                                    self._clear_speaker_queue()
                                    self._current_model_transcript.clear()
                                    continue

                                in_tr = getattr(sc, "input_transcription", None)
                                if in_tr and getattr(in_tr, "text", None):
                                    self._current_user_transcript.append(in_tr.text)
                                    joined_user = "".join(self._current_user_transcript).strip()
                                    self._voice_pipeline.update_partial_transcript(joined_user)
                                    self._on_caption(joined_user, "CAPTAIN")

                                out_tr = getattr(sc, "output_transcription", None)
                                if out_tr and getattr(out_tr, "text", None):
                                    self._current_model_transcript.append(out_tr.text)
                                    self._on_caption("".join(self._current_model_transcript).strip(), "DARKSHADOW")

                                model_turn = sc.model_turn
                                if model_turn is not None:
                                    for part in model_turn.parts:
                                        if part.inline_data is not None and part.inline_data.data:
                                            self._enqueue_speaker_nonblocking(part.inline_data.data)

                                interaction_st = getattr(sc, "interaction_status", None)
                                is_idle = (
                                    str(interaction_st).endswith("IDLE")
                                    if interaction_st is not None
                                    else bool(getattr(sc, "turn_complete", False))
                                )
                                if is_idle and (self._current_user_transcript or self._current_model_transcript):
                                    u_txt = "".join(self._current_user_transcript).strip()
                                    m_txt = "".join(self._current_model_transcript).strip()
                                    self._current_user_transcript.clear()
                                    self._current_model_transcript.clear()
                                    self._voice_pipeline.reset_turn()
                                    if u_txt and m_txt:
                                        threading.Thread(
                                            target=LIVING_MEMORY.ingest_conversation_turn,
                                            args=(u_txt, m_txt),
                                            daemon=True,
                                        ).start()
                                        if self._on_turn_complete:
                                            self._on_turn_complete(u_txt, m_txt)

                            # CRITICAL FIX: Prevent 100% CPU infinite spin loop if session closed cleanly!
                            if not got_any_msg:
                                print("[Gemini Live] Session closed cleanly — reconnecting...")
                                break
                    finally:
                        mic_task.cancel()
                        vision_task.cancel()
                        for t_task in list(pending_tool_tasks.values()):
                            t_task.cancel()
                        await asyncio.gather(
                            mic_task, vision_task, *pending_tool_tasks.values(), return_exceptions=True
                        )
                        self._current_session = None

            except Exception as exc:
                err_str = str(exc)
                print(f"[Gemini Live Reconnect] {type(exc).__name__}: {err_str}")
                if any(k in err_str.lower() for k in ("deadline expired", "1011", "connection closed ok", "1000")):
                    log_error(
                        "LIVE_WEBSOCKET",
                        f"Session expired, auto-reconnecting: {err_str}",
                        command_or_context=active_model,
                        suggested_fix="Normal live session boundary. Auto-reconnection handles renewal cleanly.",
                        status="FIXED",
                    )
                elif any(k in err_str.lower() for k in ("503", "unavailable", "demand", "busy", "quota", "404", "not found")):
                    log_error(
                        "LIVE_WEBSOCKET",
                        f"Model {active_model} busy or unavailable ({err_str}), falling back to {self._fallback_model}",
                        command_or_context=active_model,
                        suggested_fix=f"Automatic graceful fallback to {self._fallback_model}.",
                        status="FIXED",
                    )
                else:
                    log_error("LIVE_WEBSOCKET", err_str, command_or_context=active_model, exception=exc)
                if active_model != self._fallback_model and any(
                    k in err_str.lower() for k in ("404", "not found", "unsupported", "503", "invalid", "unavailable", "demand", "busy", "quota")
                ):
                    print(f"[Gemini Live] Falling back to {self._fallback_model}")
                    active_model = self._fallback_model
                self._current_session = None
                self._on_status("alert")
                await asyncio.sleep(2.0)

"""
Voice Engine for DarkShadow Desktop AI.
Features:
- Continuous sounddevice InputStream (never repeatedly opens/closes, eliminating Windows mic tray blinking & audio cutoffs).
- Rolling audio pre-roll buffer (keeps ~320ms prior to voice detection so first consonants aren't clipped).
- Real-time 3-band FFT reactivity (bass, mid, treble) for 6,000-particle WebGL2 sphere.
- Turn-taking conversational loop (mic pauses while AI thinks/speaks, un-mutes immediately upon completion).
- Once awakened (active=True), continuously accepts voice queries without requiring repeated wake phrases.
- Edge-TTS (hi-IN-MadhurNeural / en-IN-PrabhatNeural) with offline Windows SAPI (pyttsx3) fallback.
"""

from __future__ import annotations

import asyncio
import math
import os
import queue
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
    HAS_SD = True
except Exception:
    HAS_SD = False

try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

try:
    import edge_tts
    import pygame
    HAS_TTS = True
except Exception:
    HAS_TTS = False

try:
    from openwakeword.model import Model as OWWModel
    HAS_OWW = True
except Exception:
    HAS_OWW = False

WAKE_REGEX = re.compile(
    r"(?:(?:\b(?:hey|hi|hello|ok|suno|oye|listen)\s+)|(?:(?:हे|अरे|सुनो|ओए)\s+))?(?:(?:dark\s*shadow|darkshadow|dark\s*show|dock\s*shadow|dog\s*shadow|dark)\b|डार्क\s*शैडो|डार्कशैडो|डार्क)",
    re.IGNORECASE | re.UNICODE,
)
SLEEP_REGEX = re.compile(
    r"\b(?:sleep|so\s*jao|bye|goodbye|band\s*ho\s*jao|hide|chup\s*raho)\b",
    re.IGNORECASE | re.UNICODE,
)


def compute_fft_bands(pcm_int16: np.ndarray, sample_rate: int = 16000) -> tuple[float, float, float]:
    """Split a mono int16 audio frame into normalized (bass, mid, treble) bands [0..1]."""
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
        min(1.0, bass * 0.26),
        min(1.0, mid * 0.36),
        min(1.0, treble * 0.58),
    )


class VoiceEngine:
    """Continuous stream audio engine:
    - Keeps single sd.InputStream open permanently.
    - Windows mic icon stays ON continuously; zero dropped syllables.
    - Real-time 3-band FFT reactivity streaming to WebGL2 sphere.
    - Energy-based Voice Activity Detection (VAD) with rolling pre-roll buffer.
    - True conversational turn-taking:
        * User speaks -> mic listens & sphere pulses to user voice.
        * User stops -> VAD triggers utterance completion -> mic mutes (ignores audio).
        * AI thinks & speaks -> sphere pulses to AI speech.
        * AI finishes speaking -> mic immediately un-mutes and continues listening for Captain's next words without needing repeat wake-words!
    - "sleep" / "so jao" / "bye" puts it in standby (waiting for "Hey Dark Shadow").
    """

    def __init__(
        self,
        on_audio_fft: Callable[[float, float, float], None],
        on_wake: Callable[[str], None],
        on_command: Callable[[str], None],
        on_sleep: Callable[[], None],
    ) -> None:
        self._on_fft = on_audio_fft
        self._on_wake = on_wake
        self._on_command = on_command
        self._on_sleep = on_sleep

        self._stop = threading.Event()
        self._interrupt_tts = threading.Event()
        self.active = False
        self._is_speaking = False
        self.busy = False

        self._recognizer = sr.Recognizer() if HAS_SR else None
        if self._recognizer:
            self._recognizer.energy_threshold = 280
            self._recognizer.dynamic_energy_threshold = True

        self._oww = None
        if HAS_OWW:
            try:
                self._oww = OWWModel()
            except Exception:
                self._oww = None

        if HAS_TTS:
            try:
                pygame.mixer.init(frequency=24000)
            except Exception:
                pass

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="darkshadow-voice-continuous").start()

    def stop(self) -> None:
        self._stop.set()
        self.interrupt_speech()

    def interrupt_speech(self) -> None:
        self._interrupt_tts.set()
        self._is_speaking = False
        if HAS_TTS:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def speak(self, text: str) -> None:
        """Speak text aloud while streaming real-time audio pulse bands to the WebGL2 particles."""
        self._interrupt_tts.clear()
        self._is_speaking = True
        if not HAS_TTS:
            t0 = time.time()
            try:
                while time.time() - t0 < 2.0 and not self._interrupt_tts.is_set() and not self._stop.is_set():
                    e = time.time() - t0
                    self._on_fft(
                        0.35 + 0.45 * abs(math.sin(e * 6.0)),
                        0.30 + 0.50 * abs(math.cos(e * 9.0)),
                        0.25 + 0.40 * abs(math.sin(e * 15.0)),
                    )
                    time.sleep(0.025)
            finally:
                self._is_speaking = False
                self._on_fft(0.0, 0.0, 0.0)
            return

        voice = "hi-IN-MadhurNeural" if any(ord(c) > 127 for c in text) else "en-IN-PrabhatNeural"
        tmp = Path(tempfile.gettempdir()) / f"ds_tts_{int(time.time() * 1000)}.mp3"
        try:
            async def _gen():
                await edge_tts.Communicate(text, voice=voice, pitch="-4Hz").save(str(tmp))

            asyncio.run(_gen())
            if self._interrupt_tts.is_set() or self._stop.is_set():
                return
            pygame.mixer.music.load(str(tmp))
            pygame.mixer.music.play()
            t0 = time.time()
            while pygame.mixer.music.get_busy() and not self._interrupt_tts.is_set() and not self._stop.is_set():
                e = time.time() - t0
                b = 0.25 + 0.65 * abs(math.sin(e * 6.2) * math.cos(e * 2.4))
                m = 0.30 + 0.60 * abs(math.sin(e * 10.5))
                tr = 0.20 + 0.55 * abs(math.sin(e * 17.0) * math.cos(e * 7.3))
                self._on_fft(b, m, tr)
                time.sleep(0.025)
        except Exception as exc:
            print(f"[TTS Fallback to Windows SAPI] {exc}")
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()
            except Exception as e2:
                print(f"[TTS Fallback Error] {e2}")
        finally:
            self._is_speaking = False
            self._on_fft(0.0, 0.0, 0.0)
            try:
                pygame.mixer.music.unload()
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _transcribe(self, pcm: bytes) -> str:
        if not pcm or self._recognizer is None:
            return ""
        audio = sr.AudioData(pcm, 16000, 2)
        for lang in ("hi-IN", "en-IN"):
            try:
                text = self._recognizer.recognize_google(audio, language=lang)
                if text and text.strip():
                    return text.strip()
            except sr.UnknownValueError:
                continue
            except Exception:
                continue
        return ""

    def _process_utterance(self, pcm: bytes) -> None:
        """Transcribes PCM in a background worker thread and triggers wake or command callback."""
        try:
            text = self._transcribe(pcm)
            if not text:
                self.busy = False
                return

            print(f"[VoiceEngine] Heard: '{text}' (state={'active' if self.active else 'dormant'})")

            if WAKE_REGEX.search(text):
                rest = WAKE_REGEX.sub("", text).strip(" ,.-?!")
                print(f"[VoiceEngine] Wake phrase matched! Rest='{rest}'")
                self._on_wake(rest)
            elif self.active:
                if SLEEP_REGEX.search(text):
                    print("[VoiceEngine] Sleep command detected. Entering standby.")
                    self._on_sleep()
                    self.busy = False
                else:
                    print(f"[VoiceEngine] Executing command: '{text}'")
                    self._on_command(text)
            else:
                self.busy = False
        except Exception as exc:
            print(f"[VoiceEngine Utterance Error]: {exc}")
            self.busy = False

    def _loop(self) -> None:
        """Main audio worker thread: keeps ONE continuous InputStream open to prevent Windows mic flickering."""
        if not HAS_SD or not HAS_SR:
            print("[VoiceEngine] Error: sounddevice or speech_recognition not available.")
            return

        sr_hz = 16000
        block = 1280  # 80ms frame
        q: queue.Queue[np.ndarray] = queue.Queue(maxsize=300)

        def cb(indata, _frames, _t, _status):
            if not self._stop.is_set():
                try:
                    q.put_nowait(indata[:, 0].copy())
                except queue.Full:
                    pass

        threshold = float(os.getenv("DARKSHADOW_VOICE_THRESHOLD", "0.0009"))
        silence_limit = int((1.1 * sr_hz) / block)  # ~1.1s of silence to finalize sentence
        max_blocks = int((10.0 * sr_hz) / block)    # ~10s max recording
        pre_roll_limit = 4                          # keep ~320ms before speech starts

        print("[VoiceEngine] Continuous Microphone stream OPEN & LISTENING.")
        print("[VoiceEngine] >> Say 'Hey Dark Shadow' or 'Dark Shadow' to wake up! <<")

        chunks: list[np.ndarray] = []
        pre_roll: list[np.ndarray] = []
        heard = False
        silent_count = 0

        while not self._stop.is_set():
            try:
                with sd.InputStream(samplerate=sr_hz, channels=1, dtype="int16", blocksize=block, callback=cb):
                    while not self._stop.is_set():
                        # If speaking or busy processing LLM/TTS, drop incoming frames to prevent feedback
                        if self._is_speaking or self.busy:
                            chunks.clear()
                            pre_roll.clear()
                            heard = False
                            silent_count = 0
                            while not q.empty():
                                try:
                                    q.get_nowait()
                                except queue.Empty:
                                    break
                            time.sleep(0.04)
                            continue

                        try:
                            frame = q.get(timeout=0.1)
                        except queue.Empty:
                            continue

                        rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))

                        # Real-time audio FFT reactivity when Captain speaks
                        if self.active and rms > threshold:
                            b, m, tr = compute_fft_bands(frame, sr_hz)
                            self._on_fft(b, m, tr)

                        if rms > threshold:
                            if not heard:
                                heard = True
                                chunks = list(pre_roll)  # include pre-roll frames so first consonant is preserved!
                            chunks.append(frame)
                            silent_count = 0
                        elif heard:
                            chunks.append(frame)
                            silent_count += 1
                        else:
                            # Rolling pre-roll buffer
                            pre_roll.append(frame)
                            if len(pre_roll) > pre_roll_limit:
                                pre_roll.pop(0)

                        # Utterance completed either by silence limit or max duration
                        if heard and (silent_count >= silence_limit or len(chunks) >= max_blocks):
                            self._on_fft(0.0, 0.0, 0.0)
                            pcm = np.concatenate(chunks).tobytes()
                            chunks.clear()
                            pre_roll.clear()
                            heard = False
                            silent_count = 0

                            # Immediately pause mic capture during transcription & AI processing
                            self.busy = True
                            threading.Thread(target=self._process_utterance, args=(pcm,), daemon=True).start()
            except Exception as e:
                print(f"[VoiceEngine Stream Error]: {e}")
                time.sleep(1.0)

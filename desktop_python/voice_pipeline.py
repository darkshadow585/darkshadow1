"""
D-2: Ultra-Natural Voice Pipeline (Pipecat / LiveKit-Inspired Semantic Turn Detection)
======================================================================================
Solves the #1 annoyance in real-time voice assistants: cutting the user off mid-thought!
Features:
  1. Adaptive Noise-Floor Energy VAD:
     Continuously calibrates room/fan/AC background noise so mic triggers cleanly
     on Captain's real voice instead of ceiling fan hum.
  2. Multilingual Semantic End-of-Turn Detector (Hindi / Hinglish / Bhojpuri / English):
     Analyzes live partial transcripts to decide whether Captain finished speaking
     or paused mid-sentence (e.g., ending with "aur...", "toh...", "matlab...",
     "ek minute...", "because...", "and..."). Dynamically extends silence timeout
     when a sentence is semantically incomplete!
  3. Instant Barge-In Guard:
     Tracks consecutive speech frames while DarkShadow is speaking so accidental
     desk taps don't falsely interrupt, while real speech interrupts in <140ms.
  4. Optional LiveKit / Pipecat Transport Readiness Probe.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

# Trailing connectors that indicate the speaker is still thinking / continuing
_INCOMPLETE_ENDINGS_RE = re.compile(
    r"(?:\b("
    r"and|or|but|because|so|then|that|which|when|if|like|um+|uh+|wait|actually|"
    r"aur|ya|lekin|kyunki|toh|phir|matlab|ki|jo|jab|agar|ek\s+minute|ruko|jaise|"
    r"baaki|hmmm+|aa+h|tani|kahe\s+ki|ta"
    r")|[,:\-])$",
    re.IGNORECASE,
)

# Clear terminal cues indicating the user is done speaking
_COMPLETE_ENDINGS_RE = re.compile(
    r"(?:[?!.।]|\b(karo|kar\s+do|batao|bata\s+do|chala\s+do|khol\s+do|band\s+karo|"
    r"thanks|thank\s+you|please|done|ok|okay|shukriya|bataiye|kijiye|kariye))$",
    re.IGNORECASE,
)


@dataclass
class TurnDecision:
    is_speech: bool
    rms: float
    noise_floor: float
    barge_in_triggered: bool
    turn_complete: bool
    recommended_wait_ms: int


class SemanticVoicePipeline:
    """
    Real-time audio frame + semantic turn controller designed to sit directly
    in front of `gemini_live_engine.py` (or a Pipecat / LiveKit audio stream).
    """

    def __init__(
        self,
        base_silence_ms: int = 750,
        incomplete_silence_ms: int = 1650,
        barge_in_frames_required: int = 3,
    ) -> None:
        self.base_silence_ms = base_silence_ms
        self.incomplete_silence_ms = incomplete_silence_ms
        self.barge_in_frames_required = barge_in_frames_required

        self._noise_window: deque[float] = deque(maxlen=60)
        self._noise_floor: float = 0.008
        self._speech_streak: int = 0
        self._last_speech_ts: float = 0.0
        self._speaking_started_ts: float = 0.0
        self._user_is_talking: bool = False
        self._latest_partial_transcript: str = ""

    def update_partial_transcript(self, text: str) -> None:
        self._latest_partial_transcript = (text or "").strip()

    def reset_turn(self) -> None:
        self._speech_streak = 0
        self._user_is_talking = False
        self._latest_partial_transcript = ""

    def compute_semantic_wait_ms(self, partial_text: str | None = None) -> int:
        """
        Predicts whether the current utterance is semantically complete.
        Returns shorter silence wait if complete, longer wait if Captain paused mid-thought.
        """
        txt = (partial_text if partial_text is not None else self._latest_partial_transcript).strip()
        if not txt:
            return self.base_silence_ms
        if _INCOMPLETE_ENDINGS_RE.search(txt):
            return self.incomplete_silence_ms
        if _COMPLETE_ENDINGS_RE.search(txt):
            return max(420, int(self.base_silence_ms * 0.7))
        # Very short 1-2 word opener ("Captain...", "DarkShadow...") -> give extra time
        if len(txt.split()) <= 2:
            return int(self.base_silence_ms * 1.45)
        return self.base_silence_ms

    def process_pcm16_frame(
        self,
        pcm16_bytes: bytes,
        assistant_is_speaking: bool = False,
    ) -> TurnDecision:
        """
        Processes a raw 16-bit mono PCM audio chunk (e.g., 16kHz / 20-40ms frame).
        Updates adaptive noise floor, detects speech, checks barge-in, and evaluates
        semantic end-of-turn.
        """
        now = time.monotonic()
        if not pcm16_bytes:
            return TurnDecision(False, 0.0, self._noise_floor, False, False, self.base_silence_ms)

        samples = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples * samples))) if samples.size > 0 else 0.0

        # Adaptive speech threshold above rolling room noise floor
        speech_threshold = max(0.014, self._noise_floor * 2.65)
        barge_in_threshold = max(0.026, self._noise_floor * 3.8)
        active_threshold = barge_in_threshold if assistant_is_speaking else speech_threshold

        is_speech = rms >= active_threshold
        barge_in_triggered = False

        if is_speech:
            self._speech_streak += 1
            self._last_speech_ts = now
            if not self._user_is_talking and self._speech_streak >= 2:
                self._user_is_talking = True
                self._speaking_started_ts = now
            if assistant_is_speaking and self._speech_streak >= self.barge_in_frames_required:
                barge_in_triggered = True
        else:
            self._speech_streak = 0
            # Only adapt noise floor during quiet non-speech frames
            if not assistant_is_speaking and rms < speech_threshold:
                self._noise_window.append(rms)
                if len(self._noise_window) >= 8:
                    sorted_vals = sorted(self._noise_window)
                    self._noise_floor = max(0.004, min(0.045, sorted_vals[len(sorted_vals) // 3]))

        wait_ms = self.compute_semantic_wait_ms()
        turn_complete = False
        if self._user_is_talking and not is_speech and self._last_speech_ts > 0:
            silence_ms = (now - self._last_speech_ts) * 1000.0
            if silence_ms >= wait_ms:
                turn_complete = True
                self._user_is_talking = False

        return TurnDecision(
            is_speech=is_speech,
            rms=rms,
            noise_floor=self._noise_floor,
            barge_in_triggered=barge_in_triggered,
            turn_complete=turn_complete,
            recommended_wait_ms=wait_ms,
        )

    def capabilities(self) -> dict[str, Any]:
        has_pipecat = False
        has_livekit = False
        try:
            import pipecat  # noqa: F401
            has_pipecat = True
        except Exception:
            pass
        try:
            import livekit.agents  # noqa: F401
            has_livekit = True
        except Exception:
            pass
        return {
            "adaptive_vad": True,
            "semantic_turn_detection": True,
            "languages": ["hi", "hinglish", "bhojpuri", "en"],
            "pipecat_installed": has_pipecat,
            "livekit_agents_installed": has_livekit,
            "noise_floor": round(self._noise_floor, 5),
        }

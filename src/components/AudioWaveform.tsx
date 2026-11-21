import { useEffect, useRef } from "react";
import type { AssistantState } from "../types.ts";

interface AudioWaveformProps {
  state: AssistantState;
  audioLevel: number;
  reducedMotion: boolean;
}

/**
 * 25-bar state-aware audio waveform ported from ui.py's AudioWaveform.
 * Visible only during listening and speaking states.
 */
export function AudioWaveform({
  state,
  audioLevel,
  reducedMotion,
}: AudioWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef(state);
  const audioRef = useRef(audioLevel);
  const reducedRef = useRef(reducedMotion);

  stateRef.current = state;
  audioRef.current = audioLevel;
  reducedRef.current = reducedMotion;

  const active = state === "listening" || state === "speaking";

  useEffect(() => {
    if (!active) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId = 0;
    let phase = 0;
    let display = 0;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = 250;
      const height = 46;
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
      }

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);

      display += (audioRef.current - display) * 0.24;
      phase += reducedRef.current ? 0.05 : 0.16;

      ctx.strokeStyle = stateRef.current === "speaking" ? "#00D2FF" : "#765CFF";
      ctx.lineWidth = 3.2;
      ctx.lineCap = "round";

      const count = 25;
      const centerY = height / 2;
      const spacing = width / (count + 1);

      for (let i = 0; i < count; i++) {
        const distance = Math.abs(i - 12) / 12;
        const envelope = Math.pow(1 - distance, 1.55);
        const wave = 0.55 + 0.45 * Math.pow(Math.sin(phase + i * 0.74), 2);
        const barH = 3 + envelope * (9 + display * 22) * wave;
        const x = spacing * (i + 1);
        ctx.beginPath();
        ctx.moveTo(x, centerY - barH / 2);
        ctx.lineTo(x, centerY + barH / 2);
        ctx.stroke();
      }

      ctx.restore();
      rafId = requestAnimationFrame(draw);
    };

    rafId = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafId);
  }, [active]);

  return (
    <div
      className={`h-[46px] flex items-center justify-center transition-opacity duration-200 ${
        active ? "opacity-100" : "opacity-0 pointer-events-none"
      }`}
    >
      <canvas ref={canvasRef} className="w-[250px] h-[46px]" />
    </div>
  );
}

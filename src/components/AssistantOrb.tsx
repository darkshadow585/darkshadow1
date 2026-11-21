import { useEffect, useRef } from "react";
import { STATE_PALETTES } from "../types.ts";
import type { AssistantState } from "../types.ts";

interface AssistantOrbProps {
  state: AssistantState;
  audioLevel: number;
  reducedMotion: boolean;
  onClick: () => void;
}

interface RGB {
  r: number;
  g: number;
  b: number;
}

function hexToRgb(hex: string): RGB {
  const clean = hex.replace("#", "");
  return {
    r: Number.parseInt(clean.slice(0, 2), 16),
    g: Number.parseInt(clean.slice(2, 4), 16),
    b: Number.parseInt(clean.slice(4, 6), 16),
  };
}

function mixRgb(a: RGB, b: RGB, t: number): RGB {
  const clamped = Math.max(0, Math.min(1, t));
  return {
    r: Math.round(a.r + (b.r - a.r) * clamped),
    g: Math.round(a.g + (b.g - a.g) * clamped),
    b: Math.round(a.b + (b.b - a.b) * clamped),
  };
}

function rgba(c: RGB, alpha: number): string {
  return `rgba(${c.r}, ${c.g}, ${c.b}, ${alpha.toFixed(3)})`;
}

function lighten(c: RGB, factor: number): RGB {
  return {
    r: Math.min(255, Math.round(c.r * factor)),
    g: Math.min(255, Math.round(c.g * factor)),
    b: Math.min(255, Math.round(c.b * factor)),
  };
}

/**
 * Single-orb hybrid canvas + fluid GIF component ported directly from ui.py's AssistantOrb.
 * Uses DarkShadow's original /assets/darkshadow_core.gif material wrapped with state-aware
 * radial bloom, 76 procedural orbital pin-points, conical ring, processing arc, and glowing eyes.
 */
export function AssistantOrb({
  state,
  audioLevel,
  reducedMotion,
  onClick,
}: AssistantOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef(state);
  const audioRef = useRef(audioLevel);
  const reducedRef = useRef(reducedMotion);

  stateRef.current = state;
  audioRef.current = audioLevel;
  reducedRef.current = reducedMotion;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId = 0;
    let phase = 0;
    let rotation = 0;
    let displayAudio = 0;
    let blinkTimer = 3.2;
    let blinkProgress = 0;
    let lastTime = performance.now();

    const currentPalette = STATE_PALETTES[stateRef.current].map(hexToRgb);

    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - lastTime) / 1000);
      lastTime = now;

      const dpr = window.devicePixelRatio || 1;
      const size = canvas.clientWidth || 300;
      const targetPx = Math.round(size * dpr);
      if (canvas.width !== targetPx || canvas.height !== targetPx) {
        canvas.width = targetPx;
        canvas.height = targetPx;
      }

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, size, size);

      const st = stateRef.current;
      const reduced = reducedRef.current;
      const targetAudio =
        st === "listening" || st === "speaking" ? Math.max(0, Math.min(1, audioRef.current)) : 0;
      displayAudio += (targetAudio - displayAudio) * 0.22;

      const speed =
        st === "processing"
          ? 2.6
          : st === "listening" || st === "speaking"
            ? 1.7 + displayAudio * 1.4
            : 0.9;
      phase += dt * speed * (reduced ? 0.25 : 1);
      rotation += dt * (st === "processing" ? 135 : 32) * (reduced ? 0.2 : 1);

      // Smooth palette interpolation
      const targetPalette = STATE_PALETTES[st].map(hexToRgb);
      for (let i = 0; i < 3; i++) {
        currentPalette[i] = mixRgb(currentPalette[i], targetPalette[i], 0.12);
      }
      const [primary, , accent] = currentPalette;

      // Natural eye blink cadence
      blinkTimer -= dt;
      if (blinkTimer <= 0) {
        blinkProgress += dt * 9.5;
        if (blinkProgress >= Math.PI) {
          blinkProgress = 0;
          blinkTimer = 2.6 + Math.random() * 3.4;
        }
      }
      const blink = blinkProgress > 0 ? Math.max(0.08, 1 - Math.sin(blinkProgress)) : 1;

      const cx = size / 2;
      const cy = size / 2;
      const visualRadius = size * 0.345 * (1 + 0.015 * Math.sin(phase * 1.4) + displayAudio * 0.055);

      if (st === "error" && !reduced) {
        ctx.translate(Math.sin(phase * 16) * 2.8, 0);
      }

      // 1. State radial bloom
      ctx.save();
      ctx.globalCompositeOperation = "screen";
      const wash = mixRgb(primary, accent, 0.28);
      const haloGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, visualRadius * 1.48);
      haloGrad.addColorStop(0, rgba(wash, 0.04));
      haloGrad.addColorStop(0.65, rgba(wash, 0.14 + displayAudio * 0.12));
      haloGrad.addColorStop(1, rgba(wash, 0));
      ctx.fillStyle = haloGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, visualRadius * 1.48, 0, Math.PI * 2);
      ctx.fill();

      // 2. 76 procedural orbital pin-points (matching ui.py)
      for (let idx = 0; idx < 76; idx++) {
        const angle = (Math.PI * 2 * idx) / 76 + phase * 0.12;
        const spread = 1.12 + 0.25 * (0.5 + 0.5 * Math.sin(idx * 2.17 + phase * 0.75));
        const dotR = visualRadius * spread;
        const dotColor = mixRgb(primary, accent, (idx % 7) / 7);
        const alpha = (24 + ((idx * 19) % 58)) / 255;
        const dotSize = 0.65 + (idx % 3) * 0.35;
        ctx.fillStyle = rgba(dotColor, alpha);
        ctx.beginPath();
        ctx.arc(cx + Math.cos(angle) * dotR, cy + Math.sin(angle) * dotR, dotSize, 0, Math.PI * 2);
        ctx.fill();
      }

      // 3. Outer glowing ring
      const rotRad = (-rotation * Math.PI) / 180;
      const ringGrad =
        typeof ctx.createConicGradient === "function"
          ? ctx.createConicGradient(rotRad, cx, cy)
          : ctx.createLinearGradient(cx - visualRadius, cy - visualRadius, cx + visualRadius, cy + visualRadius);

      ringGrad.addColorStop(0, rgba(lighten(accent, 1.35), 0.95));
      ringGrad.addColorStop(0.3, rgba(primary, 0.92));
      ringGrad.addColorStop(0.62, "rgba(197, 154, 255, 0.92)");
      ringGrad.addColorStop(1, rgba(lighten(accent, 1.35), 0.95));

      ctx.strokeStyle = rgba(primary, 0.18 + displayAudio * 0.22);
      ctx.lineWidth = 9 + displayAudio * 6;
      ctx.beginPath();
      ctx.arc(cx, cy, visualRadius, 0, Math.PI * 2);
      ctx.stroke();

      ctx.strokeStyle = ringGrad;
      ctx.lineWidth = 2.6 + displayAudio * 1.4;
      ctx.beginPath();
      ctx.arc(cx, cy, visualRadius, 0, Math.PI * 2);
      ctx.stroke();

      // 4. Spinning processing arc
      if (st === "processing" && !reduced) {
        const arcR = visualRadius * 1.07;
        const startAngle = (rotation * Math.PI) / 180;
        ctx.strokeStyle = rgba(lighten(accent, 1.45), 0.92);
        ctx.lineWidth = 3.2;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.arc(cx, cy, arcR, startAngle, startAngle + (76 * Math.PI) / 180);
        ctx.stroke();
      }
      ctx.restore();

      // 5. Two expressive glowing eyes (matching ui.py)
      const gazeX = reduced ? 0 : Math.sin(phase * 0.55) * visualRadius * 0.032;
      const gazeY = reduced ? 0 : Math.cos(phase * 0.42) * visualRadius * 0.018;
      const eyeY = cy + visualRadius * 0.015 + gazeY;
      const eyeOffset = visualRadius * 0.165;
      const eyeWidth = visualRadius * (0.042 + displayAudio * 0.008);
      const eyeHeight = Math.max(
        visualRadius * 0.008,
        visualRadius * (0.068 + displayAudio * 0.01) * blink
      );

      for (const eyeX of [cx - eyeOffset + gazeX, cx + eyeOffset + gazeX]) {
        const eyeGlow = ctx.createRadialGradient(eyeX, eyeY, 0, eyeX, eyeY, eyeHeight * 2.1);
        eyeGlow.addColorStop(0, "rgba(255, 255, 255, 0.95)");
        eyeGlow.addColorStop(0.45, "rgba(192, 220, 255, 0.42)");
        eyeGlow.addColorStop(1, "rgba(95, 125, 255, 0)");
        ctx.fillStyle = eyeGlow;
        ctx.beginPath();
        ctx.ellipse(eyeX, eyeY, eyeHeight * 2.1, Math.max(1.5, eyeHeight * 2.1), 0, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "rgba(245, 248, 255, 0.95)";
        ctx.beginPath();
        ctx.ellipse(eyeX, eyeY, eyeWidth, eyeHeight, 0, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.restore();
      rafId = requestAnimationFrame(draw);
    };

    rafId = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const gifScale =
    state === "listening" || state === "speaking"
      ? 1 + audioLevel * 0.06
      : state === "success"
        ? 1.03
        : 1;

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Activate DarkShadow voice assistant"
      title="Click or press Space to speak"
      className="group relative flex items-center justify-center w-[260px] h-[260px] sm:w-[300px] sm:h-[300px] cursor-pointer focus:outline-none select-none"
    >
      {/* Core Fluid GIF clipped cleanly to the inner dark glass sphere */}
      <div
        className="absolute rounded-full overflow-hidden transition-transform duration-150 ease-out"
        style={{
          width: "69%",
          height: "69%",
          transform: `scale(${gifScale})`,
          boxShadow: "inset 0 0 28px rgba(0, 0, 0, 0.72)",
        }}
      >
        <img
          src="/assets/darkshadow_core.gif"
          alt="DarkShadow Core Orb"
          draggable={false}
          className="w-full h-full object-cover opacity-90"
          style={{
            filter:
              state === "error"
                ? "hue-rotate(140deg) saturate(1.4)"
                : state === "processing"
                  ? "hue-rotate(42deg) saturate(1.25)"
                  : state === "speaking"
                    ? "saturate(1.25) brightness(1.08)"
                    : "none",
          }}
        />
        {/* Subtle dark center vignette so the glowing eyes read with crisp contrast */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(circle at center, rgba(4, 6, 18, 0.62) 0%, rgba(4, 6, 18, 0.25) 48%, rgba(0, 0, 0, 0.08) 100%)",
          }}
        />
      </div>

      {/* State-aware Canvas Overlay: bloom, particles, rotating ring, arc & blinking eyes */}
      <canvas
        ref={canvasRef}
        className="relative z-10 w-full h-full pointer-events-none"
      />
    </button>
  );
}

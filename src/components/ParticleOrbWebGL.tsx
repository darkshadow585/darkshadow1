import { useEffect, useRef } from "react";

export type ParticlePhase =
  | "dormant"
  | "rising"
  | "listening"
  | "processing"
  | "speaking"
  | "alert"
  | "dissolving";

export type ParticleShape = "sphere" | "helix" | "torus" | "shield";

export interface AudioBands {
  bass: number;
  mid: number;
  treble: number;
}

interface ParticleOrbWebGLProps {
  phase: ParticlePhase;
  shape: ParticleShape;
  audioBands: AudioBands;
  reducedMotion: boolean;
  onRiseComplete?: () => void;
  onDissolveComplete?: () => void;
  onClick?: () => void;
}

const VERTEX_SHADER = `#version 300 es
precision highp float;

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aColor;
layout(location = 2) in float aSize;
layout(location = 3) in float aAlpha;

uniform float uAspect;
uniform float uDpr;

out vec3 vColor;
out float vAlpha;

void main() {
  float zCam = 2.6 - aPos.z;
  float persp = 1.9 / max(0.4, zCam);
  vec2 projected = vec2(aPos.x / uAspect, aPos.y) * persp;
  gl_Position = vec4(projected, 0.0, 1.0);
  gl_PointSize = clamp(aSize * persp * uDpr, 1.4, 24.0);
  vColor = aColor;
  vAlpha = aAlpha * clamp(persp * 0.9, 0.25, 1.0);
}
`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;

in vec3 vColor;
in float vAlpha;
out vec4 fragColor;

void main() {
  vec2 coord = gl_PointCoord - vec2(0.5);
  float distSq = dot(coord, coord);
  if (distSq > 0.25) discard;

  float core = exp(-distSq * 24.0);
  float halo = exp(-distSq * 6.2) * 0.58;
  float intensity = core + halo;
  vec3 finalCol = mix(vColor, vec3(1.0, 1.0, 1.0), core * 0.68);
  fragColor = vec4(finalCol * intensity, clamp(intensity * vAlpha, 0.0, 1.0));
}
`;

function compileShader(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

/**
 * Upgrade #5 GPU WebGL2 6,000-particle engine matching desktop_python/particle_engine.html.
 * Supports 4 live 3D morph shapes (Fibonacci Sphere, DNA Helix + Atom Rings, Plasma Torus, Shield Cube)
 * and real-time 3-band FFT audio reactivity (bass, mid, treble).
 */
export function ParticleOrbWebGL({
  phase,
  shape,
  audioBands,
  reducedMotion,
  onRiseComplete,
  onDissolveComplete,
  onClick,
}: ParticleOrbWebGLProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const phaseRef = useRef<ParticlePhase>(phase);
  const prevPhaseRef = useRef<ParticlePhase>(phase);
  const shapeRef = useRef<ParticleShape>(shape);
  const bandsRef = useRef<AudioBands>(audioBands);
  const reducedRef = useRef<boolean>(reducedMotion);
  const onRiseCompleteRef = useRef(onRiseComplete);
  const onDissolveCompleteRef = useRef(onDissolveComplete);

  phaseRef.current = phase;
  shapeRef.current = shape;
  bandsRef.current = audioBands;
  reducedRef.current = reducedMotion;
  onRiseCompleteRef.current = onRiseComplete;
  onDissolveCompleteRef.current = onDissolveComplete;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: false,
    });
    const ctx2d = gl ? null : canvas.getContext("2d");

    let program: WebGLProgram | null = null;
    let vao: WebGLVertexArrayObject | null = null;
    let vbo: WebGLBuffer | null = null;
    let uAspectLoc: WebGLUniformLocation | null = null;
    let uDprLoc: WebGLUniformLocation | null = null;

    const COUNT = 6000;
    const posX = new Float32Array(COUNT), posY = new Float32Array(COUNT), posZ = new Float32Array(COUNT);
    const velX = new Float32Array(COUNT), velY = new Float32Array(COUNT), velZ = new Float32Array(COUNT);
    const botX = new Float32Array(COUNT), botY = new Float32Array(COUNT), botZ = new Float32Array(COUNT);

    const sphX = new Float32Array(COUNT), sphY = new Float32Array(COUNT), sphZ = new Float32Array(COUNT);
    const helX = new Float32Array(COUNT), helY = new Float32Array(COUNT), helZ = new Float32Array(COUNT);
    const torX = new Float32Array(COUNT), torY = new Float32Array(COUNT), torZ = new Float32Array(COUNT);
    const cubX = new Float32Array(COUNT), cubY = new Float32Array(COUNT), cubZ = new Float32Array(COUNT);

    const seed = new Float32Array(COUNT);
    const pPhase = new Float32Array(COUNT);
    const sizes = new Float32Array(COUNT);
    const alphas = new Float32Array(COUNT);
    const vertexData = new Float32Array(COUNT * 8);

    const golden = Math.PI * (1 + Math.sqrt(5));
    for (let i = 0; i < COUNT; i++) {
      const idx = i + 0.5;
      const r1 = Math.sin(i * 12.9898) * 43758.5453;
      const s = r1 - Math.floor(r1);
      const r2 = Math.sin(i * 78.233 + 1.7) * 43758.5453;
      const s2 = r2 - Math.floor(r2);
      const r3 = Math.sin(i * 39.425 + 4.3) * 43758.5453;
      const s3 = r3 - Math.floor(r3);

      seed[i] = s;
      pPhase[i] = s2 * Math.PI * 2;
      sizes[i] = 1.9 + s3 * 3.1;

      botX[i] = (s2 * 2 - 1) * 1.15;
      botY[i] = -1.18 - s * 0.38;
      botZ[i] = (s3 * 2 - 1) * 0.4;
      posX[i] = botX[i]; posY[i] = botY[i]; posZ[i] = botZ[i];

      // 0: Fibonacci Sphere
      const phi = Math.acos(1 - (2 * idx) / COUNT);
      const theta = golden * idx;
      sphX[i] = Math.sin(phi) * Math.cos(theta) * 0.44;
      sphY[i] = Math.cos(phi) * 0.44;
      sphZ[i] = Math.sin(phi) * Math.sin(theta) * 0.44;

      // 1: DNA Double Helix + Orbital Atom Rings
      if (i < COUNT * 0.65) {
        const tH = (i / (COUNT * 0.65)) * 2 - 1;
        const strand = i % 2 === 0 ? 0 : Math.PI;
        const twist = tH * Math.PI * 3.2 + strand;
        const rH = 0.24 + (s3 - 0.5) * 0.04;
        helX[i] = Math.cos(twist) * rH;
        helY[i] = tH * 0.52;
        helZ[i] = Math.sin(twist) * rH;
      } else {
        const ringIdx = i % 3;
        const a = s2 * Math.PI * 2;
        const rr = 0.48 + (s3 - 0.5) * 0.03;
        const rx = Math.cos(a) * rr;
        const rz = Math.sin(a) * rr;
        const tilt = ringIdx === 0 ? 0.6 : ringIdx === 1 ? -0.6 : 1.5;
        helX[i] = rx;
        helY[i] = -rz * Math.sin(tilt);
        helZ[i] = rz * Math.cos(tilt);
      }

      // 2: Plasma Audio Torus
      const u = s2 * Math.PI * 2;
      const v = s3 * Math.PI * 2;
      const R = 0.36;
      const r = 0.14;
      torX[i] = (R + r * Math.cos(v)) * Math.cos(u);
      torY[i] = r * Math.sin(v) * 1.15;
      torZ[i] = (R + r * Math.cos(v)) * Math.sin(u);

      // 3: Geometric Shield Cube
      const face = i % 6;
      const a1 = (s2 * 2 - 1) * 0.36;
      const a2 = (s3 * 2 - 1) * 0.36;
      if (face === 0) { cubX[i] = 0.36; cubY[i] = a1; cubZ[i] = a2; }
      else if (face === 1) { cubX[i] = -0.36; cubY[i] = a1; cubZ[i] = a2; }
      else if (face === 2) { cubX[i] = a1; cubY[i] = 0.36; cubZ[i] = a2; }
      else if (face === 3) { cubX[i] = a1; cubY[i] = -0.36; cubZ[i] = a2; }
      else if (face === 4) { cubX[i] = a1; cubY[i] = a2; cubZ[i] = 0.36; }
      else { cubX[i] = a1; cubY[i] = a2; cubZ[i] = -0.36; }
    }

    if (gl) {
      const vs = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
      const fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
      if (vs && fs) {
        program = gl.createProgram();
        if (program) {
          gl.attachShader(program, vs);
          gl.attachShader(program, fs);
          gl.linkProgram(program);
          if (gl.getProgramParameter(program, gl.LINK_STATUS)) {
            uAspectLoc = gl.getUniformLocation(program, "uAspect");
            uDprLoc = gl.getUniformLocation(program, "uDpr");
            vao = gl.createVertexArray();
            vbo = gl.createBuffer();
            gl.bindVertexArray(vao);
            gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
            gl.bufferData(gl.ARRAY_BUFFER, vertexData.byteLength, gl.DYNAMIC_DRAW);
            const stride = 32;
            gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, stride, 0);
            gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, stride, 12);
            gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 1, gl.FLOAT, false, stride, 24);
            gl.enableVertexAttribArray(3); gl.vertexAttribPointer(3, 1, gl.FLOAT, false, stride, 28);
            gl.bindVertexArray(0);
            gl.enable(gl.BLEND);
            gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
          }
        }
      }
    }

    let rafId = 0;
    let t = 0;
    let stateTime = 0;
    let sBass = 0, sMid = 0, sTreble = 0;
    let riseSignaled = false;
    let dissolveSignaled = false;
    let lastNow = performance.now();

    const resetForRising = () => {
      riseSignaled = false;
      for (let i = 0; i < COUNT; i++) {
        posX[i] = botX[i]; posY[i] = botY[i]; posZ[i] = botZ[i];
        velX[i] = -botX[i] * 0.45;
        velY[i] = 1.75 + seed[i] * 1.45;
        velZ[i] = Math.sin(pPhase[i]) * 0.35;
        alphas[i] = 0;
      }
    };

    if (phaseRef.current === "rising") resetForRising();

    const animate = (now: number) => {
      const dt = Math.min(0.04, (now - lastNow) / 1000);
      lastNow = now;

      const curPhase = phaseRef.current;
      const curShape = shapeRef.current;
      if (curPhase !== prevPhaseRef.current) {
        stateTime = 0;
        if (curPhase === "rising") resetForRising();
        else if (curPhase === "dissolving") dissolveSignaled = false;
        prevPhaseRef.current = curPhase;
      }

      const speedScale = reducedRef.current ? 0.3 : 1.0;
      t += dt * speedScale;
      stateTime += dt;

      const audioActive = curPhase === "listening" || curPhase === "speaking";
      const b = audioActive ? bandsRef.current.bass : 0;
      const m = audioActive ? bandsRef.current.mid : 0;
      const tr = audioActive ? bandsRef.current.treble : 0;
      sBass += (b - sBass) * Math.min(1, dt * 15);
      sMid += (m - sMid) * Math.min(1, dt * 15);
      sTreble += (tr - sTreble) * Math.min(1, dt * 18);

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cssW = canvas.clientWidth || 640;
      const cssH = canvas.clientHeight || 480;
      const pxW = Math.round(cssW * dpr);
      const pxH = Math.round(cssH * dpr);
      if (canvas.width !== pxW || canvas.height !== pxH) {
        canvas.width = pxW;
        canvas.height = pxH;
      }

      const txArr = curShape === "helix" ? helX : curShape === "torus" ? torX : curShape === "shield" ? cubX : sphX;
      const tyArr = curShape === "helix" ? helY : curShape === "torus" ? torY : curShape === "shield" ? cubY : sphY;
      const tzArr = curShape === "helix" ? helZ : curShape === "torus" ? torZ : curShape === "shield" ? cubZ : sphZ;

      // PURE SOLAR 3D ROTATION: Sthir Center rotating 360-degrees on its axis (ZERO tilt, ZERO flattening)
      const rotY = t * (curPhase === "processing" ? 0.8 : 0.35 + sMid * 0.4);
      const cy = Math.cos(rotY), sy = Math.sin(rotY);

      let c1r = 0.0, c1g = 0.82, c1b = 1.0;
      let c2r = 0.46, c2g = 0.36, c2b = 1.0;
      if (curPhase === "processing" || curShape === "helix") {
        c1r = 0.84; c1g = 0.34; c1b = 1.0;
        c2r = 0.42; c2g = 0.34; c2b = 1.0;
      } else if (curPhase === "speaking" || curShape === "torus") {
        c1r = 0.0; c1g = 0.9; c1b = 1.0;
        c2r = 0.65; c2g = 0.4; c2b = 1.0;
      } else if (curPhase === "alert" || curShape === "shield") {
        c1r = 1.0; c1g = 0.28; c1b = 0.4;
        c2r = 1.0; c2g = 0.62; c2b = 0.22;
      }

      for (let i = 0; i < COUNT; i++) {
        const ox = txArr[i], oy = tyArr[i], oz = tzArr[i];
        // Pure axial rotation around Y (like the Sun rotating on its axis, ZERO tilt):
        const x1 = ox * cy - oz * sy;
        const y2 = oy; // Perfectly anchored vertical axis, never tilts or flattens
        const z2 = ox * sy + oz * cy;

        // Pure isotropic 3D solar breathing (Uniform in all 3 axes, 100% spherical roundness):
        const scale = 1.0 + sBass * 0.16 + sMid * 0.08 + 0.015 * Math.sin(pPhase[i] + t * 3.5);

        const gx = x1 * scale;
        const gy = y2 * scale;
        const gz = z2 * scale;

        if (curPhase === "dormant") {
          const driftX = botX[i] * 0.85 + Math.sin(t * 0.8 + pPhase[i]) * 0.05;
          const driftY = -0.96 + seed[i] * 0.09 + Math.sin(t * 1.9 + pPhase[i]) * 0.025;
          posX[i] += (driftX - posX[i]) * Math.min(1, dt * 3.5);
          posY[i] += (driftY - posY[i]) * Math.min(1, dt * 3.5);
          posZ[i] += (botZ[i] * 0.4 - posZ[i]) * Math.min(1, dt * 3.5);
          const targetA = seed[i] < 0.2 ? 0.28 + 0.2 * Math.sin(t * 2.2 + pPhase[i]) : 0;
          alphas[i] += (targetA - alphas[i]) * Math.min(1, dt * 4);
        } else if (curPhase === "rising") {
          const delay = seed[i] * 0.4;
          const progress = Math.max(0, Math.min(1, (stateTime - delay) / 1.15));
          if (progress > 0) {
            const swirl = (1 - progress) * 2.4;
            const k = 8.0 * Math.pow(progress, 1.5);
            velX[i] += ((gx - posX[i]) * k - velX[i] * 3.8 - posZ[i] * swirl) * dt;
            velY[i] += ((gy - posY[i]) * k - velY[i] * 3.8) * dt;
            velZ[i] += ((gz - posZ[i]) * k - velZ[i] * 3.8 + posX[i] * swirl) * dt;
            posX[i] += velX[i] * dt;
            posY[i] += velY[i] * dt;
            posZ[i] += velZ[i] * dt;
            alphas[i] = Math.min(0.95, progress * 1.45);
          }
        } else if (curPhase === "dissolving") {
          velY[i] -= (2.4 + seed[i] * 1.8) * dt;
          velX[i] += Math.sin(t * 5.2 + pPhase[i]) * 0.5 * dt;
          posX[i] += velX[i] * dt;
          posY[i] += velY[i] * dt;
          posZ[i] += velZ[i] * dt;
          alphas[i] = Math.max(0, 1 - stateTime / 1.15);
        } else {
          const k = curPhase === "speaking" ? 14.5 : 11.5;
          const tang = 0.14 + sMid * 0.9;
          velX[i] += ((gx - posX[i]) * k - velX[i] * 5.0 - z2 * tang) * dt;
          velY[i] += ((gy - posY[i]) * k - velY[i] * 5.0) * dt;
          velZ[i] += ((gz - posZ[i]) * k - velZ[i] * 5.0 + x1 * tang) * dt;
          posX[i] += velX[i] * dt;
          posY[i] += velY[i] * dt;
          posZ[i] += velZ[i] * dt;
          alphas[i] = Math.min(0.96, alphas[i] + dt * 3.2);
        }

        const mix = 0.5 + 0.5 * Math.sin(pPhase[i] + t * 1.6 + y2 * 3.0);
        const o = i * 8;
        vertexData[o] = posX[i]; vertexData[o + 1] = posY[i]; vertexData[o + 2] = posZ[i];
        vertexData[o + 3] = c1r * mix + c2r * (1 - mix);
        vertexData[o + 4] = c1g * mix + c2g * (1 - mix);
        vertexData[o + 5] = c1b * mix + c2b * (1 - mix);
        vertexData[o + 6] = sizes[i] * (1.0 + sBass * 0.55 + sTreble * 0.4);
        vertexData[o + 7] = alphas[i];
      }

      if (curPhase === "rising" && stateTime >= 1.6 && !riseSignaled) {
        riseSignaled = true;
        onRiseCompleteRef.current?.();
      }
      if (curPhase === "dissolving" && stateTime >= 1.2 && !dissolveSignaled) {
        dissolveSignaled = true;
        onDissolveCompleteRef.current?.();
      }

      if (gl && program && vao && vbo) {
        gl.viewport(0, 0, pxW, pxH);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.useProgram(program);
        gl.uniform1f(uAspectLoc, Math.max(0.1, cssW / Math.max(1, cssH)));
        gl.uniform1f(uDprLoc, dpr);
        gl.bindVertexArray(vao);
        gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, vertexData);
        gl.drawArrays(gl.POINTS, 0, COUNT);
        gl.bindVertexArray(0);
      } else if (ctx2d) {
        ctx2d.clearRect(0, 0, pxW, pxH);
        const cx2 = pxW * 0.5, cy2 = pxH * 0.5;
        const sc = Math.min(pxW, pxH) * 0.48;
        for (let i = 0; i < COUNT; i += 2) {
          const a = alphas[i];
          if (a < 0.03) continue;
          const persp = 1.9 / Math.max(0.4, 2.6 - posZ[i]);
          const o = i * 8;
          ctx2d.fillStyle = `rgba(${Math.round(vertexData[o + 3] * 255)},${Math.round(vertexData[o + 4] * 255)},${Math.round(vertexData[o + 5] * 255)},${a.toFixed(2)})`;
          ctx2d.beginPath();
          ctx2d.arc(cx2 + posX[i] * persp * sc, cy2 - posY[i] * persp * sc, Math.max(1, sizes[i] * persp * 0.4), 0, Math.PI * 2);
          ctx2d.fill();
        }
      }

      rafId = requestAnimationFrame(animate);
    };

    rafId = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(rafId);
      if (gl && program) gl.deleteProgram(program);
      if (gl && vbo) gl.deleteBuffer(vbo);
      if (gl && vao) gl.deleteVertexArray(vao);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      onClick={onClick}
      aria-label="DarkShadow 3D Particle Simulation"
      className="w-full h-full block cursor-pointer"
    />
  );
}

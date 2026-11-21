import { useEffect, useRef } from "react";
import type { AudioBands, ParticlePhase, ParticleShape } from "./ParticleOrbWebGL.tsx";

interface ParticleOrbNextGenProps {
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
uniform float uTime;
uniform vec3 uAudio;       // bass, mid, treble
uniform vec2 uMouse;       // normalized pointer [-1, 1]
uniform float uMouseHover; // hover intensity [0, 1]

out vec3 vColor;
out float vAlpha;

// Simplex 3D noise
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
             i.z + vec4(0.0, i1.z, i2.z, 1.0))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  vec3 ns = 0.142857142857 * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

vec3 curlNoise(vec3 p) {
  const float e = 0.08;
  float dx = (snoise(p + vec3(e, 0.0, 0.0)) - snoise(p - vec3(e, 0.0, 0.0))) / (2.0 * e);
  float dy = (snoise(p + vec3(0.0, e, 0.0)) - snoise(p - vec3(0.0, e, 0.0))) / (2.0 * e);
  float dz = (snoise(p + vec3(0.0, 0.0, e)) - snoise(p - vec3(0.0, 0.0, e))) / (2.0 * e);
  return vec3(dy - dz, dz - dx, dx - dy);
}

void main() {
  vec3 pos = aPos;

  // Cosmic fluid turbulence
  vec3 curl = curlNoise(pos * 2.0 + vec3(0.0, uTime * 0.16, 0.0));
  pos += curl * (0.04 + uAudio.x * 0.07);

  // Magnetic cursor gravity
  if (uMouseHover > 0.02) {
    vec2 toM = uMouse - pos.xy;
    float dist = length(toM);
    if (dist < 0.7) {
      pos.xy += (toM / (dist + 0.2)) * 0.08 * uMouseHover;
    }
  }

  float zCam = 2.6 - pos.z;
  float persp = 1.9 / max(0.4, zCam);
  gl_Position = vec4(pos.x / uAspect * persp, pos.y * persp, 0.0, 1.0);
  gl_PointSize = clamp(aSize * persp * uDpr * (1.0 + uAudio.y * 0.45), 1.6, 32.0);

  // Chromatic Luminescence
  vColor = aColor + vec3(uAudio.z * 0.25, uAudio.y * 0.18, uAudio.x * 0.20);
  vAlpha = aAlpha * clamp(persp * 0.95, 0.35, 1.0);
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

  float core = exp(-distSq * 42.0);
  float halo = exp(-distSq * 6.8);
  vec3 col = mix(vColor, vec3(1.0), core * 0.72);
  float alpha = clamp((core * 1.5 + halo * 0.6) * vAlpha, 0.0, 1.0);
  fragColor = vec4(col * alpha, alpha);
}
`;

function createShader(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error("Shader compile error:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

const COUNT = 6500;

export function ParticleOrbNextGen({
  phase,
  shape,
  audioBands,
  reducedMotion,
  onRiseComplete,
  onDissolveComplete,
  onClick,
}: ParticleOrbNextGenProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const phaseRef = useRef(phase);
  const shapeRef = useRef(shape);
  const audioRef = useRef(audioBands);
  const motionRef = useRef(reducedMotion);
  const onRiseCompleteRef = useRef(onRiseComplete);
  const onDissolveCompleteRef = useRef(onDissolveComplete);

  const mousePosRef = useRef<[number, number]>([-999, -999]);
  const mouseHoverRef = useRef<number>(0);

  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { shapeRef.current = shape; }, [shape]);
  useEffect(() => { audioRef.current = audioBands; }, [audioBands]);
  useEffect(() => { motionRef.current = reducedMotion; }, [reducedMotion]);
  useEffect(() => { onRiseCompleteRef.current = onRiseComplete; }, [onRiseComplete]);
  useEffect(() => { onDissolveCompleteRef.current = onDissolveComplete; }, [onDissolveComplete]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: true,
    });

    if (!gl) return;

    const vert = createShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    const frag = createShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    if (!vert || !frag) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vert);
    gl.attachShader(program, frag);
    gl.linkProgram(program);

    const uAspectLoc = gl.getUniformLocation(program, "uAspect");
    const uDprLoc = gl.getUniformLocation(program, "uDpr");
    const uTimeLoc = gl.getUniformLocation(program, "uTime");
    const uAudioLoc = gl.getUniformLocation(program, "uAudio");
    const uMouseLoc = gl.getUniformLocation(program, "uMouse");
    const uMouseHoverLoc = gl.getUniformLocation(program, "uMouseHover");

    const posX = new Float32Array(COUNT);
    const posY = new Float32Array(COUNT);
    const posZ = new Float32Array(COUNT);
    const velX = new Float32Array(COUNT);
    const velY = new Float32Array(COUNT);
    const velZ = new Float32Array(COUNT);

    const s0X = new Float32Array(COUNT), s0Y = new Float32Array(COUNT), s0Z = new Float32Array(COUNT);
    const s1X = new Float32Array(COUNT), s1Y = new Float32Array(COUNT), s1Z = new Float32Array(COUNT);
    const s2X = new Float32Array(COUNT), s2Y = new Float32Array(COUNT), s2Z = new Float32Array(COUNT);
    const s3X = new Float32Array(COUNT), s3Y = new Float32Array(COUNT), s3Z = new Float32Array(COUNT);

    const colR = new Float32Array(COUNT);
    const colG = new Float32Array(COUNT);
    const colB = new Float32Array(COUNT);
    const sizes = new Float32Array(COUNT);
    const alphas = new Float32Array(COUNT);
    const pPhase = new Float32Array(COUNT);
    const vertexData = new Float32Array(COUNT * 8);

    const golden = Math.PI * (1 + Math.sqrt(5));
    const ORB_RADIUS = 0.23;

    for (let i = 0; i < COUNT; i++) {
      const idx = i + 0.5;
      const s = ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1;
      const s2 = ((Math.sin(i * 78.233 + 1.7) * 43758.5453) % 1 + 1) % 1;
      pPhase[i] = s2 * Math.PI * 2;

      // Sphere
      const phi = Math.acos(1 - (2 * idx) / COUNT);
      const theta = golden * idx;
      const r = (i % 6 === 0) ? ORB_RADIUS * 0.90 + s * 0.025 : ORB_RADIUS + (s2 - 0.5) * 0.015;
      s0X[i] = Math.sin(phi) * Math.cos(theta) * r;
      s0Y[i] = Math.cos(phi) * r;
      s0Z[i] = Math.sin(phi) * Math.sin(theta) * r;

      // Helix
      const strand = (i % 2 === 0) ? 0 : Math.PI;
      const helixT = (i / COUNT) * Math.PI * 8.0;
      const hRad = 0.16 + (s - 0.5) * 0.03;
      s1X[i] = Math.cos(helixT + strand) * hRad;
      s1Y[i] = ((i / COUNT) - 0.5) * 0.65;
      s1Z[i] = Math.sin(helixT + strand) * hRad;

      // Torus
      const torusU = (i / COUNT) * Math.PI * 2.0;
      const torusV = ((i % 120) / 120) * Math.PI * 2.0;
      const R = 0.22, rTube = 0.07;
      s2X[i] = (R + rTube * Math.cos(torusV)) * Math.cos(torusU);
      s2Y[i] = (R + rTube * Math.cos(torusV)) * Math.sin(torusU);
      s2Z[i] = rTube * Math.sin(torusV);

      // Cube
      const sideIdx = i % 6;
      const u = (s - 0.5) * 0.38, v = (s2 - 0.5) * 0.38, d = 0.19;
      if (sideIdx === 0) { s3X[i] = d; s3Y[i] = u; s3Z[i] = v; }
      else if (sideIdx === 1) { s3X[i] = -d; s3Y[i] = u; s3Z[i] = v; }
      else if (sideIdx === 2) { s3X[i] = u; s3Y[i] = d; s3Z[i] = v; }
      else if (sideIdx === 3) { s3X[i] = u; s3Y[i] = -d; s3Z[i] = v; }
      else if (sideIdx === 4) { s3X[i] = u; s3Y[i] = v; s3Z[i] = d; }
      else { s3X[i] = u; s3Y[i] = v; s3Z[i] = -d; }

      posX[i] = s0X[i];
      posY[i] = s0Y[i];
      posZ[i] = s0Z[i];

      colR[i] = 0.92 + s * 0.08;
      colG[i] = 0.95 + s2 * 0.05;
      colB[i] = 1.0;
      sizes[i] = 1.8 + s * 2.4;
      alphas[i] = 0.85;
    }

    const vao = gl.createVertexArray();
    const vbo = gl.createBuffer();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, vertexData.byteLength, gl.DYNAMIC_DRAW);
    const stride = 32;
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, stride, 12);
    gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 1, gl.FLOAT, false, stride, 24);
    gl.enableVertexAttribArray(3); gl.vertexAttribPointer(3, 1, gl.FLOAT, false, stride, 28);
    gl.bindVertexArray(null);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    let lastTime = performance.now();
    let t = 0;
    let sBass = 0, sMid = 0, sTreble = 0;
    let rafId: number;

    const animate = (now: number) => {
      const dt = Math.min(0.035, (now - lastTime) / 1000);
      lastTime = now;
      t += dt;

      const audio = audioRef.current;
      sBass += (audio.bass - sBass) * Math.min(1, dt * 14);
      sMid += (audio.mid - sMid) * Math.min(1, dt * 14);
      sTreble += (audio.treble - sTreble) * Math.min(1, dt * 16);

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      const aspect = Math.max(0.1, w / Math.max(1, h));

      const curShape = shapeRef.current;
      let targetShapeIdx = 0;
      if (curShape === "helix") targetShapeIdx = 1;
      else if (curShape === "torus") targetShapeIdx = 2;
      else if (curShape === "shield") targetShapeIdx = 3;

      // PURE SOLAR 3D ROTATION: Sthir Center rotating 360-degrees on its axis (ZERO tilt, ZERO flattening)
      const rotY = t * (0.32 + sMid * 0.4);
      const cy = Math.cos(rotY), sy = Math.sin(rotY);
      const voiceBoost = 1.0 + sBass * 0.16 + sMid * 0.08;
      const springK = 18.0;
      const damping = 5.0;

      for (let i = 0; i < COUNT; i++) {
        let tx0 = s0X[i], ty0 = s0Y[i], tz0 = s0Z[i];
        if (targetShapeIdx === 1) { tx0 = s1X[i]; ty0 = s1Y[i]; tz0 = s1Z[i]; }
        else if (targetShapeIdx === 2) { tx0 = s2X[i]; ty0 = s2Y[i]; tz0 = s2Z[i]; }
        else if (targetShapeIdx === 3) { tx0 = s3X[i]; ty0 = s3Y[i]; tz0 = s3Z[i]; }

        // Pure axial rotation around Y (like the Sun rotating on its axis, ZERO tilt):
        const x1 = tx0 * cy - tz0 * sy;
        const y2 = ty0; // Perfectly anchored vertical axis
        const z2 = tx0 * sy + tz0 * cy;

        const wave = 1.0 + 0.02 * Math.sin(pPhase[i] + t * 4.0);
        const scale = voiceBoost * wave;

        const targetX = x1 * scale;
        const targetY = y2 * scale;
        const targetZ = z2 * scale;

        velX[i] += ((targetX - posX[i]) * springK - velX[i] * damping) * dt;
        velY[i] += ((targetY - posY[i]) * springK - velY[i] * damping) * dt;
        velZ[i] += ((targetZ - posZ[i]) * springK - velZ[i] * damping) * dt;

        posX[i] += velX[i] * dt;
        posY[i] += velY[i] * dt;
        posZ[i] += velZ[i] * dt;

        const o = i * 8;
        vertexData[o] = posX[i];
        vertexData[o + 1] = posY[i];
        vertexData[o + 2] = posZ[i];
        vertexData[o + 3] = colR[i];
        vertexData[o + 4] = colG[i];
        vertexData[o + 5] = colB[i];
        vertexData[o + 6] = sizes[i] * (1.0 + sBass * 0.40);
        vertexData[o + 7] = alphas[i];
      }

      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);

      gl.useProgram(program);
      gl.uniform1f(uAspectLoc, aspect);
      gl.uniform1f(uDprLoc, dpr);
      gl.uniform1f(uTimeLoc, t);
      gl.uniform3f(uAudioLoc, sBass, sMid, sTreble);
      gl.uniform2f(uMouseLoc, mousePosRef.current[0], mousePosRef.current[1]);
      gl.uniform1f(uMouseHoverLoc, mouseHoverRef.current);

      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, vertexData);
      gl.drawArrays(gl.POINTS, 0, COUNT);
      gl.bindVertexArray(null);

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

  const handlePointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const ny = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
    mousePosRef.current = [nx, ny];
    mouseHoverRef.current = 1.0;
  };

  const handlePointerLeave = () => {
    mouseHoverRef.current = 0.0;
  };

  return (
    <canvas
      ref={canvasRef}
      onClick={onClick}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      aria-label="DarkShadow Next-Gen 3D Particle Simulation"
      className="w-full h-full block cursor-pointer"
    />
  );
}

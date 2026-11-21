import { useEffect, useRef } from "react";
import type { CoreState } from "../types/darkshadow";

interface ParticleCoreProps {
  coreState: CoreState;
  energyRef: React.MutableRefObject<number>;
  standby?: boolean;
}

const VERTEX_SHADER = `#version 300 es
precision highp float;

layout(location = 0) in vec3 aSeed;
layout(location = 1) in float aSize;

uniform float uTime;
uniform float uAudio;
uniform float uState;      // 0=idle, 1=listening, 2=thinking, 3=speaking
uniform float uStandby;    // 0=active, 1=standby
uniform vec2  uResolution;
uniform vec2  uPointer;

out float vAlpha;
out float vTone;

void main() {
  float theta = aSeed.x;
  float phi   = aSeed.y;
  float layer = aSeed.z;

  // Zero-tilt solar rotation anchored smoothly around the vertical Y-axis
  float spinSpeed = mix(0.16, 0.52, clamp(uState * 0.35 + uAudio * 0.45, 0.0, 1.0));
  spinSpeed *= mix(1.0, 0.35, uStandby);

  float rotAngle = theta + uTime * spinSpeed * (0.65 + layer * 0.55);

  // Subtle organic radial breathing + audio reactive expansion
  float breath = sin(uTime * 1.45 + phi * 4.0 + layer * 6.2831) * 0.035;
  float pulse = uAudio * (0.14 + 0.12 * sin(phi * 9.0 - uTime * 7.0));
  float thinkSwirl = (uState > 1.5 && uState < 2.5)
    ? sin(uTime * 4.2 + phi * 6.0 + theta * 2.0) * 0.065
    : 0.0;

  float baseRadius = mix(0.32, 0.62, layer);
  float r = baseRadius + breath + pulse + thinkSwirl;

  // Spherical shell with equatorial density emphasis
  float sinPhi = sin(phi);
  vec3 pos = vec3(
    r * sinPhi * cos(rotAngle),
    r * cos(phi) * 0.94,
    r * sinPhi * sin(rotAngle)
  );

  // Subtle magnetic cursor repulsion in normalized viewport space
  float aspect = uResolution.x / max(uResolution.y, 1.0);
  vec2 projected = vec2(pos.x / aspect, pos.y);
  vec2 delta = projected - uPointer;
  float dist = length(delta);
  if (dist < 0.28 && dist > 0.0001) {
    float force = (1.0 - dist / 0.28) * 0.055;
    pos.xy += normalize(delta) * force * vec2(aspect, 1.0);
  }

  // Perspective projection (zero vertical/horizontal tilt)
  float cameraZ = 1.95;
  float zDepth = cameraZ - pos.z;
  float fov = 1.42;
  vec2 screenPos = vec2(pos.x / aspect, pos.y) * (fov / max(zDepth, 0.4));

  gl_Position = vec4(screenPos, 0.0, 1.0);

  float depthFactor = clamp((pos.z + 0.7) / 1.4, 0.15, 1.0);
  gl_PointSize = aSize * (1.25 + depthFactor * 1.95 + uAudio * 1.4) * (min(uResolution.x, uResolution.y) / 900.0);

  float standbyDim = mix(1.0, 0.24, uStandby);
  vAlpha = (0.18 + 0.74 * depthFactor) * standbyDim;
  vTone = clamp(layer * 0.7 + depthFactor * 0.3 + uAudio * 0.25, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;

in float vAlpha;
in float vTone;

uniform float uState;
uniform float uAudio;

out vec4 fragColor;

void main() {
  vec2 uv = gl_PointCoord - vec2(0.5);
  float d = length(uv);
  if (d > 0.5) discard;

  float core = smoothstep(0.5, 0.04, d);
  float glow = pow(core, 1.85);

  // Palette per state:
  // Idle: deep cobalt -> ice cyan
  // Listening: emerald -> bright aqua
  // Thinking: indigo -> luminous violet
  // Speaking: royal cyan -> warm white-gold highlight
  vec3 idleA = vec3(0.14, 0.40, 0.96);
  vec3 idleB = vec3(0.45, 0.85, 1.00);

  vec3 listenA = vec3(0.06, 0.72, 0.58);
  vec3 listenB = vec3(0.46, 0.98, 0.86);

  vec3 thinkA = vec3(0.44, 0.30, 0.98);
  vec3 thinkB = vec3(0.76, 0.62, 1.00);

  vec3 speakA = vec3(0.18, 0.68, 1.00);
  vec3 speakB = vec3(0.92, 0.96, 1.00);

  vec3 colA = idleA;
  vec3 colB = idleB;
  if (uState > 0.5 && uState < 1.5) {
    colA = listenA;
    colB = listenB;
  } else if (uState >= 1.5 && uState < 2.5) {
    colA = thinkA;
    colB = thinkB;
  } else if (uState >= 2.5) {
    colA = speakA;
    colB = speakB;
  }

  vec3 color = mix(colA, colB, vTone);
  color += vec3(0.15, 0.22, 0.30) * uAudio * glow;

  fragColor = vec4(color, glow * vAlpha);
}
`;

const PARTICLE_COUNT = 6400;

function stateToFloat(state: CoreState): number {
  switch (state) {
    case "listening":
      return 1;
    case "thinking":
      return 2;
    case "speaking":
      return 3;
    default:
      return 0;
  }
}

export function ParticleCore({ coreState, energyRef, standby = false }: ParticleCoreProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef<CoreState>(coreState);
  const standbyRef = useRef<boolean>(standby);

  useEffect(() => {
    stateRef.current = coreState;
  }, [coreState]);

  useEffect(() => {
    standbyRef.current = standby;
  }, [standby]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl2", {
      alpha: false,
      antialias: true,
      powerPreference: "high-performance",
    });
    if (!gl) return;

    const compileShader = (type: number, source: string) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    };

    const vs = compileShader(gl.VERTEX_SHADER, VERTEX_SHADER);
    const fs = compileShader(gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    if (!vs || !fs) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteProgram(program);
      return;
    }

    // Generate deterministic Fibonacci + layered sphere particle seeds
    const seeds = new Float32Array(PARTICLE_COUNT * 3);
    const sizes = new Float32Array(PARTICLE_COUNT);
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const t = (i + 0.5) / PARTICLE_COUNT;
      const phi = Math.acos(1 - 2 * t);
      const theta = goldenAngle * i;
      const layer = Math.pow((i * 0.61803398875) % 1, 0.72);
      seeds[i * 3] = theta;
      seeds[i * 3 + 1] = phi;
      seeds[i * 3 + 2] = layer;
      sizes[i] = 1.35 + ((i * 19) % 100) * 0.024;
    }

    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);

    const seedBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, seedBuf);
    gl.bufferData(gl.ARRAY_BUFFER, seeds, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);

    const sizeBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, sizeBuf);
    gl.bufferData(gl.ARRAY_BUFFER, sizes, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 0, 0);

    gl.bindVertexArray(null);

    const uTime = gl.getUniformLocation(program, "uTime");
    const uAudio = gl.getUniformLocation(program, "uAudio");
    const uState = gl.getUniformLocation(program, "uState");
    const uStandby = gl.getUniformLocation(program, "uStandby");
    const uResolution = gl.getUniformLocation(program, "uResolution");
    const uPointer = gl.getUniformLocation(program, "uPointer");

    const pointer = { x: 10, y: 10, tx: 10, ty: 10 };
    const handlePointerMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      pointer.tx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.ty = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
    };
    const handlePointerLeave = () => {
      pointer.tx = 10;
      pointer.ty = 10;
    };

    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointerleave", handlePointerLeave, { passive: true });

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      const height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
    };

    resize();
    window.addEventListener("resize", resize);

    let rafId = 0;
    let smoothedAudio = 0;
    let smoothedState = 0;
    let smoothedStandby = 0;
    const startMs = performance.now();

    const render = (now: number) => {
      resize();
      const elapsed = (now - startMs) * 0.001;

      const targetState = stateToFloat(stateRef.current);
      const targetStandby = standbyRef.current ? 1 : 0;

      // Synthetic subtle speaking wave when speaking without live mic RMS
      let targetAudio = energyRef.current;
      if (stateRef.current === "speaking" && targetAudio < 0.12) {
        targetAudio = 0.26 + Math.abs(Math.sin(elapsed * 7.8) * Math.cos(elapsed * 3.1)) * 0.42;
      } else if (stateRef.current === "thinking" && targetAudio < 0.08) {
        targetAudio = 0.16 + Math.abs(Math.sin(elapsed * 4.5)) * 0.14;
      }

      smoothedAudio += (targetAudio - smoothedAudio) * 0.14;
      smoothedState += (targetState - smoothedState) * 0.08;
      smoothedStandby += (targetStandby - smoothedStandby) * 0.08;
      pointer.x += (pointer.tx - pointer.x) * 0.1;
      pointer.y += (pointer.ty - pointer.y) * 0.1;

      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);

      gl.useProgram(program);
      gl.bindVertexArray(vao);

      gl.uniform1f(uTime, elapsed);
      gl.uniform1f(uAudio, smoothedAudio);
      gl.uniform1f(uState, smoothedState);
      gl.uniform1f(uStandby, smoothedStandby);
      gl.uniform2f(uResolution, canvas.width, canvas.height);
      gl.uniform2f(uPointer, pointer.x, pointer.y);

      gl.drawArrays(gl.POINTS, 0, PARTICLE_COUNT);
      gl.bindVertexArray(null);

      rafId = requestAnimationFrame(render);
    };

    rafId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerleave", handlePointerLeave);
      gl.deleteBuffer(seedBuf);
      gl.deleteBuffer(sizeBuf);
      gl.deleteVertexArray(vao);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
    };
  }, [energyRef]);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 h-full w-full block pointer-events-none select-none"
      aria-hidden="true"
    />
  );
}

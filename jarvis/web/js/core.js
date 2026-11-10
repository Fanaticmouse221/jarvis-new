// The Core: JARVIS's presence on screen. Concentric arcs drawn on a canvas that
// turn slowly at rest and quicken while JARVIS is working.
// States: "idle" | "thinking" | "offline".

const TAU = Math.PI * 2;
const RINGS = [
  { radius: 0.92, width: 1, arcs: [[0, TAU]], speed: 0, alpha: 0.22 },
  { radius: 0.8, width: 2, arcs: [[0, 1.5], [2.2, 3.9], [4.6, 5.9]], speed: 0.16, alpha: 0.85 },
  { radius: 0.64, width: 1.5, arcs: [[0.4, 2.6], [3.6, 5.7]], speed: -0.26, alpha: 0.6 },
  { radius: 0.48, width: 3, arcs: [[0, 0.9], [1.6, 2.5], [3.2, 4.1], [4.8, 5.7]], speed: 0.42, alpha: 0.9 },
];

export function createCore(canvas) {
  const context = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let state = "idle";
  let energy = 0; // eases towards 1 while thinking
  let angle = 0;
  let last = performance.now();
  let frame = null;

  function draw(now) {
    frame = null;
    if (!canvas.isConnected) return; // the view was replaced; stop quietly
    const ratio = window.devicePixelRatio || 1;
    const size = canvas.clientWidth || 148;
    if (canvas.width !== Math.round(size * ratio)) {
      canvas.width = canvas.height = Math.round(size * ratio);
    }
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    energy += ((state === "thinking" ? 1 : 0) - energy) * Math.min(dt * 4, 1);
    angle += dt * (1 + energy * 4.5);

    const mid = canvas.width / 2;
    const offline = state === "offline";
    const colour = offline ? "111, 132, 160" : "95, 212, 255";
    context.clearRect(0, 0, canvas.width, canvas.height);

    const glow = context.createRadialGradient(mid, mid, 0, mid, mid, mid);
    glow.addColorStop(0, `rgba(${colour}, ${offline ? 0.05 : 0.16 + energy * 0.12})`);
    glow.addColorStop(1, `rgba(${colour}, 0)`);
    context.fillStyle = glow;
    context.fillRect(0, 0, canvas.width, canvas.height);

    context.lineCap = "round";
    for (const ring of RINGS) {
      context.lineWidth = ring.width * ratio;
      context.strokeStyle = `rgba(${colour}, ${ring.alpha * (offline ? 0.5 : 1)})`;
      const turn = angle * ring.speed;
      for (const [from, to] of ring.arcs) {
        context.beginPath();
        context.arc(mid, mid, ring.radius * (mid - 2 * ratio), from + turn, to + turn);
        context.stroke();
      }
    }
    const pulse = 1 + Math.sin(now / (state === "thinking" ? 180 : 900)) * (0.04 + energy * 0.08);
    context.beginPath();
    context.arc(mid, mid, mid * 0.2 * pulse, 0, TAU);
    context.fillStyle = offline ? "rgba(111, 132, 160, 0.7)" : "rgba(214, 243, 255, 0.95)";
    context.fill();

    if (!reduceMotion && !document.hidden) frame = requestAnimationFrame(draw);
  }

  const start = () => {
    if (frame === null) {
      last = performance.now();
      frame = requestAnimationFrame(draw);
    }
  };
  document.addEventListener("visibilitychange", start);
  start();

  return {
    setState(next) {
      state = next;
      start();
    },
  };
}

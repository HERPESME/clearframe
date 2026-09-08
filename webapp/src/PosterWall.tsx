/**
 * A wall of posters with no films on it.
 *
 * The sign-in screen wants to say "this is a movie tool" the way a streaming
 * service does — a library glowing in a dark room. But this is a RIGHTS
 * CLEARANCE product, so decorating it with anybody's actual one-sheets would
 * be the product failing its own audit in the first frame. Every poster here
 * is drawn: six composition archetypes (the light cone, the duotone split,
 * the low sun, the noir slit, the ring, the stacked title block) over a small
 * set of cinematic hue pairs, each finished with the universal credits block
 * at the foot — which is the detail that makes a rectangle read as a poster.
 *
 * Deterministic per index, so the wall is stable across renders and there is
 * nothing to load.
 */

type Palette = { ground: string; light: string; mid: string };

const PALETTES: Palette[] = [
  { ground: "#0a1024", light: "#f5c451", mid: "#8f6b1f" }, // tungsten on navy
  { ground: "#1a0b2e", light: "#ec4899", mid: "#7c2d64" }, // magenta neon
  { ground: "#06131f", light: "#2dd4bf", mid: "#155e56" }, // teal night
  { ground: "#081228", light: "#4f9cf9", mid: "#1d4a80" }, // projector blue
  { ground: "#250a18", light: "#fb7185", mid: "#7c2d3e" }, // coral wine
  { ground: "#120a2e", light: "#a78bfa", mid: "#4c3a85" }, // violet
];

function Credits({ light }: { light: string }) {
  // The credits block: one title bar, two contact-strip lines.
  return (
    <g opacity={0.85}>
      <rect x="30" y="238" width="140" height="13" rx="2" fill={light} opacity="0.9" />
      <rect x="46" y="260" width="108" height="4" rx="2" fill="#ffffff" opacity="0.35" />
      <rect x="58" y="270" width="84" height="4" rx="2" fill="#ffffff" opacity="0.22" />
    </g>
  );
}

function Tile({ seed }: { seed: number }) {
  // Knuth-hash the index so archetype and palette decorrelate — a stride over
  // a modulus of 6 can only be 1 or 5, and 3 visits two of the six kinds.
  const h = (seed * 2654435761) >>> 0;
  const p = PALETTES[h % PALETTES.length];
  const kind = (h >>> 3) % 6;
  const gid = `pw${seed}`;
  return (
    <svg className="pw-tile" viewBox="0 0 200 300" aria-hidden="true">
      <rect width="200" height="300" fill={p.ground} />
      {kind === 0 && (
        // The light cone: a beam from the top corner, a figure at its foot.
        <>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0.5" y2="1">
              <stop offset="0%" stopColor={p.light} stopOpacity="0.75" />
              <stop offset="90%" stopColor={p.light} stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points="60,-10 140,-10 180,220 20,220" fill={`url(#${gid})`} />
          <rect x="92" y="168" width="16" height="44" rx="8" fill={p.ground} />
          <circle cx="100" cy="158" r="11" fill={p.ground} />
        </>
      )}
      {kind === 1 && (
        // The duotone split: a seam, and a moon riding it.
        <>
          <polygon points="0,0 200,0 200,90 0,210" fill={p.mid} opacity="0.55" />
          <circle cx="128" cy="128" r="46" fill={p.light} opacity="0.85" />
          <circle cx="112" cy="118" r="40" fill={p.ground} opacity="0.9" />
        </>
      )}
      {kind === 2 && (
        // The low sun: banded sky, heavy horizon.
        <>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={p.mid} stopOpacity="0.4" />
              <stop offset="70%" stopColor={p.light} stopOpacity="0.55" />
              <stop offset="100%" stopColor={p.ground} />
            </linearGradient>
          </defs>
          <rect width="200" height="220" fill={`url(#${gid})`} />
          <circle cx="100" cy="172" r="34" fill={p.light} />
          <rect x="0" y="188" width="200" height="44" fill={p.ground} />
        </>
      )}
      {kind === 3 && (
        // Noir: one slit of light, one silhouette.
        <>
          <rect x="86" y="0" width="26" height="232" fill={p.light} opacity="0.5" />
          <rect x="94" y="0" width="10" height="232" fill={p.light} opacity="0.85" />
          <rect x="70" y="150" width="60" height="82" fill={p.ground} />
          <circle cx="100" cy="142" r="15" fill={p.ground} />
        </>
      )}
      {kind === 4 && (
        // The ring: an iris, a lens, an eclipse — pick your genre.
        <>
          <circle cx="100" cy="120" r="62" fill="none" stroke={p.light} strokeWidth="10" opacity="0.9" />
          <circle cx="100" cy="120" r="34" fill={p.mid} opacity="0.5" />
          <circle cx="100" cy="120" r="8" fill={p.light} />
        </>
      )}
      {kind === 5 && (
        // The stacked title block: the typographic poster, letterforms implied.
        <>
          <rect x="24" y="42" width="152" height="30" rx="3" fill={p.light} opacity="0.92" />
          <rect x="24" y="80" width="118" height="30" rx="3" fill={p.light} opacity="0.65" />
          <rect x="24" y="118" width="136" height="30" rx="3" fill={p.mid} opacity="0.8" />
          <rect x="24" y="162" width="70" height="10" rx="2" fill="#ffffff" opacity="0.3" />
        </>
      )}
      <Credits light={p.light} />
    </svg>
  );
}

export function PosterWall({ count = 40 }: { count?: number }) {
  return (
    <div className="poster-wall" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <Tile key={i} seed={i} />
      ))}
    </div>
  );
}

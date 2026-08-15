import type { Element, Risk, RiskBand } from "./types";
import { tc } from "./timecode";

const BAND_VAR: Record<RiskBand, string> = {
  CRITICAL: "var(--critical)",
  HIGH: "var(--high)",
  MEDIUM: "var(--medium)",
  LOW: "var(--low)",
};

interface Props {
  elements: Element[];
  risk: Record<string, Risk>;
  durationS: number;
  fps: number;
  activeId: string | null;
  onJump: (id: string) => void;
}

const LANE_H = 12;
const LANE_GAP = 4;
const RULER_H = 22;

export function Timeline({ elements, risk, durationS, fps, activeId, onJump }: Props) {
  const width = 1000;
  const height = RULER_H + elements.length * (LANE_H + LANE_GAP);
  const x = (s: number) => (s / durationS) * width;

  const tickEvery = durationS > 120 ? 30 : 10;
  const ticks: number[] = [];
  for (let s = 0; s <= durationS; s += tickEvery) ticks.push(s);

  return (
    <div className="timeline-wrap">
      <div className="timeline-title">
        Clearance timeline · {tc(0, fps)} → {tc(durationS, fps)}
      </div>
      <svg
        className="timeline-svg"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{ height }}
        role="img"
        aria-label="Timeline of detected elements colored by risk"
      >
        {/* ruler */}
        <line x1={0} y1={RULER_H - 6} x2={width} y2={RULER_H - 6} stroke="var(--line)" />
        {ticks.map((s) => (
          <g key={s}>
            <line
              x1={x(s)}
              y1={RULER_H - 10}
              x2={x(s)}
              y2={RULER_H - 2}
              stroke="var(--line)"
            />
            <text
              x={Math.min(x(s) + 3, width - 60)}
              y={10}
              fill="var(--muted)"
              fontSize={9}
              fontFamily="var(--mono)"
            >
              {tc(s, fps)}
            </text>
          </g>
        ))}
        {/* lanes */}
        {elements.map((el, i) => {
          const y = RULER_H + i * (LANE_H + LANE_GAP);
          const band = risk[el.id]?.band ?? "LOW";
          const isActive = activeId === el.id;
          return (
            <g key={el.id}>
              <line
                x1={0}
                y1={y + LANE_H / 2}
                x2={width}
                y2={y + LANE_H / 2}
                stroke="var(--line)"
                strokeDasharray="1 5"
              />
              {el.time_ranges.map((r, j) => (
                <rect
                  key={j}
                  className="lane-block"
                  x={x(r.start_s)}
                  y={y}
                  width={Math.max(x(r.end_s) - x(r.start_s), 3)}
                  height={LANE_H}
                  rx={1.5}
                  fill={BAND_VAR[band]}
                  opacity={isActive ? 1 : 0.65}
                  stroke={isActive ? "var(--ink)" : "none"}
                  strokeWidth={isActive ? 1 : 0}
                  onClick={() => onJump(el.id)}
                >
                  <title>{`${el.label} · ${tc(r.start_s, fps)}–${tc(r.end_s, fps)}`}</title>
                </rect>
              ))}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

import { forwardRef, useEffect, useRef, useState } from "react";
import type { BBox, Corroboration, Coverage, Element, Risk } from "./types";
import { tc } from "./timecode";

interface Props {
  pid: string;
  elements: Element[];
  risk: Record<string, Risk>;
  corroboration: Record<string, Corroboration>;
  coverage: Record<string, Coverage>;
  fps: number;
  activeId: string | null;
  onPick: (id: string) => void;
}

/**
 * The footage, with every detection boxed on the frame it appears in.
 *
 * Detection boxes are normalized 0-1, so the overlay maps straight onto the
 * video element as long as the video fills its box (width:100%, height:auto).
 * A coordinator can scrub to 00:08 and see the swoosh outlined, labelled with
 * what it is, whether two detectors agreed, and whether it is already licensed.
 */
export const VideoPlayer = forwardRef<HTMLVideoElement, Props>(function VideoPlayer(
  { pid, elements, risk, corroboration, coverage, fps, activeId, onPick },
  ref,
) {
  const [now, setNow] = useState(0);
  const [ok, setOk] = useState(true);
  const localRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    setOk(true);
  }, [pid]);

  if (!ok) return null;

  const onFrame = (e: React.SyntheticEvent<HTMLVideoElement>) =>
    setNow(e.currentTarget.currentTime);

  // Mirrors clearframe/overlay.py::box_at exactly — one rule, two runtimes.
  // The box belongs to the APPEARANCE, so pausing at 1s gives the opening
  // shot's rectangle and pausing at 27s gives the third's. Two fallbacks keep
  // older states drawing rather than silently losing every box on upgrade.
  const BOX_WINDOW_S = 2.0;
  const boxAt = (el: Element): BBox | null => {
    const appearance = el.time_ranges.find(
      (r) => now >= r.start_s && now <= r.end_s,
    );
    if (!appearance) return null;
    if (appearance.bbox) return appearance.bbox;
    if (!el.bbox) return null;
    if (el.at_s !== null && el.at_s !== undefined) {
      return Math.abs(now - el.at_s) <= BOX_WINDOW_S ? el.bbox : null;
    }
    return el.bbox;
  };

  const visible = elements
    .map((el) => ({ el, box: boxAt(el) }))
    .filter((v): v is { el: Element; box: BBox } => v.box !== null);

  // On screen but we do not know where. Worth saying — silence would read as
  // "nothing here", and inventing a rectangle would be worse than both.
  const unlocated = elements.filter(
    (el) =>
      boxAt(el) === null &&
      el.time_ranges.some((r) => now >= r.start_s && now <= r.end_s),
  );

  const COV_LABEL: Record<string, string> = {
    COVERED: "licensed",
    PARTIAL: "licence gap",
    NOT_COVERED: "unlicensed",
    UNKNOWN: "coverage unknown",
  };

  return (
    <div className="player-wrap">
      <div className="player-frame">
        <video
          ref={(node) => {
            localRef.current = node;
            if (typeof ref === "function") ref(node);
            else if (ref) (ref as React.MutableRefObject<HTMLVideoElement | null>).current = node;
          }}
          src={`/api/productions/${pid}/media`}
          controls
          preload="metadata"
          onTimeUpdate={onFrame}
          onSeeked={onFrame}
          onError={() => setOk(false)}
        />
        <svg
          className="player-overlay"
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          aria-hidden={visible.length === 0}
        >
          {visible.map(({ el, box: b }) => {
            const band = risk[el.id]?.band ?? "LOW";
            const active = activeId === el.id;
            return (
              <g key={el.id} className="ov-g" onClick={() => onPick(el.id)}>
                <rect
                  x={b.xmin}
                  y={b.ymin}
                  width={Math.max(b.xmax - b.xmin, 0.004)}
                  height={Math.max(b.ymax - b.ymin, 0.004)}
                  className={`ov-box ${band} ${active ? "active" : ""}`}
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            );
          })}
        </svg>
        {visible.map(({ el, box: b }) => {
          const band = risk[el.id]?.band ?? "LOW";
          const cov = coverage?.[el.id]?.status;
          const verdict = corroboration?.[el.id]?.verdict;
          return (
            <button
              key={el.id}
              className={`ov-label ${band}`}
              style={{ left: `${b.xmin * 100}%`, top: `${b.ymin * 100}%` }}
              onClick={() => onPick(el.id)}
              title="Jump to this finding"
            >
              {el.label}
              {verdict === "CONFLICTED" && <span className="ov-flag">ID?</span>}
              {cov && <span className={`ov-cov ${cov}`}>{COV_LABEL[cov]}</span>}
            </button>
          );
        })}
      </div>
      <div className="player-status">
        {tc(now, fps)} · {visible.length} boxed
        {unlocated.length > 0 && (
          <span className="ov-unlocated">
            {" "}
            · {unlocated.length} on screen without a known position (
            {unlocated.map((e) => e.label).join(", ")})
          </span>
        )}
      </div>
    </div>
  );
});

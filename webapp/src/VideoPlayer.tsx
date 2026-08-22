import { forwardRef, useEffect, useRef, useState } from "react";
import type { Corroboration, Coverage, Element, Risk } from "./types";
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

  // A box is measured at ONE moment (`at_s`), so it is only true near that
  // moment. Drawing it across every appearance put the Pizza Hut box on a wall
  // three shots later — a confidently wrong rectangle, which is worse than no
  // rectangle at all. Outside the window the finding still shows in the
  // timeline and the card; only the overlay is withheld.
  const BOX_WINDOW_S = 2.0;
  const visible = elements.filter((el) => {
    if (!el.bbox) return false;
    if (el.at_s !== null && el.at_s !== undefined) {
      return Math.abs(now - el.at_s) <= BOX_WINDOW_S;
    }
    // No timestamp reported: fall back to the old behaviour rather than
    // hiding the box entirely, since older states have no at_s.
    return el.time_ranges.some((r) => now >= r.start_s && now <= r.end_s);
  });

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
          {visible.map((el) => {
            const b = el.bbox!;
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
        {visible.map((el) => {
          const b = el.bbox!;
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
        {tc(now, fps)} · {visible.length} clearable element
        {visible.length === 1 ? "" : "s"} on screen
      </div>
    </div>
  );
});

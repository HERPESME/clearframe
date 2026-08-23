import { forwardRef, useEffect, useRef, useState } from "react";
import type { BBox, Corroboration, Coverage, Element, Risk } from "./types";
import { tc } from "./timecode";

interface Props {
  pid: string;
  /**
   * Changes whenever the stored footage changes.
   *
   * Every upload lands at the same production id, so this src is otherwise
   * byte-identical between two different films and the browser replays the one
   * it already has — the previous clip's frames under the new clip's boxes.
   */
  mediaVersion: string;
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
  { pid, mediaVersion, elements, risk, corroboration, coverage, fps, activeId, onPick },
  ref,
) {
  const [now, setNow] = useState(0);
  const [paused, setPaused] = useState(true);
  // Boxes measured on the paused frame itself, keyed by element id, cached by
  // whole second. The scan's boxes come from the video pass, where Gemini
  // samples at ~1fps and returns one rectangle per time range — a union of
  // where the subject travelled rather than where it is in this frame.
  // Per second: the boxes found, and whether the frame was actually grounded.
  // The two are different answers — "grounded, absent" is a conclusion and
  // "never grounded" is a gap — and conflating them threw away the only
  // judgement worth having.
  const [ground, setGround] = useState<
    Record<string, { boxes: Record<string, BBox>; grounded: boolean }>
  >({});
  const [locating, setLocating] = useState(false);
  const [ok, setOk] = useState(true);
  const localRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    setOk(true);
    setGround({});
  }, [pid, mediaVersion]);

  // Ground only while paused. During playback a refined box would be stale
  // before it arrived, and every frame would cost a call.
  useEffect(() => {
    if (!paused) return;
    const second = String(Math.floor(now));
    if (ground[second]) return;
    let cancelled = false;
    setLocating(true);
    fetch(`/api/productions/${pid}/ground?at_s=${now.toFixed(2)}`)
      .then((r) => (r.ok ? r.json() : { boxes: {}, grounded: false }))
      .then((body) => {
        if (cancelled) return;
        setGround((g) => ({
          ...g,
          [second]: { boxes: body.boxes ?? {}, grounded: body.grounded === true },
        }));
      })
      .catch(() => {
        // Nobody looked at this frame, so the scan's box is still the best
        // thing we have — which is the behaviour that existed before this.
        if (!cancelled) {
          setGround((g) => ({ ...g, [second]: { boxes: {}, grounded: false } }));
        }
      })
      .finally(() => {
        if (!cancelled) setLocating(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pid, paused, now, ground]);

  if (!ok) return null;

  const onFrame = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    setNow(e.currentTarget.currentTime);
    setPaused(e.currentTarget.paused);
  };

  // Mirrors clearframe/overlay.py::box_at exactly — one rule, two runtimes.
  // The box belongs to the APPEARANCE, so pausing at 1s gives the opening
  // shot's rectangle and pausing at 27s gives the third's. Two fallbacks keep
  // older states drawing rather than silently losing every box on upgrade.
  const BOX_WINDOW_S = 2.0;
  const boxAt = (el: Element): BBox | null => {
    // Timecodes the scan cannot have measured place a box nowhere real.
    if (el.timing_reliable === false) return null;
    // A box measured on THIS frame beats one inferred from a time range — and
    // once a frame HAS been grounded, its answer is the whole answer. An
    // element the grounding pass did not find is not in this frame, and
    // falling back to the scan's rectangle would put the video pass's guess
    // back on screen precisely where it was checked and rejected. A live pause
    // drew "Ray-Ban Aviator Sunglasses" across a bare forehead that way.
    const frame = ground[String(Math.floor(now))];
    if (frame?.grounded) return frame.boxes[el.id] ?? null;
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

  // Boxes are drawn only while paused, and that is an honesty decision rather
  // than a tidiness one. Gemini samples video at 1 frame per second and
  // returns ONE rectangle per time range, so a box covering a moving subject
  // is a union of where it was across that range — wider than its position in
  // any single frame. Tracking that box across playback would imply a
  // precision it does not have. Held still, next to the frame it approximates,
  // it is honest about being an approximation.
  const showBoxes = paused;
  const visible = elements
    .map((el) => ({ el, box: boxAt(el) }))
    .filter((v): v is { el: Element; box: BBox } => v.box !== null)
    .filter(() => showBoxes);

  // On screen but we do not know where. Worth saying — silence would read as
  // "nothing here", and inventing a rectangle would be worse than both.
  const unlocated = elements.filter(
    (el) =>
      el.timing_reliable !== false &&
      boxAt(el) === null &&
      el.time_ranges.some((r) => now >= r.start_s && now <= r.end_s),
  );

  // Detected, but with timecodes it cannot have measured — so it is on screen
  // at no moment anyone can pause on. Listed for the whole clip rather than at
  // a timestamp, because there is no timestamp to trust.
  const untimed = elements.filter((el) => el.timing_reliable === false);

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
          src={`/api/productions/${pid}/media?v=${encodeURIComponent(mediaVersion)}`}
          controls
          preload="metadata"
          onTimeUpdate={onFrame}
          onSeeked={onFrame}
          onPause={onFrame}
          onPlay={onFrame}
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
        {tc(now, fps)} ·{" "}
        {showBoxes ? (
          <>{visible.length} boxed</>
        ) : (
          <span className="ov-unlocated">pause to place boxes</span>
        )}
        {paused && locating && (
          <span className="ov-unlocated"> · locating on this frame…</span>
        )}
        {unlocated.length > 0 && (
          <span className="ov-unlocated">
            {" "}
            · {unlocated.length} on screen without a known position (
            {unlocated.map((e) => e.label).join(", ")})
          </span>
        )}
        {untimed.length > 0 && (
          <span
            className="ov-untimed"
            title={untimed.map((e) => e.timing_note).join("\n\n")}
          >
            {" "}
            · {untimed.length} detected but not placeable in time (
            {untimed.map((e) => e.label).join(", ")}) — the scan returned
            timecodes it cannot have measured, so no box is drawn
          </span>
        )}
      </div>
    </div>
  );
});

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
  // Seconds whose grounding call is in flight. A frame being measured RIGHT
  // NOW is a fourth answer, distinct from the three below, and the one the
  // player used to get wrong: it looked identical to "nobody looked at this
  // frame", so it took the fallback and drew the scan's rectangle — the exact
  // guess grounding exists to replace — for the two-to-five seconds the call
  // takes. Long enough to pause, look, and screenshot a wrong box.
  const [pending, setPending] = useState<Record<string, true>>({});
  const [ok, setOk] = useState(true);
  const localRef = useRef<HTMLVideoElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  // Where the picture actually is inside the video element, in CSS pixels.
  //
  // The overlay used to be `inset: 0` on the frame, which is only correct
  // while the video element is exactly the size of the picture — true for
  // `width:100%; height:auto` in the page, and false the moment anything
  // letterboxes it. Full screen does exactly that: the element becomes the
  // whole display and the picture sits centred inside it with bars, so every
  // box was drawn against the screen instead of against the frame. Measuring
  // the rect makes the overlay correct in any container shape.
  const [rect, setRect] = useState({ left: 0, top: 0, width: 0, height: 0 });

  useEffect(() => {
    const video = localRef.current;
    if (!video) return;
    const measure = () => {
      const cw = video.clientWidth;
      const ch = video.clientHeight;
      const vw = video.videoWidth;
      const vh = video.videoHeight;
      if (!cw || !ch || !vw || !vh) return;
      // `object-fit: contain` is the default: the picture is scaled to fit and
      // centred, so the bars are split evenly.
      const scale = Math.min(cw / vw, ch / vh);
      const width = vw * scale;
      const height = vh * scale;
      setRect({
        left: video.offsetLeft + (cw - width) / 2,
        top: video.offsetTop + (ch - height) / 2,
        width,
        height,
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(video);
    video.addEventListener("loadedmetadata", measure);
    document.addEventListener("fullscreenchange", measure);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      video.removeEventListener("loadedmetadata", measure);
      document.removeEventListener("fullscreenchange", measure);
      window.removeEventListener("resize", measure);
    };
  }, [pid, mediaVersion]);

  // Full screen has to take the WRAPPER, not the video. The overlay is a
  // sibling of the <video>, so fullscreening the video alone leaves every box
  // behind on the page — which is exactly what a reviewer reported. The native
  // control can only ever target the video, so it is hidden in CSS and this
  // replaces it.
  const toggleFullscreen = () => {
    const frame = frameRef.current;
    if (!frame) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void frame.requestFullscreen?.();
  };
  // Bumped when the footage changes. A response that arrives after the clip
  // has been swapped belongs to a different film and is dropped — which is the
  // ONLY reason to drop one.
  const clip = useRef(0);

  useEffect(() => {
    clip.current += 1;
    setOk(true);
    setGround({});
    setPending({});
  }, [pid, mediaVersion]);

  // Ground only while paused. During playback a refined box would be stale
  // before it arrived, and every frame would cost a call.
  useEffect(() => {
    if (!paused) return;
    const second = String(Math.floor(now));
    if (ground[second] || pending[second]) return;
    // Deliberately NOT an effect-cleanup cancellation. `ground` is a dependency
    // and this effect writes to it, so cleanup fired every time ANY second's
    // answer arrived — cancelling the request in flight for the second the
    // reviewer was actually looking at, throwing away a Gemini call already
    // paid for, and leaving the player on the scan's box. Three pauses in
    // quick succession cascaded that way. An answer for second N is correct
    // for second N whatever the playhead does next; only a change of FOOTAGE
    // can invalidate it.
    const mine = clip.current;
    setPending((p) => ({ ...p, [second]: true }));
    fetch(`/api/productions/${pid}/ground?at_s=${now.toFixed(2)}`)
      .then((r) => (r.ok ? r.json() : { boxes: {}, grounded: false }))
      .then((body) => {
        if (mine !== clip.current) return;
        setGround((g) => ({
          ...g,
          [second]: { boxes: body.boxes ?? {}, grounded: body.grounded === true },
        }));
      })
      .catch(() => {
        // Nobody looked at this frame, so the scan's box is still the best
        // thing we have — which is the behaviour that existed before this.
        if (mine === clip.current) {
          setGround((g) => ({ ...g, [second]: { boxes: {}, grounded: false } }));
        }
      })
      .finally(() => {
        setPending((p) => {
          const { [second]: _done, ...rest } = p;
          return rest;
        });
      });
  }, [pid, paused, now, ground, pending]);

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
  // Mirrors clearframe/overlay.py::MAX_LOCATING_AREA. A rectangle leaving less
  // than a tenth of the picture outside it has stopped saying WHERE — it
  // restates that the element is in the shot, and paints over every real box
  // beneath it. The model returns exactly that for people ({0,0,1,1}) while
  // placing a wristwatch in the same frame to the pixel.
  const locates = (b: BBox | null | undefined): b is BBox =>
    !!b && (b.xmax - b.xmin) * (b.ymax - b.ymin) < 0.9;
  // Three-valued on purpose. `undefined` means no answer for this second yet;
  // `null` means grounding looked and this element is not in the frame; a box
  // means it located it. Conflating the first two is what drew "Ray-Ban
  // Aviator Sunglasses" across a bare forehead.
  const groundedBox = (el: Element): BBox | null | undefined => {
    const frame = ground[String(Math.floor(now))];
    // No answer, or an answer that failed — both fall back to the scan.
    if (!frame || !frame.grounded) return undefined;
    const g = frame.boxes[el.id];
    return locates(g) ? g : null;
  };

  // What the video pass measured: ONE rectangle per time range, so a union of
  // where the subject travelled rather than where it is now. Useful as a
  // placeholder, never as an answer — which is why it is drawn differently.
  const scanBox = (el: Element): BBox | null => {
    const appearance = el.time_ranges.find(
      (r) => now >= r.start_s && now <= r.end_s,
    );
    if (!appearance) return null;
    if (appearance.bbox) return locates(appearance.bbox) ? appearance.bbox : null;
    if (!locates(el.bbox)) return null;
    if (el.at_s !== null && el.at_s !== undefined) {
      return Math.abs(now - el.at_s) <= BOX_WINDOW_S ? el.bbox : null;
    }
    return el.bbox;
  };

  const boxAt = (el: Element): BBox | null => {
    // Timecodes the scan cannot have measured place a box nowhere real.
    if (el.timing_reliable === false) return null;
    const grounded = groundedBox(el);
    // Once a frame HAS been grounded its answer is the whole answer, including
    // "not in this frame". Falling back then would put the video pass's guess
    // back precisely where it was checked and rejected.
    if (grounded !== undefined) return grounded;
    return scanBox(el);
  };

  // The scan's box is showing because grounding has not answered yet. Drawing
  // nothing while an 8-second model call runs read as the app being broken;
  // drawing this as though it were measured read as the app being wrong. So
  // it is drawn, and drawn as an approximation.
  const isApprox = (el: Element): boolean =>
    el.timing_reliable !== false && groundedBox(el) === undefined;

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
      <div className="player-frame" ref={frameRef}>
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
          style={{
            left: rect.width ? `${rect.left}px` : 0,
            top: rect.width ? `${rect.top}px` : 0,
            width: rect.width ? `${rect.width}px` : "100%",
            height: rect.width ? `${rect.height}px` : "100%",
          }}
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
                  className={`ov-box ${band} ${active ? "active" : ""} ${
                    isApprox(el) ? "approx" : ""
                  }`}
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
              style={
                rect.width
                  ? {
                      left: `${rect.left + b.xmin * rect.width}px`,
                      top: `${rect.top + b.ymin * rect.height}px`,
                    }
                  : { left: `${b.xmin * 100}%`, top: `${b.ymin * 100}%` }
              }
              onClick={() => onPick(el.id)}
              title="Jump to this finding"
            >
              {el.label}
              {isApprox(el) && <span className="ov-approx">approx</span>}
              {verdict === "CONFLICTED" && <span className="ov-flag">ID?</span>}
              {cov && <span className={`ov-cov ${cov}`}>{COV_LABEL[cov]}</span>}
            </button>
          );
        })}
        <button
          type="button"
          className="player-fs"
          onClick={toggleFullscreen}
          title="Full screen (keeps the detection boxes)"
        >
          ⛶
        </button>
      </div>
      <div className="player-status">
        {tc(now, fps)} ·{" "}
        {showBoxes ? (
          <>
            {visible.length} boxed
            {visible.filter((v) => isApprox(v.el)).length > 0 && (
              <span className="ov-unlocated">
                {" "}
                ({visible.filter((v) => isApprox(v.el)).length} approximate until
                this frame is measured)
              </span>
            )}
          </>
        ) : (
          <span className="ov-unlocated">pause to place boxes</span>
        )}
        {paused && pending[String(Math.floor(now))] && (
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

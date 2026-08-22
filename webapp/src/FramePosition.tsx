import type { BBox } from "./types";
import { tc } from "./timecode";

/**
 * Where in the frame the element sits.
 *
 * Detection boxes are normalized 0-1, so this renders without the footage
 * itself — a coordinator can see "small, bottom-right, easy blur" versus
 * "centre of frame, half the picture" before pulling the shot.
 */
export function FramePosition({
  bbox,
  atS,
  fps,
  band,
}: {
  bbox: BBox;
  atS: number | null;
  fps: number;
  band: string;
}) {
  const W = 160;
  const H = 90;
  const x = bbox.xmin * W;
  const y = bbox.ymin * H;
  const w = Math.max((bbox.xmax - bbox.xmin) * W, 2);
  const h = Math.max((bbox.ymax - bbox.ymin) * H, 2);
  const area = (bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin);

  return (
    <div className="frame-pos">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        role="img"
        aria-label={`Element occupies ${(area * 100).toFixed(0)}% of the frame`}
      >
        <rect x={0} y={0} width={W} height={H} className="frame-bg" />
        <line x1={W / 3} y1={0} x2={W / 3} y2={H} className="frame-guide" />
        <line x1={(2 * W) / 3} y1={0} x2={(2 * W) / 3} y2={H} className="frame-guide" />
        <line x1={0} y1={H / 3} x2={W} y2={H / 3} className="frame-guide" />
        <line x1={0} y1={(2 * H) / 3} x2={W} y2={(2 * H) / 3} className="frame-guide" />
        <rect x={x} y={y} width={w} height={h} className={`frame-box ${band}`} />
      </svg>
      <div className="frame-cap">
        {atS !== null ? `${tc(atS, fps)} · ` : ""}
        {(area * 100).toFixed(0)}% of frame
      </div>
    </div>
  );
}

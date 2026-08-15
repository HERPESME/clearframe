export function tc(seconds: number, fps = 24, offsetS = 3600): string {
  const totalFrames = Math.round((seconds + offsetS) * fps);
  const fph = Math.round(fps * 3600);
  const fpm = Math.round(fps * 60);
  const fpsI = Math.round(fps);
  const hh = Math.floor(totalFrames / fph);
  const mm = Math.floor((totalFrames % fph) / fpm);
  const ss = Math.floor((totalFrames % fpm) / fpsI);
  const ff = totalFrames % fpsI;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(hh)}:${p(mm)}:${p(ss)}:${p(ff)}`;
}

"""SMPTE-style timecode helpers (non-drop-frame)."""


def seconds_to_tc(seconds: float, fps: float = 24.0, offset_s: float = 3600.0) -> str:
    total_frames = round((seconds + offset_s) * fps)
    frames_per_hour = round(fps * 3600)
    frames_per_minute = round(fps * 60)
    frames_per_second = round(fps)

    hh, rem = divmod(total_frames, frames_per_hour)
    mm, rem = divmod(rem, frames_per_minute)
    ss, ff = divmod(rem, frames_per_second)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

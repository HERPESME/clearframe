import { useRef, useState } from "react";
import { api, ApiError } from "./api";

const TERRITORIES = ["US", "GB", "DE", "FR", "JP", "IN"];
const MEDIA = ["THEATRICAL", "STREAMING", "BROADCAST", "HOME_VIDEO"];

/**
 * Upload footage to clear, and the rights ledger to clear it against.
 *
 * The ledger upload is the half most productions already have: a clearance
 * department keeps a licence register. Loading it means ClearFrame reports
 * "you're covered" instead of re-pricing rights the production already bought.
 */
export function Uploader({
  onStarted,
  onLedger,
}: {
  onStarted: (pid: string) => void;
  onLedger: (n: number) => void;
}) {
  const [title, setTitle] = useState("Untitled Production");
  const [territories, setTerritories] = useState<string[]>(["US", "DE", "FR"]);
  const [distribution, setDistribution] = useState<string[]>(["THEATRICAL", "STREAMING"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ledgerNote, setLedgerNote] = useState<string | null>(null);
  const clipRef = useRef<HTMLInputElement | null>(null);
  const ledgerRef = useRef<HTMLInputElement | null>(null);

  const toggle = (list: string[], set: (v: string[]) => void, value: string) =>
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const submitClip = async () => {
    const file = clipRef.current?.files?.[0];
    if (!file) {
      setError("Choose a video file first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.uploadFootage(file, {
        title,
        territories: territories.join(","),
        distribution: distribution.join(","),
      });
      onStarted(r.production_id);
    } catch (e) {
      setError(
        e instanceof ApiError && typeof e.detail === "string"
          ? e.detail
          : "Upload failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const submitLedger = async () => {
    const file = ledgerRef.current?.files?.[0];
    if (!file) return;
    setError(null);
    try {
      const r = await api.uploadLicences(file, true);
      setLedgerNote(`${r.stored} licences loaded from ${file.name}`);
      onLedger(r.stored);
    } catch (e) {
      setError(
        e instanceof ApiError && typeof e.detail === "string"
          ? e.detail
          : "Ledger upload failed.",
      );
    }
  };

  return (
    <div className="uploader">
      <div className="up-block">
        <div className="sec-title">1 · Footage to clear</div>
        <input
          className="up-text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Production title"
        />
        <input ref={clipRef} type="file" accept="video/mp4,video/quicktime,video/webm" />

        <div className="up-row">
          <span className="up-label">Release territories</span>
          {TERRITORIES.map((t) => (
            <button
              key={t}
              className={`up-chip ${territories.includes(t) ? "on" : ""}`}
              onClick={() => toggle(territories, setTerritories, t)}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="up-row">
          <span className="up-label">Media</span>
          {MEDIA.map((m) => (
            <button
              key={m}
              className={`up-chip ${distribution.includes(m) ? "on" : ""}`}
              onClick={() => toggle(distribution, setDistribution, m)}
            >
              {m.replace("_", " ")}
            </button>
          ))}
        </div>

        <button className="generate" onClick={submitClip} disabled={busy}>
          {busy ? "Uploading…" : "Scan this footage"}
        </button>
      </div>

      <div className="up-block">
        <div className="sec-title">2 · Rights you already hold (optional)</div>
        <p className="up-help">
          Upload your clearance register as <b>CSV</b> or <b>JSON</b> and ClearFrame
          checks every finding against it — reporting <em>covered</em>, or naming the
          exact gap in territory, term or media. Without it, every identified holder
          reads as unlicensed.
        </p>
        <code className="up-code">
          rights_holder, work, scope, territories, media, starts, expires, reference, notes
        </code>
        <input ref={ledgerRef} type="file" accept=".csv,.json" onChange={submitLedger} />
        {ledgerNote && <div className="up-ok">{ledgerNote}</div>}
      </div>

      {error && <div className="error-banner">{error}</div>}
    </div>
  );
}

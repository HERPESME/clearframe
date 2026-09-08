import { useRef, useState } from "react";
import { api, ApiError } from "./api";

// Must match data/jurisdictions.json — a territory offered here that the
// backend has no rules for silently falls back to the neutral band.
const TERRITORIES = [
  "US", "GB", "DE", "FR", "JP", "IN", "CA", "AU", "BR", "KR", "ES", "IT",
];
const MEDIA = ["THEATRICAL", "STREAMING", "BROADCAST", "HOME_VIDEO", "FESTIVAL"];

// What kind of work this is. Rogers v. Grimaldi protects expressive works and
// not advertising, so this is the single largest input to trademark risk — and
// the reason each option carries its consequence in plain words rather than
// hiding it in a tooltip.
const USE_CONTEXTS: [string, string, string][] = [
  ["EXPRESSIVE", "Film / TV / skit", "Speech protections apply"],
  ["SPONSORED", "Sponsored content", "A paid placement narrows them"],
  ["ADVERTISING", "Advertisement", "No Rogers shield — scored 1.4×"],
  ["NEWS", "News / reportage", "Reporting defences apply"],
  ["EDUCATIONAL", "Education / commentary", "Criticism defences apply"],
];

// Where it will be published. Drives what the PLATFORM does, which is not what
// a court would do — automated matching does not evaluate fair use.
const PLATFORMS: [string, string, string][] = [
  ["none", "Theatrical / festival", "No automated matching exists"],
  ["youtube", "YouTube", "Content ID claims ~99% automated"],
  ["tiktok", "TikTok", "Audio matching on upload"],
  ["instagram", "Instagram / Meta", "Rights Manager matching"],
  ["twitch", "Twitch", "Retroactive audio muting"],
];

function humanSize(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/**
 * Upload footage to clear.
 *
 * Was one column a screen and a half tall — every choice stacked under the
 * last, with the right half of the page empty. Now three cards across: the
 * footage, the nature of the work, the release. The action bar underneath
 * reads the choices back in plain words before the money is spent, because
 * these five inputs are the difference between a useful report and a generic
 * one. The fields and the API contract are unchanged.
 */
export function Uploader({ onStarted }: { onStarted: (pid: string) => void }) {
  const [title, setTitle] = useState("Untitled Production");
  const [territories, setTerritories] = useState<string[]>(["US", "DE", "FR"]);
  const [distribution, setDistribution] = useState<string[]>(["THEATRICAL", "STREAMING"]);
  const [useContext, setUseContext] = useState("EXPRESSIVE");
  const [platform, setPlatform] = useState("none");
  const [sponsors, setSponsors] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clip, setClip] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const clipRef = useRef<HTMLInputElement | null>(null);

  const toggle = (list: string[], set: (v: string[]) => void, value: string) =>
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const submitClip = async () => {
    if (!clip) {
      setError("Choose a video file first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.uploadFootage(clip, {
        title,
        territories: territories.join(","),
        distribution: distribution.join(","),
        use_context: useContext,
        sponsors,
        platform,
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

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      setClip(file);
      setError(null);
    }
  };

  const contextLabel = USE_CONTEXTS.find(([v]) => v === useContext)?.[1] ?? "";
  const platformLabel = PLATFORMS.find(([v]) => v === platform)?.[1] ?? "";

  return (
    <div className="up3">
      <section className="up3-card">
        <header className="up3-head">
          <h2>The footage</h2>
          <p>Three Gemini passes watch every frame.</p>
        </header>

        <div
          className={`dropzone tall ${dragging ? "over" : ""} ${clip ? "has-file" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => clipRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") clipRef.current?.click();
          }}
        >
          <input
            ref={clipRef}
            type="file"
            accept="video/mp4,video/quicktime,video/webm"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                setClip(f);
                setError(null);
              }
            }}
          />
          <svg className="dropzone-icon" viewBox="0 0 48 48" aria-hidden="true">
            <rect x="6" y="12" width="28" height="24" rx="3"
                  fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M34 22l8-5v14l-8-5z" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
          </svg>
          {clip ? (
            <>
              <div className="dropzone-name">{clip.name}</div>
              <div className="dropzone-hint">
                {humanSize(clip.size)} · click to choose a different file
              </div>
            </>
          ) : (
            <>
              <div className="dropzone-name">Drop your clip here</div>
              <div className="dropzone-hint">
                or click to browse · MP4, MOV or WebM, up to 512 MB
              </div>
            </>
          )}
        </div>

        <label className="up2-field">
          <span>Production title</span>
          <input
            className="up2-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Untitled Production"
          />
        </label>
      </section>

      <section className="up3-card">
        <header className="up3-head">
          <h2>The work</h2>
          <p>What it is decides which defences apply.</p>
        </header>

        <div className="up2-field">
          <span>What kind of work is this?</span>
          <p className="up2-why">
            The largest single input to trademark risk — Rogers v. Grimaldi
            protects expressive works and not advertising.
          </p>
          <div className="up2-options">
            {USE_CONTEXTS.map(([value, label, effect]) => (
              <button
                key={value}
                type="button"
                className={`up2-option ${useContext === value ? "on" : ""}`}
                onClick={() => setUseContext(value)}
              >
                <span className="up2-option-label">{label}</span>
                <span className="up2-option-effect">{effect}</span>
              </button>
            ))}
          </div>
        </div>

        <label className="up2-field">
          <span>Sponsors <em>optional</em></span>
          <p className="up2-why">
            Their marks count as authorised; a rival's mark in shot is flagged
            as a contract exposure even where the depiction is lawful.
          </p>
          <input
            className="up2-input"
            value={sponsors}
            onChange={(e) => setSponsors(e.target.value)}
            placeholder="Brands paying for this — e.g. Coca-Cola, Nike"
          />
        </label>
      </section>

      <section className="up3-card">
        <header className="up3-head">
          <h2>The release</h2>
          <p>Clearance is jurisdictional — where and how decide the bands.</p>
        </header>

        <div className="up2-field">
          <span>Where will it be released?</span>
          <p className="up2-why">
            Each jurisdiction is scored on its own law — a US fair-use argument
            does not travel to a closed-list country.
          </p>
          <div className="pill-row">
            {TERRITORIES.map((t) => (
              <button
                key={t}
                type="button"
                className={`pill ${territories.includes(t) ? "on" : ""}`}
                onClick={() => toggle(territories, setTerritories, t)}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div className="up2-field">
          <span>In what media?</span>
          <p className="up2-why">
            A licence covers a medium or it does not — the gap that kept WKRP
            off home video for decades.
          </p>
          <div className="pill-row">
            {MEDIA.map((m) => (
              <button
                key={m}
                type="button"
                className={`pill ${distribution.includes(m) ? "on" : ""}`}
                onClick={() => toggle(distribution, setDistribution, m)}
              >
                {m.replace("_", " ").toLowerCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="up2-field">
          <span>Publishing to</span>
          <p className="up2-why">
            What the platform's matching will do, which is not what a court
            would do.
          </p>
          <div className="up2-options">
            {PLATFORMS.map(([value, label, effect]) => (
              <button
                key={value}
                type="button"
                className={`up2-option ${platform === value ? "on" : ""}`}
                onClick={() => setPlatform(value)}
              >
                <span className="up2-option-label">{label}</span>
                <span className="up2-option-effect">{effect}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <footer className="up3-bar">
        <div className="up3-summary">
          {clip ? (
            <>
              <strong>{clip.name}</strong> · {contextLabel.toLowerCase()} ·
              releasing in {territories.join(", ") || "no territory yet"} ·{" "}
              {distribution.map((m) => m.replace("_", " ").toLowerCase()).join(" + ") ||
                "no media yet"}
              {platform !== "none" && <> · publishing to {platformLabel}</>}
            </>
          ) : (
            <>Drop a clip on the left to begin — everything else has a sane default.</>
          )}
          {error && <div className="up2-error">{error}</div>}
        </div>
        <button className="up3-go" onClick={submitClip} disabled={busy || !clip}>
          {busy ? "Uploading…" : "Scan this footage"}
        </button>
      </footer>
    </div>
  );
}

/**
 * The rights ledger — the half most productions already have.
 *
 * A clearance department keeps a licence register. Loading it means
 * ClearFrame reports "you're covered" instead of re-pricing rights the
 * production already bought.
 */
export function LedgerPanel({ onLedger }: { onLedger: (n: number) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [ledgerNote, setLedgerNote] = useState<string | null>(null);
  const [ledger, setLedger] = useState<File | null>(null);
  const ledgerRef = useRef<HTMLInputElement | null>(null);

  const submitLedger = async (file: File) => {
    setError(null);
    setLedger(file);
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
    <div className="ledger2">
      <section className="up3-card">
        <header className="up3-head">
          <h2>Load your clearance register</h2>
          <p>CSV or JSON — the format your rights spreadsheet already has.</p>
        </header>

        <div
          className={`dropzone tall ${ledger ? "has-file" : ""}`}
          onClick={() => ledgerRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) void submitLedger(f);
          }}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") ledgerRef.current?.click();
          }}
        >
          <input
            ref={ledgerRef}
            type="file"
            accept=".csv,.json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void submitLedger(f);
            }}
          />
          <svg className="dropzone-icon" viewBox="0 0 48 48" aria-hidden="true">
            <path d="M14 6h14l8 8v28H14z" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinejoin="round" />
            <path d="M28 6v8h8M20 24h12M20 30h12M20 36h8" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <div className="dropzone-name">
            {ledger ? ledger.name : "Drop a CSV or JSON ledger"}
          </div>
          <div className="dropzone-hint">or click to browse</div>
        </div>

        {ledgerNote && <div className="up2-ok">{ledgerNote}</div>}
        {error && <div className="up2-error">{error}</div>}

        <details className="up2-details">
          <summary>Expected columns</summary>
          <code>
            rights_holder, work, scope, territories, media, starts, expires,
            reference, notes
          </code>
        </details>
      </section>

      <section className="up3-card">
        <header className="up3-head">
          <h2>What it unlocks</h2>
          <p>Every finding is checked against what you already hold.</p>
        </header>
        <ul className="ledger-points">
          <li>
            <strong>Covered</strong> — a matching grant is on file, so the
            finding is reported licensed instead of re-priced.
          </li>
          <li>
            <strong>The exact gap named</strong> — a licence that exists but
            does not reach this use is reported with the missing territory,
            term or medium, not a vague warning.
          </li>
          <li>
            <strong>Music assembled, not assumed</strong> — a song is covered
            only when sync and master are both held, in territory, in term and
            in media. They arrive on two pieces of paper from two companies.
          </li>
        </ul>
        <p className="ledger-note">
          Without a ledger, every identified rights holder reads as unlicensed
          — which is honest, just noisier than your production really is.
        </p>
      </section>
    </div>
  );
}

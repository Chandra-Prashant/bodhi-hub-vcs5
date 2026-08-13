import React from "react";

/**
 * Project Description panel.
 *
 * Presented as a document record rather than a download button. The number a
 * project manager needs is not "can I download this" — it is "how much of it
 * still has to be written, and which sections". The download is the last step,
 * not the headline.
 */
export function DocumentPanel({ status, onDownload, onDownloadFinal, busy }) {
  if (!status) {
    return (
      <div className="empty">
        <h3>No document assembled yet</h3>
        <p>Run an assessment to build the Project Description.</p>
      </div>
    );
  }

  const drafted = status.sections_drafted.length;
  const remaining = status.total_guidance_blocks_remaining;
  // Guidance blocks are Verra's own prompts; each drafted section replaced one
  // or more of them, so this is a fair reading of how far along the document is.
  const done = drafted + status.fields_written;
  const ratio = Math.round((done / (done + remaining)) * 100);

  return (
    <div className="doc">
      <div className="doc__body">
        <h3 className="doc__title">VCS Project Description</h3>
        <p className="doc__meta">
          Built from {status.template_used} — the official Verra template,
          unmodified. {status.fields_written} fields populated,{" "}
          {drafted} sections drafted with clause citations.
        </p>

        <div className="doc__progress">
          <span style={{ width: `${ratio}%` }} />
        </div>
        <div className="doc__ratio">
          <span>{ratio}% assembled by the engine</span>
          <span>{remaining} guidance blocks for the author</span>
        </div>

        <div className="actions" style={{ marginTop: 0, borderTop: 0, paddingTop: 0 }}>
          <button className="btn" onClick={onDownload} disabled={busy}>
            {busy ? "Building…" : "Download working draft"}
          </button>
          <button className="btn btn--ghost" onClick={onDownloadFinal} disabled={busy}>
            Download submission copy
          </button>
        </div>
        <p className="field__hint" style={{ marginTop: 12 }}>
          The working draft keeps Verra's guidance text, which is what tells the
          author what is still missing. The submission copy strips it — only run
          that on a finished document.
        </p>
      </div>

      <div className="doc__todo">
        <span className="eyebrow">Sections needing author input</span>
        <ol>
          {status.sections_needing_input.slice(0, 12).map(([section, count]) => (
            <li key={section}>
              <span>{section}</span>
              <b>{count}</b>
            </li>
          ))}
        </ol>
        {status.sections_needing_input.length > 12 && (
          <p className="clause" style={{ marginTop: 10 }}>
            + {status.sections_needing_input.length - 12} more sections
          </p>
        )}
      </div>
    </div>
  );
}

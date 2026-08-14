import React, { useCallback, useRef, useState } from "react";

/**
 * Uploads and the review queue — Phases 3, 4 and 7 in the interface.
 *
 * PRD.md: "Human review dashboard — only flagged items require manual review."
 * So the queue holds *fields*, not documents. A reviewer resolves the three
 * uncertain values in a report rather than re-reading the report.
 *
 * Each item shows the extracted value beside the sentence the document
 * actually contains, which is the comparison Design.md specifies and the thing
 * that makes review fast — without it a reviewer reopens the PDF and searches.
 */

const SEVERITY_CLASS = {
  ERROR: "error",
  WARNING: "warning",
  INFO: "info",
};

const STATUS_LABEL = {
  UPLOADED: "Uploaded",
  EXTRACTED: "Extracted",
  NEEDS_REVIEW: "Needs review",
  MANUAL_ENTRY: "Manual entry",
  APPROVED: "Approved",
};

const STATUS_CLASS = {
  APPROVED: "approved",
  NEEDS_REVIEW: "warning",
  MANUAL_ENTRY: "error",
  EXTRACTED: "info",
  UPLOADED: "pending",
};

export function UploadPanel({ documents, onUpload, busy, lastResult }) {
  const [over, setOver] = useState(false);
  const input = useRef(null);

  const handle = useCallback(
    (files) => {
      const file = files?.[0];
      if (file) onUpload(file);
    },
    [onUpload]
  );

  return (
    <>
      <div
        className={`drop ${over ? "drop--over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          handle(e.dataTransfer.files);
        }}
      >
        <h3>{busy ? "Extracting…" : "Drop a project document here"}</h3>
        <p>
          PDF, Word or text, up to 25 MB. Scanned documents without a text layer
          are refused rather than extracted as empty — they need OCR first.
        </p>
        <button
          className="btn"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          Choose a file
        </button>
        <input
          ref={input}
          type="file"
          accept=".pdf,.docx,.doc,.txt,.md"
          style={{ display: "none" }}
          onChange={(e) => handle(e.target.files)}
        />
      </div>

      {lastResult && (
        <div
          className={lastResult.auto_approved ? "esg__ok" : "alert"}
          style={{ marginTop: 20 }}
        >
          {lastResult.auto_approved
            ? `${lastResult.document.filename} extracted cleanly — nothing flagged, so it was approved without review.`
            : `${lastResult.document.filename}: ${lastResult.review_items.length} field(s) need review.`}
        </div>
      )}

      {documents.length > 0 && (
        <div className="uploads">
          <span className="eyebrow">Documents</span>
          {documents.map((doc) => (
            <div className="upload-row" key={doc.id}>
              <span className="upload-row__name">{doc.filename}</span>
              <span className="upload-row__meta">
                <span className="clause">
                  {(doc.byte_size / 1024).toFixed(0)} KB
                </span>
                <span
                  className={`badge badge--${STATUS_CLASS[doc.status] ?? "pending"}`}
                >
                  {STATUS_LABEL[doc.status] ?? doc.status}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function QueueItem({ item, onResolve, busy }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(item.observed ?? "");

  const severity = SEVERITY_CLASS[item.severity] ?? "info";

  return (
    <article className={`qitem qitem--${severity}`}>
      <div className="qitem__head">
        <span className={`badge badge--${severity}`}>{item.severity}</span>
        <span className="qitem__field">{item.field_name}</span>
        {item.rule_id && <span className="clause">{item.rule_id}</span>}
        {item.source_page != null && (
          <span className="clause">page {item.source_page}</span>
        )}
      </div>

      <p className="qitem__reason">{item.reason}</p>

      <div className="qitem__compare">
        <div className="qitem__pane">
          <h5>Extracted</h5>
          <div className="qitem__value">{item.observed || "—"}</div>
        </div>
        <div className="qitem__pane">
          <h5>Document says</h5>
          <div className="qitem__quote">
            {item.source_text ? `"${item.source_text}"` : "—"}
          </div>
        </div>
      </div>

      <div className="qitem__actions">
        {editing ? (
          <>
            <input
              value={value}
              autoFocus
              onChange={(e) => setValue(e.target.value)}
              placeholder="Corrected value"
            />
            <button
              className="btn btn--approve"
              disabled={busy || !value.trim()}
              onClick={() => onResolve(item, "EDITED", value)}
            >
              Save correction
            </button>
            <button className="btn btn--reject" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              className="btn btn--approve"
              disabled={busy}
              onClick={() => onResolve(item, "APPROVED")}
            >
              Approve
            </button>
            <button className="btn btn--edit" onClick={() => setEditing(true)}>
              Edit
            </button>
            <button
              className="btn btn--reject"
              disabled={busy}
              onClick={() => onResolve(item, "REJECTED")}
            >
              Reject
            </button>
          </>
        )}
      </div>
    </article>
  );
}

export function ReviewQueue({ items, onResolve, busy }) {
  if (!items.length) {
    return (
      <div className="empty">
        <h3>Queue is clear</h3>
        <p>
          Nothing is flagged. Documents extracted with no uncertain values and
          no rule failures are approved without a reviewer.
        </p>
      </div>
    );
  }

  const blocking = items.filter((i) => i.severity === "ERROR").length;

  return (
    <>
      <div className="esg__bar">
        <span className="eyebrow">Only flagged fields appear here</span>
        <span className="esg__tally">
          <b>{items.length}</b> awaiting review ·{" "}
          <b style={{ color: blocking ? "var(--fail)" : "var(--primary)" }}>
            {blocking}
          </b>{" "}
          blocking calculation
        </span>
      </div>

      <div className="queue">
        {items.map((item) => (
          <QueueItem
            key={item.id}
            item={item}
            onResolve={onResolve}
            busy={busy}
          />
        ))}
      </div>
    </>
  );
}

import React, { useState } from "react";

/* -------------------------------------------------------------------------
   Project selector.

   Everything in the application is scoped to one project: its documents, its
   review queue, its ESG entries, its assessment. Switching here switches all
   of it, which is why the current project is named in the header rather than
   hidden in a menu — working on the wrong project is the mistake that must be
   hardest to make.
   ------------------------------------------------------------------------- */

export function ProjectBar({ projects, current, onSelect, onCreate, busy }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed) return;
    await onCreate(trimmed);
    setName("");
    setCreating(false);
  }

  return (
    <div className="projectbar">
      <div className="projectbar__list">
        {projects.map((p) => (
          <button
            key={p.id}
            className={`projectbar__item${
              current?.id === p.id ? " projectbar__item--on" : ""
            }`}
            onClick={() => onSelect(p)}
            disabled={busy}
          >
            <span className="projectbar__name">{p.name}</span>
            <span className="projectbar__count">
              {p.document_count} {p.document_count === 1 ? "doc" : "docs"}
            </span>
          </button>
        ))}
      </div>

      {creating ? (
        <div className="projectbar__new">
          <input
            className="input"
            autoFocus
            placeholder="Project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") setCreating(false);
            }}
          />
          <button className="btn btn--approve" onClick={submit} disabled={busy}>
            Create
          </button>
          <button className="btn btn--edit" onClick={() => setCreating(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button className="btn btn--edit projectbar__add"
                onClick={() => setCreating(true)}>
          + New project
        </button>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Run assessment, on every tab where a person enters or corrects data.

   Previously this lived only on Project details, so completing the ESG
   assessment meant navigating to another tab to see the effect of it. The
   control is the same everywhere — one component, so the label, the disabled
   state and the conflict message cannot drift between tabs.
   ------------------------------------------------------------------------- */

export function RunAssessment({ onRun, busy, disabled, hint, conflicts }) {
  return (
    <div className="runbar">
      <div className="runbar__left">
        <button
          className="btn btn--approve runbar__go"
          onClick={onRun}
          disabled={busy || disabled}
        >
          {busy ? "Assessing…" : "Run assessment"}
        </button>
        {hint && <span className="runbar__hint">{hint}</span>}
      </div>

      {conflicts?.length > 0 && (
        <div className="runbar__conflicts">
          <strong>Documents disagree.</strong> Choose a value before
          calculating — the system does not pick one, because a figure that
          differs between two source documents is a fact about the project,
          not noise.
          <ul>
            {conflicts.map((c) => (
              <li key={c.field}>
                <code>{c.field}</code>
                <ul>
                  {c.options.map((o, i) => (
                    <li key={i}>
                      <strong>{String(o.value)}</strong> — {o.filename}
                      {o.page ? ` p${o.page}` : ""}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Which document a value came from.

   With one upload this was obvious. With ten it is not, and a reviewer
   correcting a capacity needs to know which file to open.
   ------------------------------------------------------------------------- */

export function Source({ entries }) {
  if (!entries?.length) return null;
  return (
    <span className="source" title={entries[0].source_text}>
      {entries.map((e, i) => (
        <span key={i} className="source__doc">
          {e.filename}
          {e.page ? ` p${e.page}` : ""}
        </span>
      ))}
    </span>
  );
}

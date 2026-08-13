import React from "react";

/**
 * ESG risk assessment editor.
 *
 * The engine deliberately does not identify risks or score them — those are
 * site-specific judgements about real people and ecosystems. This screen is
 * where a person supplies that judgement; the engine supplies the matrix
 * lookup, the completeness check, and the commensurate-mitigation rule.
 *
 * The matrix comes from the server rather than a copy in this file. It is a
 * regulatory constant, and two copies would eventually disagree.
 */

const LEVEL_COLOUR = {
  "Very low": "var(--pass)",
  Low: "var(--pass)",
  Medium: "var(--warn)",
  High: "var(--fail)",
  "Very high": "var(--fail)",
};

const PILLAR_ORDER = ["Environmental", "Social", "Governance"];

export function EsgEditor({ schema, entries, onChange, review, onReview, busy }) {
  if (!schema) {
    return (
      <div className="empty">
        <h3>Loading the safeguard categories</h3>
        <p>The twelve categories and the risk matrix come from the engine.</p>
      </div>
    );
  }

  const byCode = Object.fromEntries(entries.map((e) => [e.category, e]));

  const update = (code, patch) => {
    const existing = byCode[code] ?? {
      category: code,
      risk_id: `${code}.1`,
      description: "",
      severity: 1,
      likelihood: 1,
      justification: "",
      mitigation: "",
      not_applicable: false,
      na_justification: "",
    };
    const next = { ...existing, ...patch };
    onChange([...entries.filter((e) => e.category !== code), next]);
  };

  const levelFor = (entry) =>
    entry && !entry.not_applicable
      ? schema.matrix[String(entry.severity)]?.[String(entry.likelihood)]
      : null;

  const assessed = entries.filter((e) => !e.not_applicable).length;
  const excluded = entries.filter((e) => e.not_applicable).length;
  const outstanding = schema.categories.length - entries.length;

  return (
    <>
      <div className="esg__bar">
        <span className="eyebrow">VCS Standard v5.0 · s3.18</span>
        <span className="esg__tally">
          <b>{assessed}</b> assessed · <b>{excluded}</b> not applicable ·{" "}
          <b style={{ color: outstanding ? "var(--warn)" : "var(--pass)" }}>
            {outstanding}
          </b>{" "}
          untouched
        </span>
        <button className="btn" onClick={onReview} disabled={busy}>
          {busy ? "Checking…" : "Check completeness"}
        </button>
      </div>

      {review && (
        <div className={review.blocked ? "alert" : "esg__ok"}>
          {review.blocked
            ? review.findings.find((f) => f.severity === "FAIL")?.message
            : "All twelve categories addressed. No blocking findings."}
        </div>
      )}

      {PILLAR_ORDER.map((pillar) => (
        <div key={pillar}>
          <h3 className="esg__pillar">{pillar}</h3>
          {schema.categories
            .filter((c) => c.pillar === pillar)
            .map((category) => {
              const entry = byCode[category.code];
              const level = levelFor(entry);
              return (
                <div className="esg__row" key={category.code}>
                  <div className="esg__head">
                    <span className="esg__code">{category.code}</span>
                    <h4 className="esg__title">{category.title}</h4>
                    <span className="clause">{category.clause}</span>
                    {level && (
                      <span
                        className="esg__level"
                        style={{ color: LEVEL_COLOUR[level] }}
                      >
                        {level}
                      </span>
                    )}
                    {entry?.not_applicable && (
                      <span className="esg__level" style={{ color: "var(--inert)" }}>
                        Not applicable
                      </span>
                    )}
                  </div>

                  <label className="esg__na">
                    <input
                      type="checkbox"
                      checked={entry?.not_applicable ?? false}
                      onChange={(e) =>
                        update(category.code, { not_applicable: e.target.checked })
                      }
                    />
                    Not applicable to this project
                  </label>

                  {entry?.not_applicable ? (
                    <div className="field">
                      <label>Justification for exclusion</label>
                      <input
                        value={entry.na_justification}
                        placeholder="A validator will not accept an unexplained exclusion."
                        onChange={(e) =>
                          update(category.code, { na_justification: e.target.value })
                        }
                      />
                    </div>
                  ) : (
                    <>
                      <div className="esg__scores">
                        <div className="field">
                          <label>Severity if it materialises</label>
                          <select
                            value={entry?.severity ?? 1}
                            onChange={(e) =>
                              update(category.code, {
                                severity: Number(e.target.value),
                              })
                            }
                          >
                            {Object.entries(schema.severity_labels).map(
                              ([value, label]) => (
                                <option key={value} value={value}>
                                  {label}
                                </option>
                              )
                            )}
                          </select>
                        </div>
                        <div className="field">
                          <label>Likelihood</label>
                          <select
                            value={entry?.likelihood ?? 1}
                            onChange={(e) =>
                              update(category.code, {
                                likelihood: Number(e.target.value),
                              })
                            }
                          >
                            {Object.entries(schema.likelihood_labels).map(
                              ([value, label]) => (
                                <option key={value} value={value}>
                                  {label}
                                </option>
                              )
                            )}
                          </select>
                        </div>
                      </div>

                      <div className="field">
                        <label>Risk</label>
                        <input
                          value={entry?.description ?? ""}
                          placeholder="What could go wrong, and to whom."
                          onChange={(e) =>
                            update(category.code, { description: e.target.value })
                          }
                        />
                      </div>
                      <div className="field">
                        <label>Justification for the level</label>
                        <input
                          value={entry?.justification ?? ""}
                          placeholder="Why this severity and likelihood — evidence, survey, consultation."
                          onChange={(e) =>
                            update(category.code, { justification: e.target.value })
                          }
                        />
                      </div>
                      <div className="field">
                        <label>Mitigation measures</label>
                        <input
                          value={entry?.mitigation ?? ""}
                          placeholder={
                            level === "High" || level === "Very high"
                              ? "Must be commensurate with the risk level — s3.18.1(2)"
                              : "Controls that reduce the risk."
                          }
                          onChange={(e) =>
                            update(category.code, { mitigation: e.target.value })
                          }
                        />
                      </div>
                    </>
                  )}
                </div>
              );
            })}
        </div>
      ))}
    </>
  );
}

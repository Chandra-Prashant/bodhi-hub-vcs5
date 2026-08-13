import React from "react";

/* -------------------------------------------------------------------------
   Verdict — the signature block.

   Rendered as a stamped audit mark, not a statistic. The tCO2e figure is
   deliberately not the hero: a number nobody can defend at validation is
   worth nothing, which is the argument the whole product rests on. So the
   headline is the verdict, and the tonnage sits below it as supporting data.
   ------------------------------------------------------------------------- */

const STATUS_COLOUR = {
  SATISFIED: "var(--pass)",
  NEEDS_INPUT: "var(--warn)",
  FAILED: "var(--fail)",
  NOT_APPLICABLE: "var(--inert)",
};

const STATUS_LABEL = {
  SATISFIED: "Satisfied",
  NEEDS_INPUT: "Needs input",
  FAILED: "Failed",
  NOT_APPLICABLE: "Not applicable",
};

/* One headline, used by both the full block and the condensed strip. Two
   phrasings drifted apart in an earlier pass — the block counted needs-input
   requirements while the strip counted every gap, so the same screen showed
   "11 items" and "16 outstanding". Derive both from here. */
function headlineFor(result) {
  const blockers = result.gaps.filter((g) => g.priority === "BLOCKER").length;
  const required = result.compliance_summary.NEEDS_INPUT ?? 0;

  if (result.ready_for_validation) {
    return "Every tracked requirement is evidenced.";
  }
  if (blockers > 0) {
    return `${blockers} blocking ${blockers === 1 ? "finding stands" : "findings stand"} between this project and validation.`;
  }
  return `${required} ${required === 1 ? "requirement" : "requirements"} still need author input.`;
}

export function Verdict({ result }) {
  const ready = result.ready_for_validation;
  const summary = result.compliance_summary;
  const total = Object.values(summary).reduce((a, b) => a + b, 0) || 1;

  const blockers = result.gaps.filter((g) => g.priority === "BLOCKER").length;
  const headline = headlineFor(result);

  const detail = ready
    ? "The register below carries a clause reference and an evidence source for each requirement. Export it for the validation body."
    : blockers > 0
      ? "A blocking finding means something is wrong with the project as described, not with the paperwork. Resolve these first."
      : "Nothing is contradicted — these are sections the engine cannot evidence and a person has to write.";

  return (
    <section
      className={`verdict ${ready ? "verdict--ready" : "verdict--blocked"}`}
      aria-label="Validation readiness"
    >
      <div className="verdict__body">
        <span className="verdict__stamp">
          <span className={`dot dot--${ready ? "pass" : "fail"}`} />
          {ready ? "Ready for validation" : "Not ready"}
        </span>
        <h2 className="verdict__line">{headline}</h2>
        <p className="verdict__sub">{detail}</p>
      </div>

      <div className="verdict__ticks">
        <span className="eyebrow">Requirement register</span>
        {Object.entries(summary).map(([status, count]) => (
          <div className="tick" key={status}>
            <span className="tick__label">{STATUS_LABEL[status] ?? status}</span>
            <span className="tick__value" style={{ color: STATUS_COLOUR[status] }}>
              {count}
            </span>
            <span className="tick__bar">
              <span
                className="tick__fill"
                style={{
                  width: `${(count / total) * 100}%`,
                  background: STATUS_COLOUR[status],
                }}
              />
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function VerdictStrip({ result }) {
  const ready = result.ready_for_validation;
  const s = result.compliance_summary;
  return (
    <div className={`verdict-strip ${ready ? "verdict-strip--ready" : "verdict-strip--blocked"}`}>
      <span className={`dot dot--${ready ? "pass" : "fail"}`} />
      <span className="verdict-strip__state">
        {ready ? "Ready for validation" : "Not ready"}
      </span>
      <span className="verdict-strip__text">{headlineFor(result)}</span>
      <span className="verdict-strip__counts">
        <span className="verdict-strip__count" style={{ color: "var(--pass)" }}>
          {s.SATISFIED} satisfied
        </span>
        <span className="verdict-strip__count" style={{ color: "var(--warn)" }}>
          {s.NEEDS_INPUT} needs input
        </span>
        <span className="verdict-strip__count" style={{ color: "var(--fail)" }}>
          {s.FAILED} failed
        </span>
      </span>
    </div>
  );
}

/* -------------------------------------------------------------------------
   Compliance ledger — one ruled row per VCS requirement, with its clause and
   evidence sources on a mono spine beneath. This is the artefact a
   verification body actually reads.
   ------------------------------------------------------------------------- */

export function Ledger({ requirements }) {
  return (
    <div className="ledger">
      {requirements.map((req) => (
        <div className="ledger__row" key={req.ref}>
          <span
            className="dot"
            style={{ background: STATUS_COLOUR[req.status], marginTop: 6 }}
            aria-hidden="true"
          />
          <div>
            <p className="ledger__title">{req.title}</p>
            {req.note && <p className="ledger__note">{req.note}</p>}
          </div>
          <span className={`ledger__status st--${req.status.toLowerCase()}`}>
            {STATUS_LABEL[req.status] ?? req.status}
          </span>
          <div className="ledger__spine">
            <span className="clause">{req.clause}</span>
            {req.evidence_sources.map((source) => (
              <span className="clause" key={source}>
                ← {source}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Gap stack — the auditor's ranked list. Order is meaningful: blockers first,
   then work, then review. It is produced deterministically, so two runs on the
   same project always agree.
   ------------------------------------------------------------------------- */

export function GapStack({ gaps, limit = 12 }) {
  if (!gaps.length) {
    return (
      <div className="empty">
        <h3>Nothing outstanding</h3>
        <p>Every tracked requirement is evidenced and no warnings are open.</p>
      </div>
    );
  }

  return (
    <div>
      {gaps.slice(0, limit).map((gap, index) => (
        <article className={`gap gap--${gap.priority.toLowerCase()}`} key={index}>
          <div className="gap__head">
            <span className="gap__pri">{gap.priority}</span>
            <span className="clause">{gap.clause}</span>
          </div>
          <h4 className="gap__area">{gap.area}</h4>
          <p className="gap__detail">{gap.detail}</p>
        </article>
      ))}
      {gaps.length > limit && (
        <p className="clause" style={{ marginTop: 10 }}>
          + {gaps.length - limit} more in the full register
        </p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
   Derivation chain — the product thesis, made tangible. Each figure shows the
   arithmetic that produced it and the clause that governs it, so a verifier
   can reproduce it by hand without opening the code.
   ------------------------------------------------------------------------- */

// International grouping, deliberately not en-IN: these figures are carried
// into the Project Description and read by Verra and the validation body,
// where 348,358 is expected rather than 3,48,358.
const t = (value, digits = 0) =>
  value == null
    ? "—"
    : value.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

export function Derivation({ result, generationMwh }) {
  const q = result.quantification;
  const c = result.classification;

  if (q.ef_grid_cm == null) {
    return (
      <div className="empty">
        <h3>No grid data supplied</h3>
        <p>
          Add the power units of the project electricity system to compute the
          operating and build margins.
        </p>
      </div>
    );
  }

  const rows = [
    {
      label: "Operating margin",
      value: `${q.ef_grid_om.toFixed(4)} tCO₂/MWh`,
      work: `Generation-weighted across dispatchable units, low-cost/must-run excluded (${q.om_method?.toLowerCase()} method)`,
      clause: "VT0011 v1.0 · Step 3",
    },
    {
      label: "Build margin",
      value: `${q.ef_grid_bm.toFixed(4)} tCO₂/MWh`,
      work: `Sample: ${q.bm_sample_unit_ids.join(", ") || "—"}`,
      clause: "VT0011 v1.0 · para 75",
    },
    {
      label: "Combined margin",
      value: `${q.ef_grid_cm.toFixed(4)} tCO₂/MWh`,
      work: `${q.ef_grid_om.toFixed(4)} × ${c.cm_weight_om} + ${q.ef_grid_bm.toFixed(4)} × ${c.cm_weight_bm}`,
      clause: "VT0011 v1.0 · para 86",
    },
    {
      label: "Baseline emissions",
      value: `${t(q.baseline_tco2e, 1)} tCO₂e`,
      work: `EG_PJ,y × EF_grid,CM,y  =  ${t(generationMwh)} MWh × ${q.ef_grid_cm.toFixed(4)}`,
      clause: "ACM0002 v22.0",
    },
    {
      label: "Project emissions",
      value: `${t(q.project_tco2e, 1)} tCO₂e`,
      work: "PE_FF + PE_GP + PE_HP + PE_BESS + PE_PV + PE_FEC",
      clause: "VMR0017 v1.0 · eq. 1",
    },
    {
      label: "Leakage — embodied",
      value: `${t(q.leakage_tco2e, 1)} tCO₂e`,
      work: `EG_facility,y × EF_embodied × 10⁻³  ·  factor mandated by technology`,
      clause: "VMR0017 v1.0 · eq. 19",
    },
  ];

  return (
    <div className="derive">
      {rows.map((row) => (
        <div className="derive__row" key={row.label}>
          <span className="derive__label">{row.label}</span>
          <span className="derive__value">{row.value}</span>
          <span className="derive__work">
            {row.work} <span className="clause">· {row.clause}</span>
          </span>
        </div>
      ))}
      <div className="derive__row derive__row--total">
        <span className="derive__label">Emission reductions, annual</span>
        <span className="derive__value">{t(q.reductions_tco2e, 1)} tCO₂e</span>
        <span className="derive__work">
          ER_y = BE_y − PE_y − LE_y ·{" "}
          <span className="clause">VMR0017 v1.0 · eq. 17</span> · over{" "}
          {c.crediting_period_years} years:{" "}
          {t(q.crediting_period_total_tco2e)} tCO₂e
        </span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
   Additionality — the commercially decisive panel. The CCP distinction is
   surfaced because it changes what the credits are worth, and it is the thing
   most easily missed.
   ------------------------------------------------------------------------- */

export function Additionality({ additionality }) {
  if (!additionality) {
    return (
      <div className="empty">
        <h3>No financial model supplied</h3>
        <p>Add capital cost, tariff and benchmark IRR to test additionality.</p>
      </div>
    );
  }

  const pct = (v) => (v == null ? "undefined" : `${(v * 100).toFixed(2)}%`);
  const additional = additionality.verdict === "ADDITIONAL";

  const rows = [
    {
      label: "Project IRR without credit revenue",
      value: pct(additionality.irr_without_credits),
      work: "Must fall below the benchmark for condition (a) to be met",
      clause: "VT0008 v1.0 · s5.4.2(2)(a)",
    },
    {
      label: "Project IRR with credit revenue",
      value: pct(additionality.irr_with_credits),
      work: `Credit revenue applied over the crediting period only`,
      clause: "VCS Standard v5.0 · Table 8",
    },
    {
      label: "Benchmark",
      value: pct(additionality.benchmark_irr),
      work: "Must be justified from a documented source, not assumed",
      clause: "VT0008 v1.0 · App. 2 sA2.3",
    },
    {
      label: "Common practice factor",
      value: `${(additionality.f_factor * 100).toFixed(1)}%`,
      work: additionality.is_common_practice
        ? "Common practice — the project is not additional"
        : "Below the threshold, or too few similar projects (footnote 17)",
      clause: "VT0008 v1.0 · s5.5.2",
    },
    {
      label: "Sensitivity",
      value: additionality.sensitivity_robust ? "Robust" : "Fails",
      work: "Condition (a) tested across ±10% on capex, opex, tariff and generation",
      clause: "VT0008 v1.0 · s5.4.2(3)",
    },
    {
      label: "CCP label eligibility",
      value: additionality.meets_ccp_conditions ? "Conditions met" : "Not met",
      work: additionality.meets_ccp_conditions
        ? "Credit revenue lifts the indicator to the benchmark"
        : "Additional, but may not qualify for Core Carbon Principles labels — this affects the price the credits fetch",
      clause: "VT0008 v1.0 · s5.4.2 note",
    },
  ];

  return (
    <div className="derive">
      <div className="derive__row derive__row--total">
        <span className="derive__label">Verdict</span>
        <span className="derive__value">
          {additional ? "Additional" : additionality.verdict.replace(/_/g, " ")}
        </span>
        <span className="derive__work">
          Regulatory surplus → investment analysis → common practice ·{" "}
          <span className="clause">
            barrier analysis unavailable under VMR0017 v1.0 s5.3.2
          </span>
        </span>
      </div>
      {rows.map((row) => (
        <div className="derive__row" key={row.label}>
          <span className="derive__label">{row.label}</span>
          <span className="derive__value">{row.value}</span>
          <span className="derive__work">
            {row.work} <span className="clause">· {row.clause}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

import React, { useState } from "react";

export function Login({ onSubmit, error, busy }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <div className="login">
      <div className="login__pitch">
        <span className="eyebrow" style={{ color: "#6c7787" }}>
          Bodhi Hub · VCS Version 5
        </span>
        <h1>Every figure carries the clause it came from.</h1>
        <p>
          Baseline, additionality and monitoring for grid-connected solar and
          wind under VMR0017. Calculations are deterministic and cited, so a
          validation body can reproduce any number by hand.
        </p>
        <div className="login__cites">
          {[
            "VCS Standard v5.0",
            "VMR0017 v1.0",
            "VT0008",
            "VT0011",
            "ACM0002 v22.0",
          ].map((c) => (
            <span className="login__cite" key={c}>
              {c}
            </span>
          ))}
        </div>
      </div>

      <div className="login__panel">
        <h2>Sign in</h2>
        {error && <div className="alert">{error}</div>}
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSubmit(email, password)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSubmit(email, password)}
          />
        </div>
        <button
          className="btn"
          disabled={busy || !email || !password}
          onClick={() => onSubmit(email, password)}
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="field__hint">
          Accounts are created by an administrator. There is no self-registration.
        </p>
      </div>
    </div>
  );
}

const TECHNOLOGIES = [
  ["SOLAR_PV_TERRESTRIAL", "Solar PV — terrestrial"],
  ["SOLAR_PV_FLOATING", "Solar PV — floating"],
  ["WIND_ONSHORE", "Wind — onshore"],
  ["WIND_OFFSHORE", "Wind — offshore"],
  ["GEOTHERMAL", "Geothermal"],
  ["HYDRO", "Hydroelectric"],
  ["WAVE", "Wave"],
  ["TIDAL", "Tidal"],
];

export function ProjectForm({
  project, onChange, onRun, onExport, busy, hasResult,
  runnable = true, onLoadSample, onClear,
}) {
  const setFinance = (key) => (event) => {
    onChange({
      ...project,
      financials: { ...(project.financials ?? {}), [key]: Number(event.target.value) },
    });
  };

  const set = (key) => (event) => {
    const raw = event.target.value;
    const numeric = ["installed_capacity_mw", "expected_annual_generation_mwh"];
    onChange({ ...project, [key]: numeric.includes(key) ? Number(raw) : raw });
  };

  return (
    <div className="form">
      <div className="form__grid">
        <div className="field">
          <label htmlFor="name">Project name</label>
          <input id="name" value={project.name} onChange={set("name")} />
        </div>
        <div className="field">
          <label htmlFor="proponent">Project proponent</label>
          <input id="proponent" value={project.proponent} onChange={set("proponent")} />
        </div>
        <div className="field">
          <label htmlFor="country">Host country</label>
          <input
            id="country"
            maxLength={2}
            value={project.country_iso2}
            onChange={set("country_iso2")}
          />
          <span className="field__hint">
            Two-letter code. Eligibility depends on it.
          </span>
        </div>
        <div className="field">
          <label htmlFor="technology">Technology</label>
          <select
            id="technology"
            value={project.technology}
            onChange={set("technology")}
          >
            {TECHNOLOGIES.map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="capacity">Installed capacity, MW</label>
          <input
            id="capacity"
            type="number"
            value={project.installed_capacity_mw}
            onChange={set("installed_capacity_mw")}
          />
        </div>
        <div className="field">
          <label htmlFor="generation">Expected generation, MWh/yr</label>
          <input
            id="generation"
            type="number"
            value={project.expected_annual_generation_mwh}
            onChange={set("expected_annual_generation_mwh")}
          />
          <span className="field__hint">
            Implied capacity factor is checked for unit errors.
          </span>
        </div>
        <div className="field">
          <label htmlFor="start">Crediting period start</label>
          <input
            id="start"
            type="date"
            value={project.initial_crediting_period_start}
            onChange={set("initial_crediting_period_start")}
          />
          <span className="field__hint">
            Selects the 5.0A or 5.0B template.
          </span>
        </div>
      </div>

      <fieldset
        style={{ border: 0, padding: 0, margin: "22px 0 0" }}
      >
        <legend className="eyebrow" style={{ padding: 0, marginBottom: 12 }}>
          Financial model · drives the additionality test
        </legend>
        <div className="form__grid">
          <div className="field">
            <label htmlFor="capex">Capital cost</label>
            <input
              id="capex"
              type="number"
              value={project.financials?.capex ?? ""}
              onChange={setFinance("capex")}
            />
            <span className="field__hint">Same currency throughout.</span>
          </div>
          <div className="field">
            <label htmlFor="opex">Annual operating cost</label>
            <input
              id="opex"
              type="number"
              value={project.financials?.annual_opex ?? ""}
              onChange={setFinance("annual_opex")}
            />
          </div>
          <div className="field">
            <label htmlFor="tariff">Tariff per MWh</label>
            <input
              id="tariff"
              type="number"
              step="0.0001"
              value={project.financials?.tariff_per_mwh ?? ""}
              onChange={setFinance("tariff_per_mwh")}
            />
          </div>
          <div className="field">
            <label htmlFor="benchmark">Benchmark IRR</label>
            <input
              id="benchmark"
              type="number"
              step="0.01"
              value={project.financials?.benchmark_irr ?? ""}
              onChange={setFinance("benchmark_irr")}
            />
            <span className="field__hint">
              0.14 is 14%. Must be justified from a documented source.
            </span>
          </div>
          <div className="field">
            <label htmlFor="creditprice">Credit price per tCO₂e</label>
            <input
              id="creditprice"
              type="number"
              step="0.0001"
              value={project.financials?.credit_price_per_tco2e ?? ""}
              onChange={setFinance("credit_price_per_tco2e")}
            />
          </div>
          <div className="field">
            <label htmlFor="life">Project lifetime, years</label>
            <input
              id="life"
              type="number"
              value={project.financials?.project_lifetime_years ?? ""}
              onChange={setFinance("project_lifetime_years")}
            />
            <span className="field__hint">
              Credit revenue still stops at the 15-year cap.
            </span>
          </div>
        </div>
      </fieldset>

      <div className="actions">
        <button className="btn" onClick={onRun} disabled={busy || !runnable}>
          {busy ? "Running…" : "Run assessment"}
        </button>
        <button
          className="btn btn--ghost"
          onClick={onExport}
          disabled={busy || !hasResult}
        >
          Export traceability matrix
        </button>
        {onLoadSample && (
          <button className="btn btn--ghost" onClick={onLoadSample}
                  disabled={busy}>
            Load sample project
          </button>
        )}
        {onClear && project.name && (
          <button className="btn btn--reject" onClick={onClear} disabled={busy}>
            Clear
          </button>
        )}
      </div>
      {!runnable && (
        <p className="field__hint" style={{ marginTop: 10 }}>
          Name, proponent, host country, capacity, generation and the crediting
          period start are all needed before an assessment can run.
        </p>
      )}
    </div>
  );
}

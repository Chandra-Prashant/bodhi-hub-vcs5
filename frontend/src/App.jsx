import React, { useEffect, useState } from "react";
import { api, downloadBlob, setToken } from "./api.js";
import { sampleProject } from "./sample.js";
import { Login, ProjectForm } from "./components/Forms.jsx";
import {
  Additionality,
  Derivation,
  GapStack,
  Ledger,
  Verdict,
  VerdictStrip,
} from "./components/Panels.jsx";

const VIEWS = [
  ["register", "Compliance register"],
  ["quantify", "Quantification"],
  ["additionality", "Additionality"],
  ["project", "Project details"],
];

export default function App() {
  const [user, setUser] = useState(null);
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);

  const [project, setProject] = useState(sampleProject);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [view, setView] = useState("register");
  const [regulatory, setRegulatory] = useState(null);

  function signOut() {
    setToken(null);
    setUser(null);
    setResult(null);
    setRegulatory(null);
    setView("register");
  }

  async function signIn(email, password) {
    setBusy(true);
    setAuthError("");
    try {
      const tokens = await api.login(email, password);
      setToken(tokens.access_token);
      setUser(await api.me());
    } catch (err) {
      setAuthError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    setBusy(true);
    setError("");
    try {
      setResult(await api.runAssessment(project));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function exportMatrix() {
    try {
      const blob = await api.traceabilityCsv(project);
      downloadBlob(blob, `traceability-${project.name.replace(/\s+/g, "-")}.csv`);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    if (!user) return;
    api.regulatoryStatus().then(setRegulatory).catch(() => setRegulatory(null));
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  if (!user) {
    return <Login onSubmit={signIn} error={authError} busy={busy} />;
  }

  const unverified = regulatory?.findings.filter(
    (f) => f.check === "regulatory.unverified"
  ).length;

  return (
    <div className="shell">
      <nav className="rail">
        <div className="rail__mark">
          Bodhi Hub
          <span>VCS VERSION 5</span>
        </div>

        <div className="rail__group">
          <p className="rail__label">Assessment</p>
          {VIEWS.map(([key, label], index) => (
            <button
              key={key}
              className="rail__item"
              aria-current={view === key}
              onClick={() => setView(key)}
            >
              <span className="rail__idx">{String(index + 1).padStart(2, "0")}</span>
              {label}
            </button>
          ))}
        </div>

        <div className="rail__foot">
          <p className="rail__label">Regulatory basis</p>
          <div className="rail__stat">
            <span>Methodology</span>
            <b>VMR0017 v1.0</b>
          </div>
          <div className="rail__stat">
            <span>Standard</span>
            <b>VCS v5.0</b>
          </div>
          <div className="rail__stat">
            <span>Unverified docs</span>
            <b style={{ color: unverified ? "var(--warn)" : undefined }}>
              {unverified ?? "—"}
            </b>
          </div>
          <div className="rail__stat" style={{ marginTop: 10 }}>
            <span>{user.full_name}</span>
            <b>{user.role.replace(/_/g, " ").toLowerCase()}</b>
          </div>
          <button className="rail__signout" onClick={signOut}>
            Sign out
          </button>
        </div>
      </nav>

      <main className="main">
        <header className="topbar">
          <h1>{result?.project_name ?? project.name}</h1>
          <div className="topbar__meta">
            <span className="clause">
              {project.technology.replace(/_/g, " ").toLowerCase()} ·{" "}
              {project.installed_capacity_mw} MW · {project.country_iso2}
            </span>
            {result && (
              <span className="clause">
                template {result.classification.template_version} · crediting
                period {result.classification.crediting_period_years} yr
              </span>
            )}
            {result?.quantification?.reductions_tco2e != null && (
              <span className="topbar__yield">
                <b>
                  {Math.round(
                    result.quantification.reductions_tco2e
                  ).toLocaleString("en-US")}
                </b>
                <span>tCO₂e per year</span>
              </span>
            )}
          </div>
        </header>

        <div className="canvas">
          {error && <div className="alert" style={{ marginBottom: 20 }}>{error}</div>}

          {result &&
            (view === "register" ? (
              <Verdict result={result} />
            ) : (
              <VerdictStrip result={result} />
            ))}

          {view === "register" && result && (
            <div className="grid2">
              <section className="section">
                <div className="section__head">
                  <h2>Requirement register</h2>
                  <span className="eyebrow">VCS Standard v5.0 · s3</span>
                </div>
                <Ledger requirements={result.requirements} />
              </section>

              <section className="section">
                <div className="section__head">
                  <h2>Outstanding</h2>
                  <span className="eyebrow">ranked · deterministic</span>
                </div>
                <GapStack gaps={result.gaps} />
              </section>
            </div>
          )}

          {view === "quantify" && result && (
            <section className="section">
              <div className="section__head">
                <h2>Derivation chain</h2>
                <span className="eyebrow">reproducible by hand</span>
              </div>
              <Derivation
                result={result}
                generationMwh={project.expected_annual_generation_mwh}
              />
            </section>
          )}

          {view === "additionality" && result && (
            <section className="section">
              <div className="section__head">
                <h2>Additionality</h2>
                <span className="eyebrow">VT0008 v1.0</span>
              </div>
              <Additionality additionality={result.additionality} />
            </section>
          )}

          {view === "project" && (
            <section className="section">
              <div className="section__head">
                <h2>Project details</h2>
                <span className="eyebrow">intake</span>
              </div>
              <ProjectForm
                project={project}
                onChange={setProject}
                onRun={run}
                onExport={exportMatrix}
                busy={busy}
                hasResult={Boolean(result)}
              />
            </section>
          )}

          {!result && !busy && view !== "project" && (
            <div className="empty">
              <h3>No assessment yet</h3>
              <p>Open Project details and run one.</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

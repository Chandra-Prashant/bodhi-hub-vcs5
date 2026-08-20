import React, { useEffect, useRef, useState } from "react";
import { api, downloadBlob, setSessionLostHandler, setToken } from "./api.js";
import { emptyProject, isRunnable, sampleProject } from "./sample.js";
import { DocumentPanel } from "./components/DocumentPanel.jsx";
import { EsgEditor } from "./components/EsgEditor.jsx";
import { ProjectBar, RunAssessment } from "./components/Projects.jsx";
import { ReviewQueue, UploadPanel } from "./components/ReviewPanels.jsx";
import { Login, ProjectForm } from "./components/Forms.jsx";
import {
  Additionality,
  Derivation,
  GapStack,
  Ledger,
  Verdict,
  VerdictStrip,
} from "./components/Panels.jsx";

// Design.md: sidebar sections Uploads / Review Queue / Reports / Audit Log.
const VIEWS = [
  ["uploads", "Uploads"],
  ["queue", "Review queue"],
  ["register", "Compliance register"],
  ["quantify", "Quantification"],
  ["additionality", "Additionality"],
  ["esg", "ESG risk"],
  ["document", "Project Description"],
  ["project", "Project details"],
];

export default function App() {
  const [user, setUser] = useState(null);
  const [authError, setAuthError] = useState("");
  const [busy, setBusy] = useState(false);

  const [project, setProject] = useState(emptyProject);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [view, setView] = useState("register");
  const [regulatory, setRegulatory] = useState(null);
  const [docStatus, setDocStatus] = useState(null);
  const [docBusy, setDocBusy] = useState(false);
  // "saved" | "unsaved" — shown in the header so a failed save is visible
  // rather than silent, which is how an hour of ESG work was lost.
  const [saveState, setSaveState] = useState("saved");
  const [projects, setProjects] = useState([]);
  const [currentProject, setCurrentProject] = useState(null);
  // field name -> [{filename, page, source_text}], so a value can show which
  // document it came from once a project holds more than one.
  const [provenance, setProvenance] = useState({});
  const [conflicts, setConflicts] = useState([]);
  const [esgSchema, setEsgSchema] = useState(null);
  const [esgReview, setEsgReview] = useState(null);
  const [esgBusy, setEsgBusy] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [queue, setQueue] = useState([]);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [lastUpload, setLastUpload] = useState(null);
  const [assessingId, setAssessingId] = useState(null);
  const [handoverNotes, setHandoverNotes] = useState([]);

  async function deleteDocument(doc) {
    setUploadBusy(true);
    setError("");
    try {
      await api.deleteDocument(doc.id);
      // The removed document may be the one on screen. Clearing avoids showing
      // an assessment whose source no longer exists.
      if (lastUpload?.document?.id === doc.id) setLastUpload(null);
      await refreshIngestion();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploadBusy(false);
    }
  }

  async function assessDocument(doc) {
    setAssessingId(doc.id);
    setError("");
    setHandoverNotes([]);
    try {
      const response = await api.assessDocument(doc.id);
      setResult(response.assessment);
      setHandoverNotes([
        ...(response.corrections_applied?.length
          ? [`Reviewer corrections applied to: ${response.corrections_applied.join(", ")}.`]
          : []),
        ...(response.notes ?? []),
      ]);
      // Show the values the assessment ran on. The handover already applied
      // reviewer corrections and dropped rejected values, so this is what was
      // actually used — not what the document said.
      if (response.project) {
        // Merge onto the CURRENT project, not onto an empty one. The handover
        // payload is built from the document, so it carries no ESG entries —
        // spreading it over a blank project silently discarded twelve
        // categories of judgement a person had typed, and the debounced save
        // then wrote that empty version over the stored one.
        //
        // Anything the assessment establishes wins; anything it has no opinion
        // about is kept.
        setProject((current) => ({
          ...emptyProject,
          ...current,
          ...response.project,
          financials: response.project.financials ?? current.financials ?? null,
          esg_entries: current.esg_entries ?? [],
        }));
        // Assemble the Project Description from the same payload, so tab 07
        // reflects the assessment that just ran rather than telling the user
        // to run one.
        try {
          setDocStatus(await api.documentStatus(response.project));
        } catch {
          setDocStatus(null);
        }
      }
      setView("register");
    } catch (err) {
      // A 409 means blocking review items are unresolved. That is a normal
      // state with somewhere to go, not a failure to report and abandon.
      setError(err.message);
      if (/review item/i.test(err.message)) setView("queue");
    } finally {
      setAssessingId(null);
    }
  }

  function selectProject(project) {
    setCurrentProject(project);
    // Everything on screen belongs to the project being left. Clear it before
    // loading the next, so nothing from Aligarh can appear under Kutch.
    setResult(null);
    setDocStatus(null);
    setNotes([]);
    setEsgReview(null);
    setProvenance({});
    setConflicts([]);
    setProject({ ...emptyProject, ...(project.state ?? {}) });
    refreshIngestion(project.id);
  }

  async function createProject(name) {
    setBusy(true);
    setError("");
    try {
      const created = await api.createProject(name);
      setProjects((list) => [created, ...list]);
      selectProject(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function assessProject() {
    if (!currentProject) return;
    setBusy(true);
    setError("");
    setConflicts([]);
    try {
      const response = await api.assessProject(currentProject.id);
      setResult(response.assessment);
      setProvenance(response.provenance ?? {});
      setProject((current) => ({
        ...emptyProject,
        ...current,
        ...response.project,
        esg_entries: current.esg_entries ?? [],
      }));
      try {
        setDocStatus(await api.documentStatus(response.project));
      } catch {
        setDocStatus(null);
      }
    } catch (err) {
      // A conflict is not an error to apologise for — it is the system
      // refusing to choose between two source documents. Show both.
      const detail = err.detail ?? err.body?.detail;
      if (detail?.conflicts) {
        setConflicts(detail.conflicts);
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function refreshIngestion(projectId = currentProject?.id) {
    if (!projectId) {
      setDocuments([]);
      setQueue([]);
      return;
    }
    try {
      const [docs, items] = await Promise.all([
        api.documents(projectId),
        api.reviewQueue(projectId),
      ]);
      setDocuments(docs);
      setQueue(items);
    } catch (err) {
      setError(err.message);
    }
  }

  async function uploadDocument(file) {
    setUploadBusy(true);
    setError("");
    try {
      const result = await api.uploadDocument(currentProject.id, file);
      setLastUpload(result);
      await refreshIngestion();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploadBusy(false);
    }
  }

  async function resolveItem(item, state, correctedValue) {
    setUploadBusy(true);
    setError("");
    try {
      await api.resolveReview(item.id, state, correctedValue);
      await refreshIngestion();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploadBusy(false);
    }
  }

  async function reviewEsg() {
    setEsgBusy(true);
    setError("");
    try {
      setEsgReview(await api.esgReview(project));
    } catch (err) {
      setError(err.message);
    } finally {
      setEsgBusy(false);
    }
  }

  function loadSample() {
    setProject(sampleProject);
    setResult(null);
    setDocStatus(null);
  }

  function clearProject() {
    api.clearDraft().catch(() => {});
    setProject(emptyProject);
    setResult(null);
    setDocStatus(null);
  }

  // When renewal fails the session is genuinely over; return to the sign-in
  // screen rather than leaving a dead interface showing stale data.
  setSessionLostHandler(() => {
    setUser(null);
    setResult(null);
    setDocuments([]);
    setQueue([]);
  });

  function signOut() {
    setToken(null, null);
    setUser(null);
    setProject(emptyProject);
    setResult(null);
    setRegulatory(null);
    setDocStatus(null);
    setView("register");
  }

  async function signIn(email, password) {
    setBusy(true);
    setAuthError("");
    try {
      const tokens = await api.login(email, password);
      // Keep the refresh token so a short-lived access token can be renewed
      // rather than ending the session mid-task.
      setToken(tokens.access_token, tokens.refresh_token ?? null);
      setUser(await api.me());
      // Restore whatever was being worked on. Twelve categories of ESG
      // judgement is an hour of typing; losing it to a sign-out was the
      // single worst thing this interface did.
      try {
        const saved = await api.readDraft();
        if (saved?.state) setProject({ ...emptyProject, ...saved.state });
      } catch {
        // A draft that will not load must not block sign-in.
      }
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
      // Assembled from the same inputs in the same pass, so the figures in the
      // document cannot drift from the figures on screen.
      setDocStatus(await api.documentStatus(project));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // Persist the working state a moment after typing stops. Debounced because
  // every keystroke in an ESG box would otherwise be a write, and saving is
  // not so urgent that it needs to race the user.
  const saveTimer = useRef(null);
  useEffect(() => {
    if (!user || !project?.name) return undefined;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    setSaveState("saving");
    saveTimer.current = setTimeout(() => {
      (currentProject
        ? api.saveProjectState(currentProject.id, project)
        : api.writeDraft(project))
        .then(() => setSaveState("saved"))
        .catch(() => setSaveState("unsaved"));
    }, 1200);
    return () => clearTimeout(saveTimer.current);
  }, [project, user]);

  async function downloadPdd(stripGuidance) {
    setDocBusy(true);
    setError("");
    try {
      const blob = await api.projectDescription(project, stripGuidance);
      const suffix = stripGuidance ? "submission" : "draft";
      downloadBlob(
        blob,
        `VCS_PD_${project.name.replace(/\s+/g, "_")}_${suffix}.docx`
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setDocBusy(false);
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
    // Reference data only. No assessment runs on sign-in — the app opens with
    // nothing loaded, so every figure on screen belongs to something the user
    // put there.
    api.regulatoryStatus().then(setRegulatory).catch(() => setRegulatory(null));
    api.esgSchema().then(setEsgSchema).catch(() => setEsgSchema(null));
    api.listProjects()
      .then((list) => {
        setProjects(list);
        // Open the most recent project rather than nothing: a user with one
        // project should not have to select it every time.
        if (list.length && !currentProject) selectProject(list[0]);
      })
      .catch(() => setProjects([]));
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
          <h1 className={project.name ? "" : "topbar__untitled"}>
            {result?.project_name || project.name || "No project loaded"}
          </h1>
          <div className="topbar__meta">
            {project.name && (
              <span className="clause">
                {project.technology.replace(/_/g, " ").toLowerCase()} ·{" "}
                {project.installed_capacity_mw} MW · {project.country_iso2}
              </span>
            )}
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

        <ProjectBar
          projects={projects}
          current={currentProject}
          onSelect={selectProject}
          onCreate={createProject}
          busy={busy}
        />

        <div className="canvas">
          {error && <div className="alert" style={{ marginBottom: 20 }}>{error}</div>}

          {handoverNotes.length > 0 && view === "register" && (
            <div className="esg__ok" style={{ marginBottom: 20 }}>
              {handoverNotes.map((note, i) => <div key={i}>{note}</div>)}
            </div>
          )}

          {result && view !== "uploads" && view !== "queue" &&
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

          {view === "uploads" && (
            <section className="section">
              <div className="section__head">
                <h2>Uploads</h2>
                <span className="eyebrow">extract · validate · flag</span>
              </div>
              <UploadPanel
                documents={documents}
                onUpload={uploadDocument}
                onAssess={assessDocument}
                onDelete={deleteDocument}
                busy={uploadBusy}
                assessingId={assessingId}
                lastResult={lastUpload}
              />
            </section>
          )}

          {view === "queue" && (
            <>
            <RunAssessment
              onRun={currentProject ? assessProject : run}
              busy={busy}
              disabled={!currentProject && !project.name}
              hint={"Re-runs with your corrections applied."}
              conflicts={conflicts}
            />
            
            <section className="section">
              <div className="section__head">
                <h2>Review queue</h2>
                <span className="eyebrow">
                  {queue.length} item{queue.length === 1 ? "" : "s"} pending
                </span>
              </div>
              <ReviewQueue
                items={queue}
                onResolve={resolveItem}
                busy={uploadBusy}
              />
            </section>
            </>
          )}

          {view === "esg" && (
            <>
            <RunAssessment
              onRun={currentProject ? assessProject : run}
              busy={busy}
              disabled={!currentProject && !project.name}
              hint={"Re-runs with this ESG assessment included."}
              conflicts={conflicts}
            />
            
            <section className="section">
              <div className="section__head">
                <h2>ESG risk assessment</h2>
                <span className="eyebrow">judgement supplied by the author</span>
              </div>
              <EsgEditor
                schema={esgSchema}
                entries={project.esg_entries ?? []}
                onChange={(esg_entries) =>
                  setProject({ ...project, esg_entries })
                }
                review={esgReview}
                onReview={reviewEsg}
                busy={esgBusy}
              />
            </section>
            </>
          )}

          {view === "document" && (
            <section className="section">
              <div className="section__head">
                <h2>Project Description</h2>
                <span className="eyebrow">
                  {docStatus?.template_used ?? "official Verra template"}
                </span>
              </div>
              <DocumentPanel
                status={docStatus}
                busy={docBusy}
                onDownload={() => downloadPdd(false)}
                onDownloadFinal={() => downloadPdd(true)}
              />
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
                runnable={isRunnable(project)}
                onLoadSample={loadSample}
                onClear={clearProject}
              />
            </section>
          )}

          {!result && !busy &&
            ["register", "quantify", "additionality"].includes(view) && (
              <div className="empty">
                <h3>Nothing assessed yet</h3>
                <p>
                  Upload a project document, or enter the project by hand under
                  Project details, then run an assessment.
                </p>
                <div className="actions" style={{ justifyContent: "center",
                                                  borderTop: 0, paddingTop: 12 }}>
                  <button className="btn" onClick={() => setView("uploads")}>
                    Upload a document
                  </button>
                  <button className="btn btn--ghost"
                          onClick={() => setView("project")}>
                    Enter it by hand
                  </button>
                </div>
              </div>
            )}
        </div>
      </main>
    </div>
  );
}

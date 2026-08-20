/** Exactly two primary views. No metrics, audit, gates, replan, settings, or
 *  administration screens — those are sections of RunView where they belong. */
import { useState } from "react";
import type { Api } from "./api/client";
import { RunView } from "./views/RunView";
import { HumanActionView } from "./views/HumanActionView";

type Tab = "run" | "human";

export function App({ api, runId, actorId }: { api: Api; runId: string; actorId: string }) {
  const [tab, setTab] = useState<Tab>("run");
  return (
    <main>
      <div role="tablist">
        <button role="tab" aria-selected={tab === "run"} onClick={() => setTab("run")}>
          Run
        </button>
        <button role="tab" aria-selected={tab === "human"} onClick={() => setTab("human")}>
          Human action
        </button>
      </div>
      {runId
        ? tab === "run"
          ? <RunView api={api} runId={runId} />
          : <HumanActionView api={api} runId={runId} actorId={actorId} />
        : <NoRunSelected tab={tab} />}
    </main>
  );
}

/**
 * With no run selected there is nothing to fetch.
 *
 * Mounting a view with `runId = ""` produced requests to `/v1/runs//gates` —
 * a path that names no run and cannot answer usefully. An empty system is a
 * normal state, not an error and not a run with blank fields, so it says so
 * and issues no request at all.
 */
function NoRunSelected({ tab }: { tab: Tab }) {
  return (
    <section>
      <h2>No workflow runs yet</h2>
      <p>
        {tab === "run"
          ? "Nothing has been submitted to the orchestrator. Once a run exists, open it with ?run=<id>."
          : "No run is selected, so there are no approvals or clarifications to act on."}
      </p>
    </section>
  );
}

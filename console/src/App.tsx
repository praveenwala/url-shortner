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
      {tab === "run"
        ? <RunView api={api} runId={runId} />
        : <HumanActionView api={api} runId={runId} actorId={actorId} />}
    </main>
  );
}

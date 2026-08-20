import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createApi } from "./api/client";

const params = new URLSearchParams(window.location.search);
const runId = params.get("run") ?? "";
const actorId = params.get("actor") ?? "";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App api={createApi()} runId={runId} actorId={actorId} />
  </StrictMode>,
);

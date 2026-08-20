/**
 * HumanActionView — what is waiting on a person, and the two things they can do.
 *
 * Every mutation goes to the API and is followed by a re-fetch. Nothing is
 * removed from the list optimistically: if the server refuses, the item is still
 * there, because the console never decided anything itself.
 */
import { useCallback, useEffect, useState } from "react";
import type { Api, Pending } from "../api/client";

export function HumanActionView(
  { api, runId, actorId }: { api: Api; runId: string; actorId: string },
) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rationale, setRationale] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setPending(await api.getPending(runId));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [api, runId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const decide = async (requestId: string, decision: "approved" | "rejected") => {
    setBusy(true);
    setError(null);
    try {
      await api.decideApproval(runId, requestId, { decision, rationale }, actorId);
      setRationale("");
    } catch (err) {
      // No optimistic removal — the item stays until the server says otherwise.
      setError((err as Error).message);
    } finally {
      await refresh();
      setBusy(false);
    }
  };

  const answer = async (requestId: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.answerClarification(runId, requestId, { answer: answers[requestId] ?? "" }, actorId);
      setAnswers((prev) => ({ ...prev, [requestId]: "" }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      // The run resumes server-side once the answer is persisted. The console
      // only re-reads; it never transitions a run.
      await refresh();
      setBusy(false);
    }
  };

  if (error && !pending) return <div role="alert">{error}</div>;
  if (!pending) return <p>Loading pending items…</p>;

  const nothing = pending.approvals.length === 0 && pending.clarifications.length === 0;

  return (
    <section>
      {error && <div role="alert">{error}</div>}
      <h2>Pending human action</h2>
      {nothing && <p>Nothing is waiting on a person.</p>}

      {pending.approvals.length > 0 && (
        <>
          <h3>Approvals</h3>
          {pending.approvals.map((request) => (
            <article key={request.id} style={{ border: "1px solid #999", padding: "0.75rem" }}>
              <p>
                <strong>{request.checkpoint}</strong> checkpoint — {request.action}
              </p>
              <pre>{JSON.stringify(request.detail, null, 2)}</pre>
              <p><em>requested by {request.requested_by} at {request.requested_at}</em></p>
              <label htmlFor={`rationale-${request.id}`}>Rationale (required)</label>
              <textarea
                id={`rationale-${request.id}`}
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
              />
              <div>
                <button
                  type="button"
                  disabled={busy || rationale.trim().length === 0}
                  onClick={() => decide(request.id, "approved")}
                >
                  Approve
                </button>
                <button
                  type="button"
                  disabled={busy || rationale.trim().length === 0}
                  onClick={() => decide(request.id, "rejected")}
                >
                  Reject
                </button>
              </div>
            </article>
          ))}
        </>
      )}

      {pending.clarifications.length > 0 && (
        <>
          <h3>Clarifications</h3>
          {pending.clarifications.map((request) => (
            <article key={request.id} style={{ border: "1px solid #999", padding: "0.75rem" }}>
              <p><strong>{request.question}</strong></p>
              <p><em>affects {request.affects} · asked by {request.requested_by}</em></p>
              <label htmlFor={`answer-${request.id}`}>Answer</label>
              <textarea
                id={`answer-${request.id}`}
                value={answers[request.id] ?? ""}
                onChange={(event) =>
                  setAnswers((prev) => ({ ...prev, [request.id]: event.target.value }))
                }
              />
              <button
                type="button"
                disabled={busy || (answers[request.id] ?? "").trim().length === 0}
                onClick={() => answer(request.id)}
              >
                Submit answer
              </button>
            </article>
          ))}
        </>
      )}
    </section>
  );
}

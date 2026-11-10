import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CornerDownLeft, MessageSquareText, Send, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { usePageTitle } from "../lib/usePageTitle";
import { CategoryLabel, StatusBadge } from "../components/Badges";
import { ErrorState, Spinner } from "../components/States";
import type { AssistantResponse } from "../lib/types";

interface Turn {
  id: string;
  question?: string;
  response?: AssistantResponse;
  error?: string;
}

export function AssistantPage() {
  usePageTitle("Operations assistant");
  const { user } = useAuth();
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  const examples = useQuery({ queryKey: ["assistant-examples"], queryFn: api.assistantExamples, staleTime: 600_000 });

  const ask = useMutation({
    mutationFn: (question: string) => api.assistant(question),
    onSuccess: (response, question) => {
      setTurns((previous) =>
        previous.map((turn) =>
          turn.question === question && !turn.response && !turn.error
            ? { ...turn, response }
            : turn,
        ),
      );
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: "smooth" }));
    },
    onError: (error, question) => {
      setTurns((previous) =>
        previous.map((turn) =>
          turn.question === question && !turn.response && !turn.error
            ? { ...turn, error: error instanceof Error ? error.message : "The assistant could not answer." }
            : turn,
        ),
      );
    },
  });

  const submit = (question: string) => {
    const cleaned = question.trim();
    if (cleaned.length < 5 || ask.isPending) return;
    setTurns((previous) => [...previous, { id: `turn-${Date.now()}`, question: cleaned }]);
    setDraft("");
    ask.mutate(cleaned);
  };

  const scopeDescription =
    user?.role === "admin"
      ? "City-wide records"
      : `Ward ${user?.ward ?? "—"} records only`;

  return (
    <div className="mx-auto max-w-[1200px] space-y-4">
      <div className="border-b border-line pb-4">
        <p className="eyebrow mb-1">Grounded retrieval</p>
        <h1 className="text-[21px] font-semibold tracking-[-0.015em] text-ink">Operations assistant</h1>
        <p className="mt-1 max-w-2xl text-[13px] leading-5 text-muted">
          Ask operational questions in plain language. Answers are generated only from live complaint
          records in your scope, and every claim cites the underlying case.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="card flex min-h-[540px] flex-col overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <div className="flex items-center gap-2">
              <MessageSquareText className="h-4 w-4 text-faint" aria-hidden />
              <h2 className="section-title">Conversation</h2>
            </div>
            <span className="inline-flex items-center gap-1.5 text-[10px] text-muted">
              <ShieldCheck className="h-3 w-3 text-[color:var(--positive)]" aria-hidden />
              {scopeDescription}
            </span>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {turns.length === 0 ? (
              <div className="flex h-full min-h-[300px] flex-col items-center justify-center px-4 text-center">
                <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-raised text-muted">
                  <Sparkles className="h-5 w-5" aria-hidden />
                </span>
                <p className="text-[14px] font-semibold text-ink">Start with an operational question</p>
                <p className="mt-1 max-w-md text-[12px] leading-5 text-muted">
                  The assistant understands wards, categories, periods, overdue SLAs and individual
                  case status. It will not speculate beyond the retrieved records.
                </p>
                {examples.data?.length ? (
                  <div className="mt-4 flex max-w-xl flex-wrap justify-center gap-1.5">
                    {examples.data.map((example) => (
                      <button
                        key={example}
                        type="button"
                        className="chip h-auto py-1 text-left hover:border-line-strong hover:text-ink"
                        onClick={() => submit(example)}
                      >
                        {example}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {turns.map((turn) => (
              <div key={turn.id} className="space-y-3">
                {turn.question ? (
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-lg rounded-br-sm border border-[color:var(--primary)] bg-[color:var(--primary-soft)] px-3 py-2">
                      <p className="whitespace-pre-line text-[12px] leading-5 text-ink">{turn.question}</p>
                    </div>
                  </div>
                ) : null}

                {turn.response ? (
                  <div className="flex gap-2.5">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded border border-line bg-raised text-muted">
                      <MessageSquareText className="h-3.5 w-3.5" aria-hidden />
                    </span>
                    <div className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2.5">
                      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                        <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-faint">
                          Assistant
                        </span>
                        <span className="rounded border border-line bg-raised px-1.5 py-0.5 text-[9px] uppercase tracking-[0.05em] text-muted">
                          {turn.response.intent.replace(/_/g, " ")}
                        </span>
                        <span className="rounded border border-line bg-raised px-1.5 py-0.5 text-[9px] uppercase tracking-[0.05em] text-muted">
                          {turn.response.scope}
                        </span>
                      </div>
                      <p className="whitespace-pre-line text-[12px] leading-5 text-ink">
                        {turn.response.answer}
                      </p>
                      {turn.response.clarification ? (
                        <p className="mt-2 rounded border border-[color:var(--warning-border)] bg-[color:var(--warning-soft)] px-2 py-1.5 text-[11px] leading-4 text-muted">
                          {turn.response.clarification}
                        </p>
                      ) : null}
                      {turn.response.citations.length > 0 ? (
                        <div className="mt-2.5 border-t border-line pt-2">
                          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-faint">
                            Sources
                          </p>
                          <ol className="space-y-1">
                            {turn.response.citations.map((citation, index) => (
                              <li key={citation.complaint_id}>
                                <Link
                                  to={`/queue/${citation.complaint_id}`}
                                  className="group flex items-center gap-2 rounded px-1 py-0.5 hover:bg-raised"
                                >
                                  <span className="tabular w-4 shrink-0 text-[10px] text-faint">
                                    [{index + 1}]
                                  </span>
                                  <span className="min-w-0 flex-1 truncate text-[11px] text-ink group-hover:text-primary">
                                    {citation.title}
                                  </span>
                                  <StatusBadge status={citation.status} className="h-5 px-1.5 text-[9px]" />
                                  <CategoryLabel
                                    category={citation.category}
                                    showIcon={false}
                                    className="hidden text-[10px] text-muted sm:inline-flex"
                                  />
                                </Link>
                              </li>
                            ))}
                          </ol>
                        </div>
                      ) : (
                        <p className="mt-2 border-t border-line pt-2 text-[10px] text-faint">
                          No individual records matched; the answer is an aggregate.
                        </p>
                      )}
                    </div>
                  </div>
                ) : null}

                {turn.error ? (
                  <div className="flex gap-2.5">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded border border-[color:var(--critical-border)] bg-[color:var(--critical-soft)] text-[color:var(--critical)]">
                      !
                    </span>
                    <div className="min-w-0 flex-1">
                      <ErrorState
                        error={new Error(turn.error)}
                        title="Answer unavailable"
                        onRetry={() => turn.question && ask.mutate(turn.question)}
                      />
                    </div>
                  </div>
                ) : null}

                {!turn.response && !turn.error ? (
                  <div className="flex gap-2.5" role="status" aria-label="Assistant is answering">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded border border-line bg-raised text-muted">
                      <Spinner className="h-3 w-3" />
                    </span>
                    <div className="flex-1 space-y-2 rounded-lg border border-line bg-surface px-3 py-3">
                      <span className="block h-2.5 w-3/4 animate-pulse rounded bg-raised" />
                      <span className="block h-2.5 w-5/6 animate-pulse rounded bg-raised" />
                      <span className="block h-2.5 w-1/2 animate-pulse rounded bg-raised" />
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <form
            className="border-t border-line p-3"
            onSubmit={(event) => {
              event.preventDefault();
              submit(draft);
            }}
          >
            <label htmlFor="assistant-input" className="sr-only">
              Ask the operations assistant
            </label>
            <div className="flex items-end gap-2">
              <textarea
                id="assistant-input"
                className="field-textarea min-h-[44px] flex-1 py-2"
                rows={1}
                maxLength={500}
                placeholder="e.g. Which drainage complaints are overdue in Ward 5?"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit(draft);
                  }
                }}
              />
              <button
                type="submit"
                className="btn btn-primary h-[44px] shrink-0 px-3"
                disabled={draft.trim().length < 5 || ask.isPending}
              >
                {ask.isPending ? <Spinner /> : <Send className="h-4 w-4" aria-hidden />}
                Ask
              </button>
            </div>
            <p className="mt-1.5 flex items-center gap-1 text-[10px] text-faint">
              <CornerDownLeft className="h-3 w-3" aria-hidden />
              Enter to send · Shift + Enter for a new line · answers are audit-safe and scoped to your role
            </p>
          </form>
        </div>

        <aside className="space-y-4">
          <section className="card p-4">
            <h2 className="section-title">What it can answer</h2>
            <ul className="mt-2 space-y-2 text-[11px] leading-5 text-muted">
              <li>Recurring issue clusters by ward, category and period.</li>
              <li>Status of a specific report or the caller&apos;s own open cases.</li>
              <li>Overdue SLA cases filtered by ward.</li>
              <li>Complaint counts and category mix for a period.</li>
            </ul>
          </section>

          <section className="card p-4">
            <h2 className="section-title">How answers are produced</h2>
            <ol className="mt-2 space-y-2 text-[11px] leading-5 text-muted">
              <li>
                <span className="mr-1 font-semibold text-ink">1.</span> The question is matched to a
                supported intent and slots (ward, category, period).
              </li>
              <li>
                <span className="mr-1 font-semibold text-ink">2.</span> Records are retrieved from
                MongoDB within the caller&apos;s role scope.
              </li>
              <li>
                <span className="mr-1 font-semibold text-ink">3.</span> The answer is rendered from
                those rows, with case citations.
              </li>
            </ol>
            <p className="mt-3 border-t border-line pt-2 text-[10px] leading-4 text-faint">
              The assistant does not generate free-form prose beyond retrieved data. If the intent is
              unclear it will ask a clarifying question instead of guessing.
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Bot, Loader2, UserRound } from "lucide-react";

import { askQuestion, createDomain, fetchDomains, fetchEvaluation } from "../api";
import DomainSelect from "../components/DomainSelect";
import { readRecentDomainIds, rememberDomainId } from "../storage";
import { useAuth } from "../AuthContext";
import type { Domain, EvaluationScores } from "../types";

type Message = {
  id: string;
  queryId: string;
  question: string;
  answer: string;
  route?: "local" | "api";
  language?: string;
  evaluationStatus: "pending" | "completed";
  evaluation?: EvaluationScores | null;
  evaluationError?: string;
};

const evaluationKeys = [
  ["faithfulness", "Faithfulness"],
  ["relevance", "Relevance"],
  ["completeness", "Completeness"],
  ["citation_accuracy", "Citations"],
] as const;

export default function ChatPage() {
  const { token, hasRole } = useAuth();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [recentDomainIds, setRecentDomainIds] = useState<string[]>(() =>
    readRecentDomainIds(),
  );
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoadingDomains, setIsLoadingDomains] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  const effectiveDomainId = useMemo(() => selectedDomainId, [selectedDomainId]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    const nextHeight = Math.min(textarea.scrollHeight, 220);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 220 ? "auto" : "hidden";
  }, [question]);

  useEffect(() => {
    if (!token) return;
    let ignore = false;
    setIsLoadingDomains(true);
    fetchDomains(token)
      .then((items) => {
        if (!ignore) setDomains(items);
      })
      .catch((err) => {
        if (!ignore)
          setError(err instanceof Error ? err.message : "Could not load domains");
      })
      .finally(() => {
        if (!ignore) setIsLoadingDomains(false);
      });
    return () => {
      ignore = true;
    };
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const pending = messages.filter(
      (message) => message.queryId && message.evaluationStatus === "pending",
    );
    if (!pending.length) return;

    let cancelled = false;
    const poll = async () => {
      await Promise.all(
        pending.map(async (message) => {
          try {
            const result = await fetchEvaluation(token, message.queryId);
            if (cancelled || result.status !== "completed") return;
            setMessages((current) =>
              current.map((item) =>
                item.id === message.id
                  ? {
                      ...item,
                      evaluationStatus: "completed",
                      evaluation: result.evaluation,
                      evaluationError: undefined,
                    }
                  : item,
              ),
            );
          } catch (err) {
            if (cancelled) return;
            setMessages((current) =>
              current.map((item) =>
                item.id === message.id
                  ? {
                      ...item,
                      evaluationError:
                        err instanceof Error ? err.message : "Evaluation unavailable",
                    }
                  : item,
              ),
            );
          }
        }),
      );
    };

    const interval = window.setInterval(() => {
      void poll();
    }, 3000);
    void poll();

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [messages, token]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || !token) return;

    const currentQuestion = question.trim();
    setQuestion("");
    setIsSubmitting(true);
    setError("");
    if (effectiveDomainId) {
      setRecentDomainIds(rememberDomainId(effectiveDomainId));
    }

    try {
      const result = await askQuestion(token, currentQuestion, effectiveDomainId);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          queryId: result.query_id,
          question: currentQuestion,
          answer: result.answer,
          route: result.llm_route,
          language: result.language_detected,
          evaluationStatus: result.evaluation ? "completed" : "pending",
          evaluation: result.evaluation ?? null,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Question failed");
      setQuestion(currentQuestion);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateDomain(name: string) {
    if (!token) return;
    const domain = await createDomain(token, name);
    setDomains((current) => [domain, ...current]);
    setSelectedDomainId(domain.id);
    setRecentDomainIds(rememberDomainId(domain.id));
  }

  // Only admins can create domains from the chat page
  const canCreateDomain = hasRole("admin");

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <section className="grid gap-2">
        <h1 className="text-3xl font-semibold tracking-normal">Chat</h1>
        <p className="max-w-2xl text-sm leading-6 text-zinc-500 dark:text-zinc-400">
          Ask a question against a selected domain. The existing backend router
          decides whether the request goes to the local or API LLM path.
        </p>
      </section>

      <section className="surface rounded-lg p-4">
        <DomainSelect
          domains={domains}
          recentDomainIds={recentDomainIds}
          selectedDomainId={selectedDomainId}
          loading={isLoadingDomains}
          onSelectDomain={setSelectedDomainId}
          onCreateDomain={canCreateDomain ? handleCreateDomain : undefined}
        />
      </section>

      <section className="surface grid min-h-[520px] rounded-lg">
        <div className="max-h-[58vh] overflow-y-auto p-4">
          {messages.length === 0 ? (
            <div className="grid h-80 place-items-center text-center">
              <div>
                <div className="mx-auto grid h-12 w-12 place-items-center rounded-lg border border-zinc-200 dark:border-zinc-800">
                  <Bot size={22} />
                </div>
                <p className="mt-4 font-semibold">No messages yet</p>
                <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
                  Start with a question about the selected domain.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {messages.map((message) => (
                <article key={message.id} className="space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-100 dark:bg-zinc-900">
                      <UserRound size={17} />
                    </div>
                    <p className="rounded-lg border border-zinc-200 px-4 py-3 text-sm dark:border-zinc-800">
                      {message.question}
                    </p>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
                      <Bot size={17} />
                    </div>
                    <div className="rounded-lg bg-zinc-50 px-4 py-3 text-sm leading-6 dark:bg-zinc-900">
                      <p>{message.answer}</p>
                      <p className="mt-3 text-xs uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                        {message.route} route · {message.language}
                      </p>
                      <EvaluationBadge message={message} />
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        <form
          className="border-t border-zinc-200 p-4 dark:border-zinc-800"
          onSubmit={handleSubmit}
        >
          {error ? (
            <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              {error}
            </p>
          ) : null}
          <div className="flex items-end gap-3 rounded-2xl border border-zinc-200 bg-white px-3 py-2 transition focus-within:border-zinc-950 focus-within:ring-2 focus-within:ring-zinc-950/10 dark:border-zinc-800 dark:bg-zinc-950 dark:focus-within:border-white dark:focus-within:ring-white/10">
            <textarea
              ref={textareaRef}
              className="chat-composer-input min-h-11 flex-1 resize-none border-0 bg-transparent px-1 py-3 text-sm text-zinc-950 outline-none placeholder:text-zinc-400 dark:text-white"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask a question"
              rows={1}
            />
            <button
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-zinc-950 text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200"
              disabled={isSubmitting}
              type="submit"
              title="Send message"
            >
              {isSubmitting ? (
                <Loader2 className="animate-spin" size={17} />
              ) : (
                <ArrowUp size={17} />
              )}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}


function EvaluationBadge({ message }: { message: Message }) {
  if (message.evaluationStatus === "pending") {
    return (
      <div className="mt-3 inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        <Loader2 className="animate-spin" size={14} />
        Judge pending
      </div>
    );
  }

  if (!message.evaluation) {
    return null;
  }

  const average = averageScore(message.evaluation);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span
        className={`inline-flex items-center rounded-lg px-2.5 py-1.5 text-xs font-semibold ${
          message.evaluation.flagged
            ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100"
            : "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100"
        }`}
        title={message.evaluation.flagged ? "Flagged for moderation" : "Judge evaluation passed"}
      >
        Judge {formatScore(average)}
      </span>
      {evaluationKeys.map(([key, label]) => (
        <span
          key={key}
          className="rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs text-zinc-600 dark:border-zinc-800 dark:text-zinc-300"
        >
          {label} {formatScore(message.evaluation?.[key])}
        </span>
      ))}
      {message.evaluationError ? (
        <span className="text-xs text-red-600 dark:text-red-400">
          {message.evaluationError}
        </span>
      ) : null}
    </div>
  );
}


function averageScore(evaluation: EvaluationScores): number | null {
  const values = evaluationKeys
    .map(([key]) => evaluation[key])
    .filter((score): score is number => typeof score === "number");
  if (!values.length) return null;
  return values.reduce((sum, score) => sum + score, 0) / values.length;
}


function formatScore(score: number | null | undefined): string {
  if (typeof score !== "number") return "--";
  return `${Math.round(score * 100)}%`;
}

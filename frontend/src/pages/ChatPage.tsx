import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Bot, Loader2, UserRound } from "lucide-react";

import { askQuestion, createDomain, fetchDomains, fetchEvaluation } from "../api";
import DomainSelect from "../components/DomainSelect";
import { readRecentDomainIds, rememberDomainId } from "../storage";
import { useAuth } from "../AuthContext";
import type { Domain, EvaluationScores } from "../types";

type Message = {
  id: string;
  queryId?: string;
  question: string;
  answer?: string;
  route?: "local" | "api";
  language?: string;
  answerStatus: "thinking" | "completed" | "error";
  evaluationStatus: "idle" | "pending" | "completed";
  evaluation?: EvaluationScores | null;
  evaluationError?: string;
  startedAt: number;
  completedAt?: number;
};

const evaluationKeys = [
  ["faithfulness", "Faithfulness"],
  ["relevance", "Relevance"],
  ["completeness", "Completeness"],
  ["citation_accuracy", "Citations"],
] as const;

const answerPhases = [
  "Checking domain access",
  "Searching embedded chunks",
  "Extracting relevant context",
  "Generating answer",
  "Preparing judge evaluation",
];

export default function ChatPage() {
  const { token, hasRole } = useAuth();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [recentDomainIds, setRecentDomainIds] = useState<string[]>(() =>
    readRecentDomainIds(),
  );
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoadingDomains, setIsLoadingDomains] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState("");

  const effectiveDomainId = useMemo(() => selectedDomainId, [selectedDomainId]);
  const hasThinkingMessage = messages.some((message) => message.answerStatus === "thinking");

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    const nextHeight = Math.min(textarea.scrollHeight, 220);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 220 ? "auto" : "hidden";
  }, [question]);

  useEffect(() => {
    if (!hasThinkingMessage) return;
    const interval = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(interval);
  }, [hasThinkingMessage]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, now]);

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
      (message) =>
        message.queryId &&
        message.answerStatus === "completed" &&
        message.evaluationStatus === "pending",
    );
    if (!pending.length) return;

    let cancelled = false;
    const poll = async () => {
      await Promise.all(
        pending.map(async (message) => {
          if (!message.queryId) return;
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
    if (!question.trim() || !token || isSubmitting) return;

    const currentQuestion = question.trim();
    const messageId = crypto.randomUUID();
    const startedAt = Date.now();
    setQuestion("");
    setNow(startedAt);
    setIsSubmitting(true);
    setError("");
    setMessages((current) => [
      ...current,
      {
        id: messageId,
        question: currentQuestion,
        answerStatus: "thinking",
        evaluationStatus: "idle",
        startedAt,
      },
    ]);

    if (effectiveDomainId) {
      setRecentDomainIds(rememberDomainId(effectiveDomainId));
    }

    try {
      const result = await askQuestion(token, currentQuestion, effectiveDomainId);
      const completedAt = Date.now();
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? {
                ...message,
                queryId: result.query_id,
                answer: result.answer,
                route: result.llm_route,
                language: result.language_detected,
                answerStatus: "completed",
                evaluationStatus: result.evaluation ? "completed" : "pending",
                evaluation: result.evaluation ?? null,
                completedAt,
              }
            : message,
        ),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Question failed";
      setError(message);
      setQuestion(currentQuestion);
      setMessages((current) =>
        current.map((item) =>
          item.id === messageId
            ? {
                ...item,
                answer: message,
                answerStatus: "error",
                evaluationStatus: "idle",
                completedAt: Date.now(),
              }
            : item,
        ),
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function handleCreateDomain(name: string) {
    if (!token) return;
    const domain = await createDomain(token, name);
    setDomains((current) => [domain, ...current]);
    setSelectedDomainId(domain.id);
    setRecentDomainIds(rememberDomainId(domain.id));
  }

  const canCreateDomain = hasRole("admin");

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <section className="grid gap-2">
        <h1 className="text-3xl font-semibold tracking-normal">Chat</h1>
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
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {messages.map((message) => (
                <ChatMessage key={message.id} message={message} now={now} />
              ))}
              <div ref={endRef} />
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
              onKeyDown={handleComposerKeyDown}
              placeholder="Ask a question"
              rows={1}
            />
            <button
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-zinc-950 text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200"
              disabled={isSubmitting || !question.trim()}
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

function ChatMessage({ message, now }: { message: Message; now: number }) {
  const elapsed = formatElapsed((message.completedAt ?? now) - message.startedAt);
  return (
    <article className="space-y-4">
      <div className="flex justify-end">
        <div className="flex max-w-[78%] items-start gap-3">
          <p className="whitespace-pre-wrap rounded-2xl bg-zinc-100 px-4 py-3 text-sm leading-6 dark:bg-zinc-900">
            {message.question}
          </p>
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-100 dark:bg-zinc-900">
            <UserRound size={17} />
          </div>
        </div>
      </div>

      <div className="flex justify-start">
        <div className="flex max-w-[82%] items-start gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
            <Bot size={17} />
          </div>
          <div className="min-w-0 rounded-2xl bg-zinc-50 px-4 py-3 text-sm leading-6 dark:bg-zinc-900">
            {message.answerStatus === "thinking" ? (
              <ThinkingState message={message} now={now} />
            ) : message.answerStatus === "error" ? (
              <p className="text-red-600 dark:text-red-300">{message.answer}</p>
            ) : (
              <>
                <p className="whitespace-pre-wrap">{message.answer}</p>
                <p className="mt-3 text-xs uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                  Thought for {elapsed} - {message.route} route - {message.language}
                </p>
                <EvaluationBadge message={message} />
              </>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function ThinkingState({ message, now }: { message: Message; now: number }) {
  const elapsedMs = now - message.startedAt;
  const phaseIndex = Math.min(
    answerPhases.length - 1,
    Math.floor(elapsedMs / 2500),
  );
  return (
    <div className="grid gap-3">
      <div className="inline-flex items-center gap-2 text-zinc-500 dark:text-zinc-400">
        <Loader2 className="animate-spin" size={15} />
        <span>
          {answerPhases[phaseIndex]} for {formatElapsed(elapsedMs)}
        </span>
      </div>
      <div className="grid gap-2">
        {answerPhases.slice(0, phaseIndex + 1).map((phase, index) => (
          <div key={phase} className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                index === phaseIndex ? "bg-zinc-950 dark:bg-white" : "bg-zinc-300 dark:bg-zinc-700"
              }`}
            />
            {phase}
          </div>
        ))}
      </div>
    </div>
  );
}

function EvaluationBadge({ message }: { message: Message }) {
  if (message.answerStatus !== "completed") return null;

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

function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

import { useEffect, useRef, useState } from "react";
import { Send, ChevronDown, ChevronRight } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { ChatMessage, ChatResponse } from "@/lib/types";

const SAMPLE_QUESTIONS = [
  "Why is Cyber flagged as a concern?",
  "Show Excess Casualty GWP vs plan for all 12 weeks",
  "Which line had the highest loss ratio last week?",
];

/**
 * crypto.randomUUID() only exists in "secure contexts" — https:// or
 * localhost. Plain http:// on a real domain/IP (e.g. a raw ALB DNS name
 * before TLS is set up) silently has no crypto.randomUUID at all, which
 * throws rather than degrading gracefully. These IDs are only used as
 * React list keys / local message identity, never sent to the backend
 * or relied on for anything security-sensitive, so a non-cryptographic
 * fallback is fine — it just needs to be unique within one chat session.
 */
function localId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

interface ChatPanelContentProps {
  runId: string | null;
}

export function ChatPanelContent({ runId }: ChatPanelContentProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send(question: string) {
    if (!question.trim() || sending) return;

    const userMsg: ChatMessage = { id: localId(), role: "user", content: question };
    const pendingMsg: ChatMessage = {
      id: localId(),
      role: "assistant",
      content: "",
      pending: true,
    };
    setMessages((prev) => [...prev, userMsg, pendingMsg]);
    setInput("");
    setSending(true);

    try {
      const res = await api.post<ChatResponse>("/chat", {
        question,
        run_id: runId,
      });
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingMsg.id
            ? {
                ...m,
                content: res.answer,
                sql: res.sql,
                rows: res.rows,
                columns: res.columns,
                pending: false,
                error: res.error,
              }
            : m,
        ),
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingMsg.id
            ? {
                ...m,
                content: "Something went wrong reaching the agent. Try again.",
                pending: false,
                error: String(err),
              }
            : m,
        ),
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm text-warmgray leading-relaxed">
              Ask about this report in plain language. Answers are grounded in the
              underlying data and connected to what the report already flagged.
            </p>
            <div className="space-y-1.5">
              {SAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="block w-full text-left text-sm text-house bg-house/8 hover:bg-house/15 px-3 py-2 rounded-md transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <ChatBubble key={m.id} message={m} />
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="border-t border-line p-3 flex items-end gap-2"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          placeholder="Ask about this report…"
          rows={1}
          className="flex-1 resize-none bg-page border border-line rounded-md px-3 py-2 text-sm text-ink placeholder:text-warmgray focus:outline-none focus:ring-2 focus:ring-house/40"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="bg-ink text-page p-2 rounded-md disabled:opacity-30 hover:bg-house transition-colors flex-shrink-0"
          aria-label="Send"
        >
          <Send size={15} />
        </button>
      </form>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const [sqlOpen, setSqlOpen] = useState(false);
  const isUser = message.role === "user";

  return (
    <div className={clsx("flex flex-col", isUser ? "items-end" : "items-start")}>
      <div
        className={clsx(
          "max-w-[92%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed",
          isUser ? "bg-ink text-page" : "bg-white border border-line text-ink",
        )}
      >
        {message.pending ? (
          <span className="inline-flex gap-1 items-center text-warmgray">
            <Dot /> <Dot delay="150ms" /> <Dot delay="300ms" />
          </span>
        ) : (
          message.content
        )}
      </div>

      {!isUser && !message.pending && message.sql && (
        <div className="mt-1.5 w-full">
          <button
            onClick={() => setSqlOpen((v) => !v)}
            className="flex items-center gap-1 text-xs text-warmgray hover:text-house transition-colors"
          >
            {sqlOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            View query
          </button>
          {sqlOpen && (
            <div className="mt-1.5 bg-ink/95 rounded-md p-3 overflow-x-auto">
              <pre className="tabular text-xs text-page/90 whitespace-pre-wrap">{message.sql}</pre>
              {message.rows && message.rows.length > 0 && (
                <div className="mt-2 pt-2 border-t border-page/10 overflow-x-auto">
                  <table className="w-full text-xs tabular">
                    <thead>
                      <tr>
                        {message.columns?.map((c) => (
                          <th key={c} className="text-left text-page/60 font-medium pr-3 pb-1">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {message.rows.slice(0, 10).map((row, i) => (
                        <tr key={i}>
                          {message.columns?.map((c) => (
                            <td key={c} className="text-page/90 pr-3 py-0.5 whitespace-nowrap">
                              {String(row[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Dot({ delay = "0ms" }: { delay?: string }) {
  return (
    <span
      className="w-1.5 h-1.5 rounded-full bg-warmgray animate-bounce"
      style={{ animationDelay: delay }}
    />
  );
}

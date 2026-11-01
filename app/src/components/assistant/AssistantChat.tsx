import { useEffect, useReducer, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Dialog as SheetPrimitive } from "radix-ui";
import { MessageCircle, Square, ArrowUp, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  FAILURE_TEXT,
  MAX_CHARS,
  assistantOff,
  bidiSegments,
  chatReducer,
  conversationFull,
  initialChat,
  markAssistantOff,
  sendChat,
  subscribeAssistant,
  toolLabel,
} from "@/lib/assistantChat";

const SUGGESTIONS = ["כמה הוצאנו על אוכל החודש?", "איך נראים הסיכומים החודשיים?", "מה המצב הכללי של הכסף?"];

/** One line of an answer: numbers, amounts and Latin runs in LTR isolates so ₪ and digits keep their order, `**x**` as semibold. */
function Line({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <>
      {parts.map((part, i) => {
        const inner = bidiSegments(part).map((s, j) =>
          s.ltr ? (
            <bdi key={j} dir="ltr" className="tabular-nums">
              {s.text}
            </bdi>
          ) : (
            s.text
          ),
        );
        return i % 2 === 1 ? <strong key={i} className="font-semibold">{inner}</strong> : <span key={i}>{inner}</span>;
      })}
    </>
  );
}

/** An assistant answer: paragraphs per line, "- " lines as a quiet list. */
export function AnswerText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (!list.length) return;
    blocks.push(
      <ul key={`l${blocks.length}`} className="ms-4 list-disc space-y-1">
        {list.map((li, i) => (
          <li key={i}><Line text={li} /></li>
        ))}
      </ul>,
    );
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    if (bullet) list.push(bullet[1]);
    else {
      flush();
      if (line) blocks.push(<p key={`p${blocks.length}`}><Line text={line} /></p>);
    }
  }
  flush();
  return <div dir="rtl" className="space-y-2 text-[15px] leading-[1.6] break-words">{blocks}</div>;
}

/** The chat itself: transcript, calm tool activity, composer. Conversation lives in this component's state only. */
function ChatPanel({ onClose }: { onClose: () => void }) {
  const [state, dispatch] = useReducer(chatReducer, initialChat);
  const [input, setInput] = useState("");
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [state.turns.length, state.tool, state.waiting, state.failure]);
  // A question that got no answer goes back into the input.
  useEffect(() => {
    if (state.draft) setInput((cur) => cur || state.draft);
  }, [state.draft]);

  async function submit(raw: string) {
    const text = raw.trim();
    if (!text || state.waiting || conversationFull(state.turns)) return;
    setInput("");
    const ctl = new AbortController();
    abort.current = ctl;
    dispatch({ type: "send", text });
    const result = await sendChat(
      [...state.turns, { role: "user", content: text.slice(0, MAX_CHARS) }],
      { onTool: (name) => dispatch({ type: "tool", name }), onAnswer: (t) => dispatch({ type: "answer", text: t }) },
      ctl.signal,
    );
    if (abort.current === ctl) abort.current = null;
    if (result === "off") {
      markAssistantOff(); // hides the whole chat
      return;
    }
    dispatch(result ? { type: "fail", failure: result } : { type: "finish" });
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(input);
  }
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit(input);
    }
  }

  const full = conversationFull(state.turns);
  const empty = state.turns.length === 0 && !state.waiting;

  return (
    <>
      <header className="flex items-center justify-between gap-2 px-5 pt-4 pb-2">
        <SheetPrimitive.Title className="font-display text-[20px] leading-[1.15] font-medium">שאלו על הכסף</SheetPrimitive.Title>
        <div className="flex items-center gap-1">
          {state.turns.length > 0 && !state.waiting && (
            <button type="button" onClick={() => dispatch({ type: "reset" })} className="rounded-full px-3 py-1.5 text-[13px] text-muted-foreground hover:text-foreground">
              שיחה חדשה
            </button>
          )}
          <SheetPrimitive.Close aria-label="סגירה" className="grid size-9 place-items-center rounded-full text-muted-foreground hover:bg-muted" onClick={onClose}>
            <X className="size-5" />
          </SheetPrimitive.Close>
        </div>
      </header>
      <SheetPrimitive.Description className="sr-only">שיחה עם העוזר על הנתונים של משק הבית. התשובות נוצרות במחשב הביתי.</SheetPrimitive.Description>

      <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-5 py-2" aria-live="polite">
        {empty && (
          <div className="space-y-3 pt-2">
            <p className="text-[15px] leading-[1.6] text-muted-foreground">אפשר לשאול על הוצאות, סיכומים חודשיים ותנועות. העוזר קורא רק את הנתונים שלכם ולא משנה דבר.</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => void submit(s)} className="rounded-full border border-[color:var(--lg-secondary-line)] bg-secondary px-3.5 py-2 text-[13px] text-secondary-foreground">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {state.turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-start">
              <div dir="rtl" className="max-w-[85%] rounded-[18px] bg-[var(--lg-primary)] px-4 py-2.5 text-[15px] leading-[1.5] break-words text-[var(--lg-on-accent)]">
                <Line text={t.content} />
              </div>
            </div>
          ) : (
            <div key={i} className="max-w-[92%] rounded-[18px] bg-panel-2 px-4 py-3">
              <AnswerText text={t.content} />
            </div>
          ),
        )}
        {state.waiting && (
          <p role="status" className="flex items-center gap-2 px-1 text-[13px] text-muted-foreground">
            <span className="size-1.5 animate-pulse rounded-full bg-[var(--lg-primary)]" aria-hidden />
            {state.tool ? toolLabel(state.tool) : "חושב…"}
          </p>
        )}
        {state.failure && (
          <p role="status" className="px-1 text-[14px] leading-[1.5] text-muted-foreground">
            {FAILURE_TEXT[state.failure]}
          </p>
        )}
        {full && !state.waiting && <p className="px-1 text-[14px] text-muted-foreground">{FAILURE_TEXT.too_long}</p>}
      </div>

      <form onSubmit={onSubmit} className="flex items-end gap-2 border-t border-line px-4 pt-3" style={{ paddingBottom: "max(env(safe-area-inset-bottom), 12px)" }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={MAX_CHARS}
          rows={1}
          dir="auto"
          placeholder="מה תרצו לדעת?"
          aria-label="השאלה שלכם"
          className="max-h-32 min-h-11 flex-1 resize-none rounded-[22px] border border-line bg-panel px-4 py-2.5 text-[16px] leading-[1.5] outline-none placeholder:text-muted-foreground focus-visible:border-[var(--lg-primary)]"
        />
        {state.waiting ? (
          <Button type="button" variant="secondary" size="icon-lg" className="size-11" aria-label="עצירה" onClick={() => abort.current?.abort()}>
            <Square className="size-4 fill-current" />
          </Button>
        ) : (
          <Button type="submit" variant="primary" size="icon-lg" className="size-11" aria-label="שליחה" disabled={!input.trim() || full}>
            <ArrowUp className="size-5" />
          </Button>
        )}
      </form>
    </>
  );
}

/**
 * Quiet entry point (a small round button above the tab bar) and the chat sheet. Renders nothing once
 * the API has answered `assistant_off` this session. Mounted once, in App.
 */
export function AssistantLauncher() {
  const off = useSyncExternalStore(subscribeAssistant, assistantOff);
  const [open, setOpen] = useState(false);
  if (off) return null;
  return (
    <SheetPrimitive.Root open={open} onOpenChange={setOpen}>
      <SheetPrimitive.Trigger asChild>
        <button
          type="button"
          aria-label="שאלו על הכסף"
          className="fixed end-4 z-30 grid size-12 place-items-center rounded-full border border-[color:var(--card-border)] bg-panel text-[var(--lg-primary)] shadow-[var(--shadow)] transition-transform duration-200 ease-[var(--ease-calm)] active:scale-95 md:end-6 md:bottom-6"
          style={{ bottom: "calc(var(--tabbar-total) + 12px)" }}
        >
          <MessageCircle className="size-5" strokeWidth={1.75} />
        </button>
      </SheetPrimitive.Trigger>
      <SheetPrimitive.Portal>
        <SheetPrimitive.Overlay className="fixed inset-0 z-50 bg-scrim/20 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
        <SheetPrimitive.Content
          dir="rtl"
          className={cn(
            "fixed inset-x-0 bottom-0 z-50 flex h-[88dvh] flex-col rounded-t-[22px] border-t border-[color:var(--card-border)] bg-popover text-popover-foreground shadow-[var(--shadow)] outline-none duration-300 ease-[var(--ease-calm)]",
            "data-open:animate-in data-open:slide-in-from-bottom-10 data-open:fade-in-0 data-closed:animate-out data-closed:slide-out-to-bottom-10 data-closed:fade-out-0",
            "md:inset-x-auto md:end-6 md:bottom-6 md:h-[640px] md:max-h-[calc(100dvh-48px)] md:w-[420px] md:rounded-[22px] md:border",
          )}
        >
          <ChatPanel onClose={() => setOpen(false)} />
        </SheetPrimitive.Content>
      </SheetPrimitive.Portal>
    </SheetPrimitive.Root>
  );
}

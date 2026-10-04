"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { ClockCounterClockwise, MagnifyingGlass, NotePencil } from "@phosphor-icons/react/ssr";
import type { SessionSummary } from "@/lib/types";
import { ago, useNow } from "@/lib/format";
import { sessionLabels } from "./session-badge";

type Item =
  | { kind: "session"; id: string; label: string; session: SessionSummary; ranges: [number, number][] }
  | { kind: "action"; id: string; label: string; href: string; icon: typeof NotePencil; ranges: [number, number][] };

/** Case-insensitive fuzzy match: contiguous hits score best, then in-order subsequences (VS Code style). */
function match(text: string, query: string): { score: number; ranges: [number, number][] } | null {
  if (!query) return { score: 0, ranges: [] };
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase();
  const at = haystack.indexOf(needle);
  if (at >= 0) return { score: 1000 - at, ranges: [[at, at + needle.length]] };
  const ranges: [number, number][] = [];
  let from = 0;
  for (const char of needle) {
    if (char === " ") continue;
    const index = haystack.indexOf(char, from);
    if (index < 0) return null;
    const last = ranges[ranges.length - 1];
    if (last && last[1] === index) last[1] = index + 1; else ranges.push([index, index + 1]);
    from = index + 1;
  }
  return { score: 500 - ranges.length * 10 - ranges[0][0], ranges };
}

function Highlight({ text, ranges }: { text: string; ranges: [number, number][] }) {
  if (!ranges.length) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  ranges.forEach(([start, end], index) => {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(<mark key={index}>{text.slice(start, end)}</mark>);
    cursor = end;
  });
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}

const ACTIONS = [
  { id: "new", label: "New investigation", href: "/", icon: NotePencil },
  { id: "history", label: "View all history", href: "/history", icon: ClockCounterClockwise },
];

export function SearchPalette({ open, onOpenChange, sessions }: { open: boolean; onOpenChange: (open: boolean) => void; sessions: SessionSummary[] }) {
  const router = useRouter();
  const now = useNow();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const { sessionItems, actionItems } = useMemo(() => {
    const sessionItems = sessions
      .map((session) => ({ session, hit: match(session.title, query.trim()) }))
      .filter((entry) => entry.hit)
      .sort((a, b) => b.hit!.score - a.hit!.score || b.session.createdAt.localeCompare(a.session.createdAt))
      .map(({ session, hit }): Item => ({ kind: "session", id: session.id, label: session.title, session, ranges: hit!.ranges }));
    const actionItems = ACTIONS
      .map((action) => ({ action, hit: match(action.label, query.trim()) }))
      .filter((entry) => entry.hit)
      .map(({ action, hit }): Item => ({ kind: "action", ...action, ranges: hit!.ranges }));
    return { sessionItems, actionItems };
  }, [sessions, query]);
  const items = useMemo(() => [...sessionItems, ...actionItems], [sessionItems, actionItems]);
  const activeIndex = Math.min(active, Math.max(items.length - 1, 0));

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  function choose(item: Item | undefined) {
    if (!item) return;
    onOpenChange(false);
    if (item.kind === "session") router.push(`/session/${encodeURIComponent(item.id)}`);
    else if (item.id === "new") router.push(`/?new=${crypto.randomUUID()}`);
    else router.push(item.href);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (!items.length) return;
    if (event.key === "ArrowDown") { event.preventDefault(); setActive((activeIndex + 1) % items.length); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((activeIndex - 1 + items.length) % items.length); }
    else if (event.key === "Enter") { event.preventDefault(); choose(items[activeIndex]); }
  }

  const row = (item: Item, index: number) => {
    const Icon = item.kind === "action" ? item.icon : null;
    return <div key={`${item.kind}-${item.id}`} id={`palette-option-${index}`} role="option" aria-selected={index === activeIndex} data-index={index}
      className={`palette-item ${index === activeIndex ? "palette-item--active" : ""}`} onMouseMove={() => setActive(index)} onClick={() => choose(item)}>
      {Icon ? <Icon size={16} className="palette-icon" /> : <span className={`status-dot status-dot--${item.kind === "session" ? item.session.status : ""}`} title={item.kind === "session" ? sessionLabels[item.session.status] : undefined} />}
      <span className={`palette-label ${item.kind === "session" && item.session.status === "running" ? "shimmer" : ""}`}><Highlight text={item.label} ranges={item.ranges} /></span>
      {item.kind === "session" && <time className="palette-meta" dateTime={item.session.createdAt}>{ago(item.session.createdAt, now)}</time>}
    </div>;
  };

  // The shell mounts the palette only while it is open, so every opening starts with a clean query.
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Overlay className="palette-overlay" />
      <Dialog.Content className="palette" aria-describedby={undefined} onKeyDown={onKeyDown}>
        <Dialog.Title className="sr-only">Search sessions</Dialog.Title>
        <div className="palette-input-row">
          <MagnifyingGlass size={16} className="palette-icon" />
          <input autoFocus className="palette-input" placeholder="Search sessions…" value={query} onChange={(event) => { setQuery(event.target.value); setActive(0); }}
            role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={items.length ? `palette-option-${activeIndex}` : undefined} aria-autocomplete="list" />
        </div>
        <div className="palette-list" id="palette-list" role="listbox" ref={listRef} aria-label="Results">
          {sessionItems.length > 0 && <p className="palette-group">{query.trim() ? "Sessions" : "Recent sessions"}</p>}
          {sessionItems.map((item, index) => row(item, index))}
          {actionItems.length > 0 && <p className="palette-group">Actions</p>}
          {actionItems.map((item, index) => row(item, sessionItems.length + index))}
          {!items.length && <p className="palette-empty">No sessions match “{query.trim()}”</p>}
        </div>
        <div className="palette-footer" aria-hidden="true"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span></div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}

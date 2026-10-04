"use client";
import { useEffect, useState, useSyncExternalStore } from "react";

const clock = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const day = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const full = new Intl.DateTimeFormat(undefined, { dateStyle: "full", timeStyle: "short" });

/** "Today 3:42 PM", "Yesterday 9:05 AM", or "Sep 28, 3:42 PM". */
export function sentAt(iso: string, now = new Date()) {
  const date = new Date(iso);
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  const prefix = days === 0 ? "Today" : days === 1 ? "Yesterday" : day.format(date) + ",";
  return `${prefix} ${clock.format(date)}`;
}

/** Compact relative age for lists: "now", "5m", "3h", "2d", then a date. */
export function ago(iso: string, now = Date.now()) {
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`;
  if (minutes < 10_080) return `${Math.floor(minutes / 1440)}d`;
  return day.format(new Date(iso));
}

export const fullDate = (iso: string) => full.format(new Date(iso));

function startOfDay(date: Date) { return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime(); }

/** Renders ⌘ on Apple platforms and Ctrl elsewhere; resolved after hydration. */
const noSubscription = () => () => {};
export function useModKey() {
  return useSyncExternalStore(noSubscription, () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl ", () => "⌘");
}

/** Re-renders periodically so relative times stay current. */
export function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), intervalMs); return () => clearInterval(timer); }, [intervalMs]);
  return now;
}

"use client";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { Tooltip } from "radix-ui";
import { NotePencil, MagnifyingGlass, ClockCounterClockwise, SidebarSimple } from "@phosphor-icons/react/ssr";
import { useSessions } from "@/hooks/use-meshmind";
import { ago, fullDate, useModKey, useNow } from "@/lib/format";
import markSrc from "@/assets/amalga-mark.png";
import { Logo } from "./logo";
import { sessionLabels } from "./session-badge";
import { SearchPalette } from "./search-palette";

const RAIL_KEY = "amalga.sidebar.rail";
const railListeners = new Set<() => void>();
function readRail() { try { return localStorage.getItem(RAIL_KEY) === "1"; } catch { return false; } }
function writeRail(value: boolean) { try { localStorage.setItem(RAIL_KEY, value ? "1" : "0"); } catch { /* storage unavailable */ } railListeners.forEach((listener) => listener()); }
function subscribeRail(listener: () => void) { railListeners.add(listener); return () => { railListeners.delete(listener); }; }

/** Icon-only rail items get a side tooltip; the expanded sidebar shows labels instead. */
function RailTip({ label, enabled, children }: { label: string; enabled: boolean; children: React.ReactElement }) {
  if (!enabled) return children;
  return <Tooltip.Root><Tooltip.Trigger asChild>{children}</Tooltip.Trigger><Tooltip.Portal><Tooltip.Content side="right" sideOffset={10} className="tooltip">{label}</Tooltip.Content></Tooltip.Portal></Tooltip.Root>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const rail = useSyncExternalStore(subscribeRail, readRail, () => false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const mobileToggleRef = useRef<HTMLButtonElement>(null);
  const isMobile = () => window.matchMedia("(max-width: 700px)").matches;
  const closeMobileSidebar = useCallback(() => {
    if (isMobile()) { setMobileOpen(false); requestAnimationFrame(() => mobileToggleRef.current?.focus()); }
  }, []);
  const pathname = usePathname();
  const router = useRouter();
  const { sessions } = useSessions();
  const mod = useModKey();
  const now = useNow();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === "k") { event.preventDefault(); setSearchOpen((open) => !open); }
      else if ((event.metaKey || event.ctrlKey) && key === "b") { event.preventDefault(); writeRail(!readRail()); }
      else if (event.key === "Escape" && !document.querySelector(".palette")) closeMobileSidebar();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeMobileSidebar]);
  const runNav = (id: "new" | "search" | "history") => {
    closeMobileSidebar();
    if (id === "new") router.push(`/?new=${crypto.randomUUID()}`);
    else if (id === "search") setSearchOpen(true);
    else router.push("/history");
  };
  const nav = [
    { id: "new" as const, label: "New investigation", icon: NotePencil, active: pathname === "/" },
    { id: "search" as const, label: "Search", icon: MagnifyingGlass, active: false, shortcut: `${mod}K` },
    { id: "history" as const, label: "History", icon: ClockCounterClockwise, active: pathname === "/history" },
  ];
  return <Tooltip.Provider delayDuration={250}>
    <div className={`app-shell ${rail ? "sidebar-rail" : ""} ${mobileOpen ? "sidebar-mobile-open" : ""}`}>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <aside id="main-navigation" className="sidebar" aria-label="Main navigation">
        <div className="sidebar-brand">
          <Link href="/" className="brand-full" onClick={closeMobileSidebar} aria-label="Amalga, new investigation"><Logo /></Link>
          <RailTip label={`Open sidebar (${mod}B)`} enabled={rail}>
            <button type="button" className="rail-mark" onClick={() => writeRail(false)} aria-label="Open sidebar">
              <Image src={markSrc} alt="" width={24} height={24} className="rail-mark-logo" /><SidebarSimple size={18} className="rail-mark-toggle" />
            </button>
          </RailTip>
          <button type="button" className="icon-button sidebar-collapse" onClick={() => writeRail(true)} aria-label="Collapse sidebar" title={`Collapse sidebar (${mod}B)`}><SidebarSimple size={18}/></button>
        </div>
        <nav className="sidebar-nav">{nav.map(({ id, label, icon: Icon, active, shortcut }) =>
          <RailTip key={label} label={label} enabled={rail}>
            <button type="button" className={`nav-item ${active ? "nav-item--active" : ""}`} onClick={() => runNav(id)} aria-label={rail ? label : undefined} aria-haspopup={label === "Search" ? "dialog" : undefined}>
              <Icon size={18}/><span className="nav-label">{label}</span>{shortcut && <kbd>{shortcut}</kbd>}
            </button>
          </RailTip>)}
        </nav>
        <div className="sidebar-section sidebar-section--recents"><p className="sidebar-label">Recents</p><div className="sidebar-recents">{sessions.map((session) => {
          const current = pathname.includes(`/session/${session.id}`);
          return <Link key={session.id} href={`/session/${session.id}`} onClick={closeMobileSidebar} className={`recent-nav ${current ? "recent-nav--active" : ""}`} aria-current={current ? "page" : undefined}>
            <span className={`status-dot status-dot--${session.status}`} title={sessionLabels[session.status]} /><span className={`recent-title ${session.status === "running" ? "shimmer" : ""}`}>{session.title}</span><span className="sr-only">, {sessionLabels[session.status]}</span>
            <time dateTime={session.createdAt} title={fullDate(session.createdAt)}>{ago(session.createdAt, now)}</time>
          </Link>;
        })}{sessions.length === 0 && <p className="sidebar-empty">No sessions yet</p>}</div></div>
      </aside>
      <button ref={mobileToggleRef} className="sidebar-toggle sidebar-toggle--mobile icon-button" aria-label={mobileOpen ? "Hide sidebar" : "Show sidebar"} aria-expanded={mobileOpen} aria-controls="main-navigation" onClick={() => setMobileOpen((open) => !open)}><SidebarSimple size={19}/></button>
      <main id="main-content" className="app-main">{children}</main>
      {searchOpen && <SearchPalette open onOpenChange={setSearchOpen} sessions={sessions} />}
    </div>
  </Tooltip.Provider>;
}

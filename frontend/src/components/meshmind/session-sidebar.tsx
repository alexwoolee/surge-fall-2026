"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { NotePencil, MagnifyingGlass, ClockCounterClockwise, SidebarSimple } from "@phosphor-icons/react/ssr";
import { useSessions } from "@/hooks/use-meshmind";
import { ago, fullDate, useModKey, useNow } from "@/lib/format";
import { Logo } from "./logo";
import { sessionLabels } from "./session-badge";
import { SpaceBackground } from "./space-background";
import { SearchPalette } from "./search-palette";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const desktopToggleRef = useRef<HTMLButtonElement>(null);
  const mobileToggleRef = useRef<HTMLButtonElement>(null);
  const collapseRef = useRef<HTMLButtonElement>(null);
  const closeSidebar = useCallback(() => {
    const mobile = window.matchMedia("(max-width: 700px)").matches;
    if (mobile) setMobileOpen(false);
    else setCollapsed(true);
    requestAnimationFrame(() => (mobile ? mobileToggleRef : desktopToggleRef).current?.focus());
  }, []);
  const closeMobileSidebar = () => {
    if (window.matchMedia("(max-width: 700px)").matches && mobileOpen) {
      setMobileOpen(false);
      requestAnimationFrame(() => mobileToggleRef.current?.focus());
    }
  };
  const pathname = usePathname();
  const router = useRouter();
  const { sessions } = useSessions();
  const mod = useModKey();
  const now = useNow();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setSearchOpen((open) => !open); }
      else if (event.key === "Escape" && !document.querySelector(".palette")) closeSidebar();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeSidebar]);
  const newSession = () => { closeMobileSidebar(); router.push(`/?new=${crypto.randomUUID()}`); };
  return <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""} ${mobileOpen ? "sidebar-mobile-open" : ""}`}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside id="main-navigation" className="sidebar" aria-label="Main navigation">
      <div className="sidebar-brand"><Link href="/" onClick={closeMobileSidebar} aria-label="Amalga, new session"><Logo /></Link><button ref={collapseRef} className="icon-button" onClick={closeSidebar} aria-label="Hide sidebar" title="Hide sidebar"><SidebarSimple size={18}/></button></div>
      <nav className="sidebar-nav">
        <button type="button" className={`nav-item ${pathname === "/" ? "nav-item--active" : ""}`} onClick={newSession}><NotePencil size={18}/><span>New session</span></button>
        <button type="button" className="nav-item" onClick={() => { closeMobileSidebar(); setSearchOpen(true); }} aria-haspopup="dialog"><MagnifyingGlass size={18}/><span>Search</span><kbd>{mod}K</kbd></button>
        <Link href="/history" onClick={closeMobileSidebar} className={`nav-item ${pathname === "/history" ? "nav-item--active" : ""}`}><ClockCounterClockwise size={18}/><span>History</span></Link>
      </nav>
      <div className="sidebar-section sidebar-section--recents"><p className="sidebar-label">Recents</p><div className="sidebar-recents">{sessions.map((session) => {
        const current = pathname.includes(`/session/${session.id}`);
        return <Link key={session.id} href={`/session/${session.id}`} onClick={closeMobileSidebar} className={`recent-nav ${current ? "recent-nav--active" : ""}`} aria-current={current ? "page" : undefined}>
          <span className={`status-dot status-dot--${session.status}`} title={sessionLabels[session.status]} /><span className="recent-title">{session.title}</span><span className="sr-only">, {sessionLabels[session.status]}</span>
          <time dateTime={session.createdAt} title={fullDate(session.createdAt)}>{ago(session.createdAt, now)}</time>
        </Link>;
      })}{sessions.length === 0 && <p className="sidebar-empty">No sessions yet</p>}</div></div>
    </aside>
    <button ref={desktopToggleRef} className="sidebar-toggle sidebar-toggle--desktop icon-button" aria-label="Show sidebar" title="Show sidebar" aria-expanded={!collapsed} aria-controls="main-navigation" onClick={() => { setCollapsed(false); requestAnimationFrame(() => collapseRef.current?.focus()); }}><SidebarSimple size={19}/></button>
    <button ref={mobileToggleRef} className="sidebar-toggle sidebar-toggle--mobile icon-button" aria-label={mobileOpen ? "Hide sidebar" : "Show sidebar"} aria-expanded={mobileOpen} aria-controls="main-navigation" onClick={() => setMobileOpen((open) => !open)}><SidebarSimple size={19}/></button>
    <main id="main-content" className="app-main"><SpaceBackground />{children}</main>
    {searchOpen && <SearchPalette open onOpenChange={setSearchOpen} sessions={sessions} />}
  </div>;
}

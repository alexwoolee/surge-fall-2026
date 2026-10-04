"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Home, SquarePlus, Search, History, PanelLeftClose, PanelLeft, ArrowUpRight } from "lucide-react";
import { useSessions } from "@/hooks/use-meshmind";
import { Logo } from "./logo";
import { isDemoMode } from "@/lib/data-provider";
import { sessionLabels } from "./session-badge";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
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
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") { event.preventDefault(); router.push("/history?search=1"); }
      if (event.key === "Escape") closeSidebar();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, closeSidebar]);
  const nav = [{href:"/",label:"Home",icon:Home}, {href:"/?new=1",label:"New investigation",icon:SquarePlus}, {href:"/history?search=1",label:"Search sessions",icon:Search}, {href:"/history",label:"History",icon:History}];
  return <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""} ${mobileOpen ? "sidebar-mobile-open" : ""}`}>
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside id="main-navigation" className="sidebar" aria-label="Main navigation">
      <div className="sidebar-brand"><Link href="/" onClick={closeMobileSidebar} aria-label="MeshMind home"><Logo /></Link><button ref={collapseRef} className="icon-button" onClick={closeSidebar} aria-label="Collapse sidebar"><PanelLeftClose size={17}/></button></div>
      <nav>{nav.map(({href,label,icon:Icon}) => <Link key={label} href={href} onClick={(event) => { closeMobileSidebar(); if (label === "New investigation") { event.preventDefault(); router.push(`/?new=${crypto.randomUUID()}`); } }} className={`nav-item ${((href === "/" && pathname === "/") || (href === "/history" && pathname === "/history")) ? "nav-item--active" : ""}`}><Icon size={18}/><span>{label}</span>{label === "Search sessions" && <kbd>⌘K</kbd>}</Link>)}</nav>
      <div className="sidebar-section"><p className="sidebar-label">Recents</p><div className="sidebar-recents">{sessions.slice(0,5).map((session) => <Link key={session.id} href={`/session/${session.id}`} onClick={closeMobileSidebar} className={`recent-nav ${pathname.includes(`/session/${session.id}`) ? "recent-nav--active" : ""}`}><span>{session.title}</span><small>{sessionLabels[session.status]}</small></Link>)}</div></div>
      <div className="sidebar-section"><p className="sidebar-label">Workers</p><Link href={sessions[0] ? `/worker/hydro?session=${encodeURIComponent(sessions[0].id)}` : "/worker/hydro"} onClick={closeMobileSidebar} className="worker-nav-link"><span className="worker-nav-mark">2</span><span>Hydrometeorology<small>Laptop 2</small></span><ArrowUpRight size={14}/></Link><Link href={sessions[0] ? `/worker/flood?session=${encodeURIComponent(sessions[0].id)}` : "/worker/flood"} onClick={closeMobileSidebar} className="worker-nav-link"><span className="worker-nav-mark">3</span><span>Surface Water & Terrain<small>Laptop 3</small></span><ArrowUpRight size={14}/></Link></div>
      <div className="sidebar-foot"><span className="demo-indicator"/>{isDemoMode ? "Frontend demo" : "Control workspace"}<p>{isDemoMode ? "Simulated activity & evidence" : "Validated environmental evidence"}</p></div>
    </aside>
    <button ref={desktopToggleRef} className="sidebar-toggle sidebar-toggle--desktop icon-button" aria-label="Expand sidebar" aria-expanded={!collapsed} aria-controls="main-navigation" onClick={() => { setCollapsed(false); requestAnimationFrame(() => collapseRef.current?.focus()); }}><PanelLeft size={20}/></button>
    <button ref={mobileToggleRef} className="sidebar-toggle sidebar-toggle--mobile icon-button" aria-label={mobileOpen ? "Collapse sidebar" : "Expand sidebar"} aria-expanded={mobileOpen} aria-controls="main-navigation" onClick={() => setMobileOpen((open) => !open)}><PanelLeft size={20}/></button>
    <main id="main-content" className="app-main"><div className="ambient-field" aria-hidden="true"/>{children}</main>
  </div>;
}

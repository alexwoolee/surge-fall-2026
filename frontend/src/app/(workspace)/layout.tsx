import { AppShell } from "@/components/meshmind/session-sidebar";

/** One shell for every operator route, so the sidebar keeps its state across navigation. */
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

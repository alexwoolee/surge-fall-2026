import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "MeshMind — Environmental intelligence",
  description: "A focused workspace for environmental investigations, specialist evidence, and grounded briefings.",
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en" className="dark"><body>{children}</body></html>;
}

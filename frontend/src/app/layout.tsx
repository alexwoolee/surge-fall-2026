import type { Metadata } from "next";
import { Geist_Mono, Inter, Inter_Tight } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const display = Inter_Tight({ subsets: ["latin"], weight: ["300", "400", "500"], variable: "--font-display-face" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

// No root title: investigation pages name the browser tab after the loaded session on the client,
// and a streamed metadata title would overwrite it. Other routes declare their own titles.
export const metadata: Metadata = {
  description: "A focused workspace for environmental investigations, specialist evidence, and grounded briefings.",
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en" className={`dark ${inter.variable} ${display.variable} ${mono.variable}`}><body>{children}</body></html>;
}

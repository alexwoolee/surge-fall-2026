import Link from "next/link";
export const metadata = { title: "Not found · Amalga" };
export default function NotFound() { return <main className="view-empty-state"><h1>This page is unavailable.</h1><Link href="/" className="back-link">Back to Amalga</Link></main>; }

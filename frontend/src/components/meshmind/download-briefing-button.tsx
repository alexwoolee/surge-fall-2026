"use client";

import { DownloadSimple } from "@phosphor-icons/react/ssr";
import { Button } from "@/components/ui/button";
import { getMockBriefingDownload } from "@/lib/mock-download";
import { briefingDownload } from "@/lib/api-provider";
import { isDemoMode } from "@/lib/data-provider";
import type { BriefingViewModel } from "@/lib/types";

export function DownloadBriefingButton({ briefing, sessionId, label }: { briefing: BriefingViewModel; sessionId: string; label?: string }) {
  const { href, filename } = isDemoMode ? getMockBriefingDownload(briefing) : briefingDownload(sessionId);
  return <span className="download-action"><Button className="primary-action" asChild><a href={href} download={filename}>
    <DownloadSimple size={16} aria-hidden="true" />{label || "Download briefing (HTML)"}
  </a></Button></span>;
}

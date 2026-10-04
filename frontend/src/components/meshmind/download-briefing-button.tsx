"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getMockBriefingDownload } from "@/lib/mock-download";
import { briefingDownload } from "@/lib/api-provider";
import { isDemoMode } from "@/lib/data-provider";
import type { BriefingViewModel } from "@/lib/types";

export function DownloadBriefingButton({ briefing, sessionId, label }: { briefing: BriefingViewModel; sessionId: string; label?: string }) {
  const { href, filename } = isDemoMode ? getMockBriefingDownload(briefing) : briefingDownload(sessionId);
  return <span className="download-action"><Button className="primary-action" asChild><a href={href} download={filename}>
    <Download size={16} aria-hidden="true" />{label || (briefing.partial && !briefing.risk ? "Download partial briefing" : "Download briefing (HTML)")}
  </a></Button></span>;
}

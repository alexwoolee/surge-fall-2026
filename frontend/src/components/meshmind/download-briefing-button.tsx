"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getMockBriefingDownload } from "@/lib/mock-download";
import type { BriefingViewModel } from "@/lib/types";

export function DownloadBriefingButton({ briefing, label }: { briefing: BriefingViewModel; label?: string }) {
  const {href, filename} = getMockBriefingDownload(briefing);

  return (
    <span className="download-action">
      <Button className="primary-action" asChild><a href={href} download={filename}>
        <Download size={16} aria-hidden="true" />
        {label || (briefing.partial ? "Download partial briefing" : "Download briefing (HTML)")}
      </a></Button>
    </span>
  );
}

// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { AgStudio, AgStudioProvider } from "ag-studio-react";

type Row = Record<string, boolean | number | string | null | undefined>;

export interface StudioSource {
  id: string;
  data: Row[];
}

export default function AgStudioWorkspace({ sources }: { sources: StudioSource[] }) {
  const studio = (
    <div className="h-[680px] min-h-[520px] w-full overflow-hidden rounded-[11px] border border-(--line)">
      <AgStudio data={{ sources }} mode="edit" />
    </div>
  );
  const licenseKey = process.env.NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY;

  return licenseKey ? <AgStudioProvider licenseKey={licenseKey}>{studio}</AgStudioProvider> : studio;
}

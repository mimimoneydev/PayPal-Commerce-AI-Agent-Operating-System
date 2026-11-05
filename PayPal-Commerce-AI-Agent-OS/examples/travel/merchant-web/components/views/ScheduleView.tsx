// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import dynamic from "next/dynamic";
import { Notice, PageHeader, Panel, Skeleton, useResource } from "web-shared";
import { fetchOccupancy } from "@/lib/api";
import IntegrationBoundary from "@/components/IntegrationBoundary";

const BryntumOccupancyScheduler = dynamic(() => import("@/components/schedule/BryntumOccupancyScheduler"), {
  ssr: false,
  loading: () => <Skeleton className="h-[640px]" />,
});

export default function ScheduleView({ refreshKey }: { refreshKey: number }) {
  const { data, failed } = useResource(fetchOccupancy, [refreshKey]);

  return (
    <div className="ac-reveal flex flex-col gap-4">
      <PageHeader title="Revenue schedule" subtitle="Compare weekly occupancy, nightly rates, and staged overrides across every property." />
      {failed && !data ? (
        <Notice>The travel API isn&apos;t reachable, so the revenue schedule can&apos;t load.</Notice>
      ) : !data ? (
        <Skeleton className="h-[640px]" />
      ) : (
        <Panel title="Occupancy and rates" subtitle={`${data.window.from} to ${data.window.to} · read-only operational view`}>
          {data.staged_windows.length ? (
            <p className="mx-3 mb-2 rounded-[9px] bg-(--accent-soft) px-3 py-2 text-[12.5px] text-(--accent-ink)">
              {data.staged_windows.length} staged rate {data.staged_windows.length === 1 ? "window is" : "windows are"} shown as orange overrides. Approval remains in the assistant workflow.
            </p>
          ) : null}
          <div className="mx-3 mb-3 h-[640px] overflow-hidden rounded-[11px] border border-(--line)">
            <IntegrationBoundary name="Bryntum Scheduler">
              <BryntumOccupancyScheduler data={data} />
            </IntegrationBoundary>
          </div>
        </Panel>
      )}
    </div>
  );
}

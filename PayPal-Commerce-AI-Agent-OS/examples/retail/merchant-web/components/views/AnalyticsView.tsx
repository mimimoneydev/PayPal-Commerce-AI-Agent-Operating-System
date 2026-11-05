// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { Notice, PageHeader, Panel, Skeleton, useResource } from "web-shared";
import { fetchAlerts, fetchListings, fetchOverview } from "@/lib/api";
import type { OverviewResponse } from "@/lib/types";
import type { StudioSource } from "@/components/analytics/AgStudioWorkspace";
import IntegrationBoundary from "@/components/IntegrationBoundary";

const AgStudioWorkspace = dynamic(() => import("@/components/analytics/AgStudioWorkspace"), {
  ssr: false,
  loading: () => <Skeleton className="h-[680px]" />,
});

function metricRows(overview: OverviewResponse): StudioSource["data"] {
  return Object.entries(overview.trends ?? {}).flatMap(([metric, points]) =>
    points.map((point) => ({ metric, date: point.date, value: point.value, period: overview.snapshot.period })),
  );
}

export default function AnalyticsView({ refreshKey }: { refreshKey: number }) {
  const overview = useResource(fetchOverview, [refreshKey]);
  const listings = useResource(fetchListings, [refreshKey]);
  const alerts = useResource(fetchAlerts, [refreshKey]);
  const loading = !overview.data || !listings.data || !alerts.data;
  const failed = overview.failed || listings.failed || alerts.failed;

  const sources = useMemo<StudioSource[]>(() => {
    if (!overview.data || !listings.data || !alerts.data) return [];
    return [
      { id: "performance_trends", data: metricRows(overview.data) },
      {
        id: "catalog",
        data: listings.data.listings.map((listing) => ({
          listing_id: listing.listing_id,
          title: listing.title,
          status: listing.status,
          category: listing.category,
          price: listing.price,
          currency: listing.currency ?? "USD",
          stock: listing.stock,
          content_quality: listing.content_quality,
        })),
      },
      {
        id: "inventory_alerts",
        data: alerts.data.inventory.map((alert) => ({
          listing_id: alert.listing_id,
          title: alert.title,
          alert_type: alert.kind,
          stock: alert.stock,
          threshold: alert.threshold,
          days_of_cover: alert.days_of_cover,
          sales_last_30d: alert.sales_last_30d,
        })),
      },
      {
        id: "order_issues",
        data: alerts.data.order_issues.map((issue) => ({
          issue_id: issue.issue_id,
          order_id: issue.order_id,
          issue_type: issue.kind,
          summary: issue.summary,
          listing_id: issue.listing_id,
          opened_at: issue.opened_at,
        })),
      },
      {
        id: "recent_orders",
        data: overview.data.recent_orders.map((order) => ({ ...order })),
      },
      {
        id: "change_history",
        data: overview.data.recent_changes.map((change) => ({
          change_id: change.change_id,
          type: change.kind,
          status: change.status,
          summary: change.summary,
          created_at: change.created_at,
          created_by: change.created_by,
          margin_impact: change.margin_impact,
        })),
      },
    ];
  }, [alerts.data, listings.data, overview.data]);

  return (
    <div className="ac-reveal flex flex-col gap-4">
      <PageHeader title="Analytics studio" subtitle="Build grids, charts, KPI tiles, and cross-filtered reports from live merchant data." />
      {failed && loading ? (
        <Notice>The merchant API isn&apos;t reachable, so analytics data can&apos;t load.</Notice>
      ) : loading ? (
        <Skeleton className="h-[680px]" />
      ) : (
        <Panel title="Merchant control center" subtitle={`${sources.length} governed data sources · drag fields onto the canvas`}>
          <div className="px-3 pb-3">
            <IntegrationBoundary name="AG Studio">
              <AgStudioWorkspace sources={sources} />
            </IntegrationBoundary>
          </div>
        </Panel>
      )}
    </div>
  );
}

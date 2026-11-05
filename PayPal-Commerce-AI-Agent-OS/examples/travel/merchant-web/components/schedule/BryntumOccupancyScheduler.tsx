// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { BryntumScheduler } from "@bryntum/scheduler-react";
import type { OccupancyOverviewResponse } from "@/lib/types";

function addDays(value: string, days: number): Date {
  const result = new Date(`${value}T00:00:00`);
  result.setUTCDate(result.getUTCDate() + days);
  return result;
}

function occupancyPct(raw?: number | null): number | null {
  if (raw == null || Number.isNaN(raw)) return null;
  return Math.round(raw > 0 && raw <= 1 ? raw * 100 : raw);
}

export default function BryntumOccupancyScheduler({ data }: { data: OccupancyOverviewResponse }) {
  const resources = data.properties.map((property, index) => ({
    id: property.listing_id ?? `property-${index}`,
    name: property.title ?? property.listing_id ?? "Property",
    rooms: property.rooms ?? 0,
    baseRate: property.base_nightly_rate ?? 0,
  }));
  const events = data.properties.flatMap((property, propertyIndex) => {
    const resourceId = property.listing_id ?? `property-${propertyIndex}`;
    return (property.weeks ?? []).flatMap((week, weekIndex) => {
      if (!week.week_start) return [];
      const pct = occupancyPct(week.occupancy_pct);
      const rate = week.nightly_rate ?? property.base_nightly_rate;
      const label = [rate != null ? `$${Math.round(rate)}` : null, pct != null ? `${pct}% booked` : null]
        .filter(Boolean)
        .join(" · ");
      return [{
        id: `${resourceId}-${week.week_start}-${weekIndex}`,
        resourceId,
        name: `${week.override ? "Override · " : ""}${label || "Occupancy"}`,
        startDate: addDays(week.week_start, 0),
        endDate: addDays(week.week_start, 7),
        eventColor: week.override ? "orange" : pct != null && pct >= 85 ? "red" : pct != null && pct >= 65 ? "blue" : "green",
      }];
    });
  });

  return (
    <BryntumScheduler
      startDate={addDays(data.window.from, 0)}
      endDate={addDays(data.window.to, 1)}
      viewPreset="weekAndMonth"
      rowHeight={52}
      barMargin={7}
      readOnly
      resources={resources}
      events={events}
      columns={[
        { text: "Property", field: "name", width: 220, flex: 1 },
        { text: "Rooms", field: "rooms", width: 72 },
        { text: "Base rate", field: "baseRate", width: 90, renderer: ({ value }: { value: number }) => `$${value}` },
      ]}
      height="640px"
    />
  );
}

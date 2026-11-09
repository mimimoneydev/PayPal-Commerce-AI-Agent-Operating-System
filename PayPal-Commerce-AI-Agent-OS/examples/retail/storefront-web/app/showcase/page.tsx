// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

/** Renders lib/showcase-fixtures.ts; no API needed. */

import CartPanel from "@/components/CartPanel";
import GenerativeBlock from "@/components/generative";
import { SHOWCASE, SHOWCASE_CART, SHOWCASE_RECEIPT } from "@/lib/showcase-fixtures";

const SECTIONS = Object.keys(SHOWCASE) as (keyof typeof SHOWCASE)[];

function Section({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="mb-3 font-mono text-sm text-(--ink-soft)">{name}</h2>
      <div data-component={name}>{children}</div>
    </section>
  );
}

export default function ShowcasePage() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-(--ink-soft)">
        ACME component showcase (fixture data)
      </p>
      {SECTIONS.map((name) => (
        <Section key={name} name={name}>
          <GenerativeBlock block={{ component: name, payload: SHOWCASE[name] }} status="final" onAdd={() => true} />
        </Section>
      ))}
      <Section name="checkout-receipt">
        <p className="mb-2 text-[11px] text-(--ink-soft)">
          Component fixture — placeholder identifiers, no PayPal order was created. Real ids are
          recorded in SANDBOX-PROOF.md after a sandbox run.
        </p>
        <GenerativeBlock
          block={{ component: "checkout", payload: SHOWCASE_RECEIPT }}
          status="final"
          onAdd={() => true}
        />
      </Section>
      <Section name="cart">
        <div className="flex h-[440px] flex-col overflow-hidden rounded-xl border border-(--line) bg-(--card)">
          <CartPanel cart={SHOWCASE_CART} />
        </div>
      </Section>
    </main>
  );
}

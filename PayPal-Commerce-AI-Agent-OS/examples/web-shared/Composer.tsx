// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "./icons";
import { useVoiceInput } from "./speech";

export interface Prefill {
  text: string;
  /** Changes on every request so the same text can be offered twice. */
  nonce: number;
}

const VARIANTS = {
  /** The storefront's composer under the page: one roomy field with the send arrow inside it. */
  dock: {
    form: "items-center gap-2 rounded-[16px] border border-(--line-strong) bg-(--card) py-1.5 pl-4 pr-1.5 shadow-(--shadow) transition-colors focus-within:border-(--accent)",
    input: "bg-transparent py-1.5 text-[16px]",
    button: "h-9 w-9 rounded-[11px]",
  },
  /** The portal rail: the same field, compact. */
  field: {
    form: "items-center gap-1.5 rounded-[14px] border border-(--line-strong) bg-(--card) py-[5px] pl-3.5 pr-[5px] shadow-(--shadow-sm) transition-colors focus-within:border-(--accent)",
    // 16px below lg so touch browsers do not zoom on focus.
    input: "bg-transparent py-1.5 text-[16px] lg:text-[14.5px]",
    button: "h-8 w-8 rounded-[10px]",
  },
};

/**
 * The shared chat input for the storefront and the merchant portal. Spoken words
 * only fill the draft: the shopper or operator still presses Enter or Send.
 * A prefill also only fills the draft. screenshot_tour.py waits on "Working…".
 */
export function Composer({
  send,
  ready,
  busy,
  label,
  placeholder,
  prefill,
  variant = "dock",
  className = "",
}: {
  send: (text: string) => void;
  ready: boolean;
  busy: boolean;
  label: string;
  placeholder: string;
  prefill?: Prefill | null;
  variant?: keyof typeof VARIANTS;
  className?: string;
}) {
  const [draft, setDraft] = useState("");
  const boxRef = useRef<HTMLTextAreaElement>(null);
  /** Whatever was typed before dictation began, so speech appends instead of overwriting. */
  const voiceBaseRef = useRef("");
  const wasListeningRef = useRef(false);

  const voice = useVoiceInput((text) => {
    const base = voiceBaseRef.current;
    setDraft(base ? `${base} ${text}` : text);
  });

  useEffect(() => {
    if (!prefill) return;
    setDraft(prefill.text);
    boxRef.current?.focus();
  }, [prefill]);

  // Hand focus back to the field when dictation ends so Enter/Send is one keystroke away.
  useEffect(() => {
    if (wasListeningRef.current && !voice.listening) boxRef.current?.focus();
    wasListeningRef.current = voice.listening;
  }, [voice.listening]);

  const submit = () => {
    if (!draft.trim() || busy || !ready) return;
    voice.stop();
    send(draft);
    setDraft("");
  };

  const onMicrophone = () => {
    if (!voice.listening) voiceBaseRef.current = draft.trim();
    voice.toggle();
  };

  // An error outranks the listening label so a refused microphone is never hidden.
  const hint = voice.error ?? (voice.listening ? "Listening… speak in English" : null);

  return (
    <form
      className={`relative flex ${VARIANTS[variant].form} ${className}`}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {hint ? (
        <div
          role="status"
          aria-live="polite"
          className={`pointer-events-none absolute -top-8 left-0 max-w-full truncate rounded-lg px-2.5 py-1 text-[12px] shadow-(--shadow-sm) ${
            voice.error ? "bg-(--warn-soft) text-(--warn)" : "bg-(--accent) text-(--on-accent)"
          }`}
        >
          {hint}
        </div>
      ) : null}
      <textarea
        ref={boxRef}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        rows={1}
        aria-label={label}
        placeholder={busy ? "Working…" : placeholder}
        className={`max-h-40 min-w-0 flex-1 resize-none text-(--ink) outline-none transition placeholder:text-(--ink-soft)/70 ${VARIANTS[variant].input}`}
      />
      <button
        type="button"
        onClick={onMicrophone}
        disabled={busy || !voice.supported}
        aria-label={voice.listening ? "Stop voice input" : "Voice input: speak in English"}
        aria-pressed={voice.listening}
        title={
          !voice.supported
            ? "Voice input needs Chrome, Edge or Safari"
            : voice.listening
              ? "Stop listening"
              : "Speak instead of typing (English)"
        }
        className={`grid shrink-0 place-items-center transition disabled:opacity-35 ${
          voice.listening
            ? "bg-(--accent) text-(--on-accent)"
            : "text-(--ink-soft) hover:bg-(--well) hover:text-(--ink)"
        } ${VARIANTS[variant].button}`}
      >
        <Icon name="mic" size={16} />
      </button>
      <button
        type="submit"
        disabled={busy || !ready || !draft.trim()}
        aria-label="Send"
        className={`grid shrink-0 place-items-center bg-(--ink) text-(--surface) transition hover:brightness-110 disabled:opacity-35 ${VARIANTS[variant].button}`}
      >
        <Icon name="arrow-up" size={16} />
      </button>
    </form>
  );
}

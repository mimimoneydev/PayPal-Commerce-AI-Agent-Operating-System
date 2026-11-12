// Copyright 2026 PayPal Commerce AI Agent OS contributors
// SPDX-License-Identifier: Apache-2.0

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The Web Speech API's recognition types are not part of TypeScript's DOM lib,
 * so the small slice the composer needs is declared here. Chrome, Edge and
 * Safari expose the same object as `webkitSpeechRecognition`.
 */
interface RecognitionAlternative {
  readonly transcript: string;
}
interface RecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: RecognitionAlternative;
}
interface RecognitionResultList {
  readonly length: number;
  readonly [index: number]: RecognitionResult;
}
interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: RecognitionResultList;
}
interface RecognitionErrorEvent {
  readonly error: string;
}
interface SpeechRecognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionConstructor = new () => SpeechRecognition;

type SpeechWindow = {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

interface ActiveRecognition {
  recognition: SpeechRecognition;
  /** A user-initiated stop should not be reported as an error. */
  stopRequested: boolean;
}

function recognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as SpeechWindow;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const ERROR_COPY: Record<string, string> = {
  "no-speech": "No speech heard. Press the microphone and try again.",
  "audio-capture": "No microphone found. Check your device.",
  "not-allowed": "Microphone access is blocked. Allow it in your browser's site settings.",
  "service-not-allowed": "Voice input is blocked by the browser. Allow microphone access.",
  network: "Speech service is unreachable. Check your connection.",
  language: "English speech recognition is unavailable on this device.",
};

/**
 * Browser-native English dictation. `onTranscript` receives the whole utterance
 * (final words plus any interim words) on every update, so the caller replaces
 * rather than appends and interim text never duplicates. Nothing is sent
 * automatically: the words only fill the composer draft.
 */
export function useVoiceInput(onTranscript: (text: string) => void) {
  // Starts false so the server and the first client render agree; the effect
  // below enables the button once the browser's API has been detected.
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRef = useRef<ActiveRecognition | null>(null);
  const callbackRef = useRef(onTranscript);
  callbackRef.current = onTranscript;

  useEffect(() => {
    setSupported(recognitionConstructor() !== null);
    return () => {
      const active = activeRef.current;
      activeRef.current = null;
      if (!active) return;
      active.recognition.onresult = null;
      active.recognition.onerror = null;
      active.recognition.onend = null;
      active.recognition.abort();
    };
  }, []);

  useEffect(() => {
    if (!error) return;
    const timer = window.setTimeout(() => setError(null), 7000);
    return () => window.clearTimeout(timer);
  }, [error]);

  const stop = useCallback(() => {
    const active = activeRef.current;
    if (!active) return;
    active.stopRequested = true;
    active.recognition.stop();
  }, []);

  const toggle = useCallback(() => {
    const Constructor = recognitionConstructor();
    if (!Constructor) {
      setError("Voice input needs Chrome, Edge or Safari.");
      return;
    }
    if (activeRef.current) {
      stop();
      return;
    }

    const recognition = new Constructor();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    // `results` is cumulative (final words first, then any interim words), so
    // rebuild the whole utterance each time instead of accumulating deltas.
    // A browser that re-sends earlier results can then never duplicate words.
    recognition.onresult = (event) => {
      let words = "";
      for (let i = 0; i < event.results.length; i += 1) {
        words += event.results[i][0]?.transcript ?? "";
      }
      const text = words.replace(/\s+/g, " ").trim();
      if (text) callbackRef.current(text);
    };
    recognition.onerror = (event) => {
      if (event.error === "aborted" || activeRef.current?.stopRequested) return;
      // Some browsers fire onerror without a following onend; do not leave the
      // button stuck in its listening state when that happens.
      setListening(false);
      setError(ERROR_COPY[event.error] ?? "Voice input stopped. Please try again.");
    };
    recognition.onend = () => {
      if (activeRef.current?.recognition === recognition) activeRef.current = null;
      setListening(false);
    };

    const active: ActiveRecognition = { recognition, stopRequested: false };
    activeRef.current = active;
    setError(null);
    setListening(true);
    try {
      recognition.start();
    } catch {
      activeRef.current = null;
      setListening(false);
      setError("Could not start voice input. Please try again.");
    }
  }, [stop]);

  return { supported, listening, error, toggle, stop, clearError: () => setError(null) };
}

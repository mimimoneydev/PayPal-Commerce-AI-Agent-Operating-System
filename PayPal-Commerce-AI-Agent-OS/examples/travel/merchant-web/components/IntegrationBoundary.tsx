// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { Notice } from "web-shared";

interface Props {
  children: ReactNode;
  name: string;
}

interface State {
  failed: boolean;
}

/** Keep an optional commercial widget failure contained to its own portal panel. */
export default class IntegrationBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`${this.props.name} failed to render`, error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <Notice>
          {this.props.name} couldn&apos;t start in this browser. The rest of the merchant
          workspace is still available.
        </Notice>
      );
    }
    return this.props.children;
  }
}

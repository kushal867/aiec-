import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  onError?: (error: Error) => void;
  /** Name shown nowhere to the end user — only in the dev console — so
   * integrators can tell which widget instance failed when several are on
   * one page. */
  label: string;
}

interface State {
  hasError: boolean;
}

/** Without this, an unhandled error anywhere in the widget's render tree
 * (e.g. crypto.randomUUID() being unavailable — see sessionId.ts) unmounts
 * every component below the nearest error boundary in the HOST page, not
 * just this widget. A client's whole site going blank because of an embedded
 * chat widget is the worst-case outcome this exists to prevent. Falls back
 * to rendering nothing rather than a placeholder, since a broken widget
 * silently absent is a better default than a placeholder box an integrator
 * didn't design for. */
export class WidgetErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`[AIEC widget] ${this.props.label} crashed:`, error, info.componentStack);
    this.props.onError?.(error);
  }

  render(): ReactNode {
    if (this.state.hasError) return null;
    return this.props.children;
  }
}

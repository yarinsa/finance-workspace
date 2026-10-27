import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * App-wide error boundary to catch render errors anywhere in the React tree.
 * Without this, a render error in any component (e.g. RangeError: Invalid time value)
 * unmounts the entire app and leaves the installed iPhone PWA blank and unresponsive.
 * Shows a recovery UI (RTL, Hebrew, matching main.tsx's fail() style) with options
 * to retry or reload the page.
 */
export default class AppErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: unknown) {
    console.error("App render error caught by boundary:", error);
  }

  resetError = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div dir="rtl" style={{ padding: "2rem", fontFamily: "system-ui", lineHeight: 1.6 }}>
          <h1 style={{ fontSize: "1.25rem", marginBottom: ".5rem" }}>משהו השתבש</h1>
          <p style={{ color: "var(--lg-muted, #5e6b60)", fontSize: "0.875rem", marginBottom: "1rem" }}>
            {this.state.error.message || "שגיאה לא צפויה"}
          </p>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              type="button"
              onClick={this.resetError}
              style={{
                padding: ".6rem 1.2rem",
                borderRadius: 999,
                border: 0,
                background: "var(--lg-primary, #314c3b)",
                color: "var(--lg-on-accent, #f7f3ea)",
                fontSize: "1rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              נסה שוב
            </button>
            <button
              type="button"
              onClick={() => location.reload()}
              style={{
                padding: ".6rem 1.2rem",
                borderRadius: 999,
                border: "1px solid var(--lg-secondary-line, #bdc9b8)",
                background: "transparent",
                color: "var(--lg-text, #1f2a23)",
                fontSize: "1rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              טען מחדש
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

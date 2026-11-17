import { AlertTriangle, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { Wordmark } from "../components/Wordmark";
import { Spinner } from "../components/States";
import { useAuth } from "../lib/auth";
import { usePageTitle } from "../lib/usePageTitle";

/**
 * Shown only when the console cannot open a session at all - almost always a
 * backend that is asleep or unreachable. There is no login form to fall back
 * to, so this screen offers a retry plus the public portal.
 */
export function ConnectionFailed({
  message,
  onRetry,
}: {
  message: string | null;
  onRetry: () => void;
}) {
  usePageTitle("Connecting");
  const { status, demoEnabled } = useAuth();
  const pending = status === "loading";
  const demoOff = !demoEnabled;

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="flex h-16 items-center px-5 sm:px-8">
        <Wordmark />
      </header>

      <main id="main" className="flex flex-1 items-center justify-center px-5 py-10">
        <div className="w-full max-w-md">
          <div className="card overflow-hidden">
            <div
              className="h-1.5 w-full"
              style={{ background: "linear-gradient(90deg, var(--aurora-1), var(--aurora-2), var(--aurora-3))" }}
              aria-hidden
            />
            <div className="p-6">
              <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-[color:var(--warning-soft)] text-[color:var(--warning)]">
                <AlertTriangle className="h-5 w-5" aria-hidden />
              </span>
              <h1 className="text-[19px] font-semibold tracking-[-0.015em] text-ink">
                {demoOff ? "Public demo switched off" : "The console could not start"}
              </h1>
              <p className="mt-1.5 text-[13px] leading-6 text-muted">
                {demoOff
                  ? "This deployment requires a signed-in account, and the console no longer ships a login form. Use the API directly, or browse the public portal below."
                  : "CivicLens opens without signing in, but it could not reach the API just now. The free-tier backend may still be waking up."}
              </p>

              {message ? (
                <p
                  className="mt-3 rounded-md border border-[color:var(--critical-border)] bg-[color:var(--critical-soft)] px-3 py-2 text-[12px] leading-5 text-[color:var(--critical)]"
                  role="alert"
                >
                  {message}
                </p>
              ) : null}

              {demoOff ? null : (
                <button
                  type="button"
                  className="btn btn-primary mt-5 w-full"
                  onClick={onRetry}
                  disabled={pending}
                >
                  {pending ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
                  {pending ? "Reconnecting…" : "Try again"}
                </button>
              )}

              <p className="mt-4 text-center text-[12px] text-muted">
                Or browse the{" "}
                <Link to="/public" className="link font-medium">
                  public transparency portal
                </Link>
                , which needs no session.
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

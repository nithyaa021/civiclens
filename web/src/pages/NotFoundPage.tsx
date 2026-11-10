import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { usePageTitle } from "../lib/usePageTitle";
import { Wordmark } from "../components/Wordmark";

export function NotFoundPage() {
  usePageTitle("Page not found");
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas px-6 text-center">
      <Wordmark />
      <span className="mt-8 flex h-11 w-11 items-center justify-center rounded-lg border border-line bg-surface text-muted">
        <Compass className="h-5 w-5" aria-hidden />
      </span>
      <p className="mt-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">404</p>
      <h1 className="mt-1 text-[20px] font-semibold text-ink">This page does not exist</h1>
      <p className="mt-1 max-w-sm text-[13px] leading-5 text-muted">
        The link may be outdated, or the record may have been removed from the municipal register.
      </p>
      <div className="mt-5 flex gap-2">
        <Link to="/" className="btn btn-primary btn-sm">
          Operations overview
        </Link>
        <Link to="/public" className="btn btn-secondary btn-sm">
          Public portal
        </Link>
      </div>
    </div>
  );
}

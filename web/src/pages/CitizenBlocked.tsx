import { Link, useNavigate } from "react-router-dom";
import { LogOut, Smartphone } from "lucide-react";
import { useAuth } from "../lib/auth";
import { usePageTitle } from "../lib/usePageTitle";
import { Wordmark } from "../components/Wordmark";

export function CitizenBlocked() {
  usePageTitle("Staff console");
  const { user, signOut } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas px-6">
      <div className="w-full max-w-md">
        <Wordmark />
        <div className="card mt-6 p-5">
          <span className="flex h-9 w-9 items-center justify-center rounded border border-line bg-raised text-muted">
            <Smartphone className="h-4 w-4" aria-hidden />
          </span>
          <h1 className="mt-3 text-[17px] font-semibold text-ink">This console is for municipal staff</h1>
          <p className="mt-1.5 text-[12px] leading-5 text-muted">
            Signed in as <span className="font-medium text-ink">{user?.full_name}</span> ({user?.email}),
            a citizen account. Citizen reports, votes and resolution decisions are handled in the
            CivicLens mobile app.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => void signOut().then(() => navigate("/login"))}
            >
              <LogOut className="h-3.5 w-3.5" aria-hidden />
              Sign out
            </button>
            <Link to="/public" className="btn btn-secondary btn-sm">
              Public transparency portal
            </Link>
          </div>
        </div>
        <p className="mt-4 text-[10px] leading-4 text-faint">
          Staff accounts are provisioned by city administrators. Contact your ward coordinator if you
          need access.
        </p>
      </div>
    </div>
  );
}

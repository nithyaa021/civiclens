import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Eye, EyeOff, KeyRound, MapPinned, Radar, ShieldCheck } from "lucide-react";
import { useAuth } from "../lib/auth";
import { usePageTitle } from "../lib/usePageTitle";
import { ApiError } from "../lib/api";
import { Wordmark } from "../components/Wordmark";
import { Spinner } from "../components/States";

const DEMO = [
  { role: "Administrator", email: "admin@civiclens.dev", password: "Admin#12345" },
  { role: "Ward officer", email: "officer12@civiclens.dev", password: "Officer#12345" },
  { role: "Citizen", email: "citizen1@civiclens.dev", password: "Citizen#12345" },
];

export function LoginPage() {
  usePageTitle("Sign in");
  const { status, user, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (status === "authenticated" && user) {
    return <Navigate to={user.role === "citizen" ? "/public" : "/"} replace />;
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const account = await signIn(email.trim(), password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(account.role === "citizen" ? "/public" : from && from.startsWith("/") ? from : "/", {
        replace: true,
      });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Sign-in failed. Check the API connection and try again.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="grid min-h-screen grid-cols-1 bg-canvas lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-[color:var(--sidebar)] p-10 lg:flex">
        <Wordmark inverse />
        <div className="max-w-md">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-[color:var(--sidebar-muted)]">
            Municipal operations console
          </p>
          <h1 className="mt-3 text-[30px] font-semibold leading-[1.2] tracking-[-0.025em] text-[color:var(--sidebar-ink)]">
            Complaint intelligence for the city service area.
          </h1>
          <p className="mt-3 text-[13px] leading-6 text-[color:var(--sidebar-muted)]">
            Triage live reports, dispatch ward crews, track service-level commitments and publish
            verified resolution data.
          </p>
          <ul className="mt-8 space-y-4 border-t border-white/10 pt-6">
            {[
              {
                icon: Radar,
                title: "Recurring issue detection",
                body: "Cluster reports by location and text to find repeat failures.",
              },
              {
                icon: MapPinned,
                title: "Ward-level accountability",
                body: "Every case is scoped to a ward and a named responsible officer.",
              },
              {
                icon: ShieldCheck,
                title: "Verified closures",
                body: "Before/after evidence and citizen confirmation gate resolution.",
              },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.title} className="flex gap-3">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded border border-white/10 bg-white/5 text-[color:var(--sidebar-ink)]">
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                  </span>
                  <span>
                    <span className="block text-[12px] font-medium text-[color:var(--sidebar-ink)]">
                      {item.title}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-5 text-[color:var(--sidebar-muted)]">
                      {item.body}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
        <p className="text-[10px] uppercase tracking-[0.08em] text-[color:var(--sidebar-muted)]">
          Bengaluru · CivicLens authority console
        </p>
      </aside>

      <main className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 lg:hidden">
            <Wordmark />
          </div>
          <h2 className="text-[22px] font-semibold tracking-[-0.02em] text-ink">Sign in</h2>
          <p className="mt-1 text-[13px] text-muted">
            Use your municipal account to open the operations console.
          </p>

          <form className="mt-6 space-y-3" onSubmit={(event) => void submit(event)}>
            <div>
              <label htmlFor="email" className="label">
                Work email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                required
                className="field"
                placeholder="name@civiclens.dev"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="password" className="label">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  className="field pr-10"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
                <button
                  type="button"
                  className="absolute right-0 top-0 flex h-[34px] w-9 items-center justify-center text-faint hover:text-ink"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
                </button>
              </div>
            </div>

            {error ? (
              <p
                className="rounded border border-[color:var(--critical-border)] bg-[color:var(--critical-soft)] px-2.5 py-2 text-[12px] leading-5 text-[color:var(--critical)]"
                role="alert"
              >
                {error}
              </p>
            ) : null}

            <button type="submit" className="btn btn-primary h-9 w-full" disabled={pending}>
              {pending ? <Spinner /> : <KeyRound className="h-4 w-4" aria-hidden />}
              {pending ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-4 text-[11px] leading-5 text-muted">
            Citizen accounts use the CivicLens mobile app.{" "}
            <Link to="/public" className="link">
              View the public transparency portal
            </Link>
            .
          </p>

          <div className="mt-8 border-t border-line pt-4">
            <p className="eyebrow mb-2">Development environment</p>
            <div className="space-y-1.5">
              {DEMO.map((account) => (
                <div
                  key={account.email}
                  className="flex items-center gap-2 rounded border border-line bg-surface px-2.5 py-1.5"
                >
                  <span className="w-[86px] shrink-0 text-[10px] font-medium uppercase tracking-[0.04em] text-faint">
                    {account.role}
                  </span>
                  <span className="tabular min-w-0 flex-1 truncate text-[11px] text-muted">
                    {account.email}
                  </span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm shrink-0"
                    onClick={() => {
                      setEmail(account.email);
                      setPassword(account.password);
                      setError(null);
                    }}
                  >
                    Use
                  </button>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[10px] leading-4 text-faint">
              Seeded accounts for local evaluation only. Passwords are documented in the project
              README.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

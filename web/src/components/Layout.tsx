import { NavLink, Outlet, useLocation } from "react-router-dom";
import { clsx } from "clsx";
import {
  BookOpenText,
  ChevronRight,
  ClipboardList,
  ExternalLink,
  LayoutDashboard,
  Map,
  MessageSquareText,
  Moon,
  Radar,
  Sun,
} from "lucide-react";
import { apiDocsUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/themeContext";
import { PerspectiveSwitcher } from "./PerspectiveSwitcher";
import { Wordmark } from "./Wordmark";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true, staffOnly: true },
  { to: "/queue", label: "Complaint queue", icon: ClipboardList },
  { to: "/map", label: "City map", icon: Map, staffOnly: true },
  { to: "/recurring", label: "Recurring issues", icon: Radar, staffOnly: true },
  { to: "/assistant", label: "Operations assistant", icon: MessageSquareText, staffOnly: true },
];

const TITLES: Record<string, string> = {
  "/": "Overview",
  "/queue": "Complaint queue",
  "/map": "City map",
  "/recurring": "Recurring issues",
  "/assistant": "Operations assistant",
};

export function AppShell() {
  const { user, perspective } = useAuth();
  const location = useLocation();
  const { theme, toggle } = useTheme();

  // Citizens see their own reports; the analytics views are staff-only and
  // would return 403, so they are not offered rather than shown as dead links.
  const isCitizen = user?.role === "citizen";
  const items = NAV.filter((item) => !isCitizen || !item.staffOnly);

  const rootPath = `/${location.pathname.split("/")[1] ?? ""}`;
  const isDetail = location.pathname.startsWith("/queue/");
  const isWardScope = perspective?.startsWith("ward-") ?? false;
  const section = isCitizen
    ? isDetail
      ? "Case detail"
      : "My complaints"
    : (TITLES[rootPath] ??
      (isDetail ? "Complaint detail" : "CivicLens"));

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[1100] focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-[13px] focus:shadow-pop"
      >
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 z-40 flex w-[68px] flex-col border-r border-[color:var(--sidebar-line)] bg-[color:var(--sidebar)] lg:w-[236px]">
        <div className="flex h-16 items-center px-[19px] lg:px-5">
          <span className="lg:hidden">
            <Wordmark compact inverse />
          </span>
          <span className="hidden lg:block">
            <Wordmark inverse />
          </span>
        </div>

        <nav className="mt-1 flex-1 space-y-1 px-2.5" aria-label="Main navigation">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    "group relative flex h-10 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium transition-all",
                    isActive
                      ? "bg-[color:var(--sidebar-active)] text-[color:var(--sidebar-ink)] shadow-[inset_0_1px_0_rgb(255_255_255/0.07)]"
                      : "text-[color:var(--sidebar-muted)] hover:bg-[color:var(--sidebar-hover)] hover:text-[color:var(--sidebar-ink)]",
                  )
                }
                title={item.label}
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={clsx(
                        "absolute inset-y-1.5 left-0 w-1 rounded-r-full transition-opacity",
                        isActive ? "opacity-100" : "opacity-0",
                      )}
                      style={{
                        background: "linear-gradient(180deg, var(--aurora-1), var(--aurora-2))",
                      }}
                      aria-hidden
                    />
                    <span
                      className={clsx(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors",
                        isActive
                          ? "bg-white/10 text-[color:var(--aurora-2)]"
                          : "text-[color:var(--sidebar-muted)] group-hover:text-[color:var(--sidebar-ink)]",
                      )}
                      aria-hidden
                    >
                      <Icon className="h-[17px] w-[17px]" />
                    </span>
                    <span className="hidden truncate lg:block">
                    {isCitizen && item.to === "/queue" ? "My complaints" : item.label}
                  </span>
                  </>
                )}
              </NavLink>
            );
          })}

          <div className="my-2.5 border-t border-[color:var(--sidebar-line)]" />

          <a
            href="/public"
            target="_blank"
            rel="noreferrer"
            className="group flex h-10 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium text-[color:var(--sidebar-muted)] transition-colors hover:bg-[color:var(--sidebar-hover)] hover:text-[color:var(--sidebar-ink)]"
            title="Public transparency portal"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center" aria-hidden>
              <ExternalLink className="h-[17px] w-[17px]" />
            </span>
            <span className="hidden truncate lg:block">Public portal</span>
          </a>
          <a
            href={apiDocsUrl}
            target="_blank"
            rel="noreferrer"
            className="group flex h-10 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium text-[color:var(--sidebar-muted)] transition-colors hover:bg-[color:var(--sidebar-hover)] hover:text-[color:var(--sidebar-ink)]"
            title="API reference (OpenAPI)"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center" aria-hidden>
              <BookOpenText className="h-[17px] w-[17px]" />
            </span>
            <span className="hidden truncate lg:block">API reference</span>
          </a>
        </nav>

        <div className="hidden border-t border-[color:var(--sidebar-line)] p-3 lg:block">
          <div
            className="rounded-lg p-3"
            style={{
              background:
                "linear-gradient(140deg, color-mix(in srgb, var(--aurora-1) 22%, transparent), color-mix(in srgb, var(--aurora-2) 16%, transparent))",
            }}
          >
            <p className="text-[11px] font-semibold text-[color:var(--sidebar-ink)]">
              Open demo
            </p>
            <p className="mt-1 text-[10.5px] leading-4 text-[color:var(--sidebar-muted)]">
              {user?.full_name ?? "Demo session"} · no password, no sign-up.
            </p>
          </div>
        </div>
      </aside>

      <div className="pl-[68px] lg:pl-[236px]">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 border-b border-line bg-surface/90 px-3 backdrop-blur-md sm:px-6">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[12px]">
            <span className="hidden text-faint sm:inline">Operations</span>
            <ChevronRight className="hidden h-3 w-3 text-line-strong sm:inline" aria-hidden />
            {isDetail ? (
              <NavLink to="/queue" className="text-muted hover:text-ink">
                {isCitizen ? "My complaints" : "Complaint queue"}
              </NavLink>
            ) : null}
            {isDetail ? <ChevronRight className="h-3 w-3 text-line-strong" aria-hidden /> : null}
            <span className="truncate font-semibold text-ink">{section}</span>
          </nav>

          <div className="flex shrink-0 items-center gap-2">
            <span
              className={clsx(
                "hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium md:inline-flex",
                isWardScope
                  ? "border-[color:var(--info-border)] bg-[color:var(--info-soft)] text-[color:var(--info)]"
                  : "border-[color:var(--positive-border)] bg-[color:var(--positive-soft)] text-[color:var(--positive)]",
              )}
            >
              <span
                className={clsx(
                  "h-1.5 w-1.5 rounded-full",
                  isWardScope ? "bg-[color:var(--info)]" : "bg-[color:var(--positive)]",
                )}
                aria-hidden
              />
              {isWardScope ? `Ward ${user?.ward ?? "—"} scope` : "All wards · Bengaluru"}
            </span>
            <button
              type="button"
              onClick={toggle}
              className="btn btn-ghost h-9 w-9 rounded-full px-0"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {theme === "dark" ? (
                <Sun className="h-[18px] w-[18px]" aria-hidden />
              ) : (
                <Moon className="h-[18px] w-[18px]" aria-hidden />
              )}
            </button>
            <PerspectiveSwitcher />
          </div>
        </header>

        <main id="main" className="px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

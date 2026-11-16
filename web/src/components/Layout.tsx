import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import {
  BookOpenText,
  ChevronRight,
  ClipboardList,
  ExternalLink,
  LayoutDashboard,
  LogOut,
  Map,
  MessageSquareText,
  Moon,
  Radar,
  Sun,
  UserRound,
} from "lucide-react";
import { apiDocsUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/themeContext";
import { Wordmark } from "./Wordmark";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/queue", label: "Complaint queue", icon: ClipboardList },
  { to: "/map", label: "City map", icon: Map },
  { to: "/recurring", label: "Recurring issues", icon: Radar },
  { to: "/assistant", label: "Operations assistant", icon: MessageSquareText },
];

const TITLES: Record<string, string> = {
  "/": "Overview",
  "/queue": "Complaint queue",
  "/map": "City map",
  "/recurring": "Recurring issues",
  "/assistant": "Operations assistant",
};

export function AppShell() {
  const { user, signOut } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();

  const rootPath = `/${location.pathname.split("/")[1] ?? ""}`;
  const section = TITLES[rootPath] ?? (location.pathname.startsWith("/queue") ? "Complaint detail" : "CivicLens");
  const isDetail = location.pathname.startsWith("/queue/");

  const initials = (user?.full_name ?? "?")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[1100] focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-[13px] focus:shadow-pop"
      >
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 z-40 flex w-[64px] flex-col border-r border-[color:var(--sidebar-active)] bg-[color:var(--sidebar)] lg:w-[228px]">
        <div className="flex h-14 items-center px-[18px] lg:px-5">
          <span className="lg:hidden">
            <Wordmark compact inverse />
          </span>
          <span className="hidden lg:block">
            <Wordmark inverse />
          </span>
        </div>

        <nav className="mt-3 flex-1 space-y-0.5 px-2.5" aria-label="Main navigation">
          {NAV.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    "group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
                    isActive
                      ? "bg-[color:var(--sidebar-active)] text-white"
                      : "text-[color:var(--sidebar-muted)] hover:bg-white/5 hover:text-[color:var(--sidebar-ink)]",
                  )
                }
                title={item.label}
              >
                <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
                <span className="hidden truncate lg:block">{item.label}</span>
              </NavLink>
            );
          })}

          <div className="my-2 border-t border-white/10" />

          <a
            href="/public"
            target="_blank"
            rel="noreferrer"
            className="group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium text-[color:var(--sidebar-muted)] transition-colors hover:bg-white/5 hover:text-[color:var(--sidebar-ink)]"
            title="Public transparency portal"
          >
            <ExternalLink className="h-[18px] w-[18px] shrink-0" aria-hidden />
            <span className="hidden truncate lg:block">Public portal</span>
          </a>
          <a
            href={apiDocsUrl}
            target="_blank"
            rel="noreferrer"
            className="group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium text-[color:var(--sidebar-muted)] transition-colors hover:bg-white/5 hover:text-[color:var(--sidebar-ink)]"
            title="API reference (OpenAPI)"
          >
            <BookOpenText className="h-[18px] w-[18px] shrink-0" aria-hidden />
            <span className="hidden truncate lg:block">API reference</span>
          </a>
        </nav>

        <div className="border-t border-white/10 p-2.5">
          <div className="flex items-center gap-2.5 rounded-md px-1 py-1.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[color:var(--sidebar-active)] text-[11px] font-semibold text-[color:var(--sidebar-ink)]">
              {initials || <UserRound className="h-4 w-4" aria-hidden />}
            </span>
            <div className="hidden min-w-0 flex-1 lg:block">
              <p className="truncate text-[12px] font-medium text-[color:var(--sidebar-ink)]">
                {user?.full_name}
              </p>
              <p className="truncate text-[10px] uppercase tracking-[0.06em] text-[color:var(--sidebar-muted)]">
                {user?.role === "admin" ? "City administrator" : `Ward ${user?.ward ?? "—"} officer`}
              </p>
            </div>
            <button
              type="button"
              className="hidden h-7 w-7 items-center justify-center rounded text-[color:var(--sidebar-muted)] hover:bg-white/10 hover:text-white lg:flex"
              onClick={() => void signOut().then(() => navigate("/login"))}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
      </aside>

      <div className="pl-[64px] lg:pl-[228px]">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b border-line bg-surface/95 px-4 backdrop-blur-sm sm:px-6">
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[12px]">
            <span className="hidden text-faint sm:inline">Operations</span>
            <ChevronRight className="hidden h-3 w-3 text-line-strong sm:inline" aria-hidden />
            {isDetail ? (
              <NavLink to="/queue" className="text-muted hover:text-ink">
                Complaint queue
              </NavLink>
            ) : null}
            {isDetail ? <ChevronRight className="h-3 w-3 text-line-strong" aria-hidden /> : null}
            <span className="truncate font-medium text-ink">{section}</span>
          </nav>

          <div className="flex shrink-0 items-center gap-1.5">
            <span className="mr-1 hidden items-center gap-1.5 rounded border border-line bg-raised px-2 py-1 text-[11px] text-muted sm:inline-flex">
              <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--positive)]" aria-hidden />
              {user?.role === "admin" ? "All wards · Bengaluru" : `Ward ${user?.ward} scope`}
            </span>
            <button
              type="button"
              onClick={toggle}
              className="btn btn-ghost h-8 w-8 px-0"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" aria-hidden />
              ) : (
                <Moon className="h-4 w-4" aria-hidden />
              )}
            </button>
            <button
              type="button"
              onClick={() => void signOut().then(() => navigate("/login"))}
              className="btn btn-ghost h-8 w-8 px-0 lg:hidden"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </header>

        <main id="main" className="px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

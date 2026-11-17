import { lazy, Suspense, useMemo, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { ThemeProvider } from "./lib/themeContext";
import { AppShell } from "./components/Layout";
import { Spinner } from "./components/States";
import { Skeleton, SkeletonLines } from "./components/Skeleton";
import { Wordmark } from "./components/Wordmark";
import { ConnectionFailed } from "./pages/ConnectionFailed";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PublicPage } from "./pages/PublicPage";

// Views are code-split: the shell and transparency portal stay in the initial
// bundle, while charts, the map and the assistant load on demand.
const OverviewPage = lazy(() =>
  import("./pages/OverviewPage").then((module) => ({ default: module.OverviewPage })),
);
const QueuePage = lazy(() =>
  import("./pages/QueuePage").then((module) => ({ default: module.QueuePage })),
);
const ComplaintDetailPage = lazy(() =>
  import("./pages/ComplaintDetailPage").then((module) => ({ default: module.ComplaintDetailPage })),
);
const MapPage = lazy(() =>
  import("./pages/MapPage").then((module) => ({ default: module.MapPage })),
);
const RecurringPage = lazy(() =>
  import("./pages/RecurringPage").then((module) => ({ default: module.RecurringPage })),
);
const AssistantPage = lazy(() =>
  import("./pages/AssistantPage").then((module) => ({ default: module.AssistantPage })),
);

/**
 * One cache per open perspective. Ward scoping, citizen redaction and audit
 * visibility are all decided server-side, so reusing another view's cache would
 * briefly show the wrong numbers - and offer actions the new role cannot take.
 * Rebuilding the client on identity change drops every stale entry at once.
 */
function ConsoleQueries({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const client = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
    [user?.id],
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function LoadingScreen() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-canvas">
      <Wordmark />
      <span className="flex items-center gap-2 text-[12px] text-muted" role="status">
        <Spinner />
        Opening CivicLens…
      </span>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-4" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading view</span>
      <div className="space-y-2 border-b border-line pb-4">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-3 w-96 max-w-full" />
      </div>
      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="bg-surface p-4">
            <Skeleton className="mb-3 h-3 w-24" />
            <Skeleton className="mb-3 h-7 w-16" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="card p-4 xl:col-span-2">
          <Skeleton className="mb-4 h-3 w-40" />
          <Skeleton className="h-[240px] w-full" />
        </div>
        <div className="card p-4">
          <Skeleton className="mb-4 h-3 w-28" />
          <SkeletonLines lines={8} />
        </div>
      </div>
    </div>
  );
}

/**
 * Opens the console for everyone. There is no login wall: the app silently
 * enters a seeded demo perspective, and visitors switch views from the header.
 * This only fails when the API itself is unreachable.
 */
function OpenConsole() {
  const { status, error, retry } = useAuth();

  if (status === "loading") return <LoadingScreen />;
  if (status === "anonymous") return <ConnectionFailed message={error} onRetry={() => void retry()} />;
  return <Outlet />;
}

/** Citizens have no city-wide analytics, so the index sends them to their reports. */
function OverviewIndex() {
  const { user } = useAuth();
  if (user?.role === "citizen") return <Navigate to="/queue" replace />;
  return <OverviewPage />;
}

export function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ConsoleQueries>
          <BrowserRouter>
            <Suspense fallback={<PageSkeleton />}>
              <Routes>
                <Route path="/public" element={<PublicPage />} />
                <Route element={<OpenConsole />}>
                  <Route element={<AppShell />}>
                    <Route index element={<OverviewIndex />} />
                    <Route path="queue" element={<QueuePage />} />
                    <Route path="queue/:id" element={<ComplaintDetailPage />} />
                    <Route path="map" element={<MapPage />} />
                    <Route path="recurring" element={<RecurringPage />} />
                    <Route path="assistant" element={<AssistantPage />} />
                  </Route>
                </Route>
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </ConsoleQueries>
      </AuthProvider>
    </ThemeProvider>
  );
}

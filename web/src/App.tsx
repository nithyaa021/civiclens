import { lazy, Suspense } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { ThemeProvider } from "./lib/themeContext";
import { AppShell } from "./components/Layout";
import { Spinner } from "./components/States";
import { Skeleton, SkeletonLines } from "./components/Skeleton";
import { Wordmark } from "./components/Wordmark";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PublicPage } from "./pages/PublicPage";

// Staff screens are code-split: the public portal and sign-in stay in the
// initial bundle for anonymous visitors, while charts and map code load on use.
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
const CitizenBlocked = lazy(() =>
  import("./pages/CitizenBlocked").then((module) => ({ default: module.CitizenBlocked })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function LoadingScreen() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-canvas">
      <Wordmark />
      <span className="flex items-center gap-2 text-[12px] text-muted" role="status">
        <Spinner />
        Verifying session…
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

function RequireStaff() {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === "loading") return <LoadingScreen />;
  if (status === "anonymous" || !user) {
    return <Navigate to="/login" state={{ from: `${location.pathname}${location.search}` }} replace />;
  }
  if (user.role === "citizen") return <CitizenBlocked />;
  return <Outlet />;
}

export function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Suspense fallback={<PageSkeleton />}>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/public" element={<PublicPage />} />
                <Route element={<RequireStaff />}>
                  <Route element={<AppShell />}>
                    <Route index element={<OverviewPage />} />
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
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, authStore, type DemoPerspective } from "./api";
import type { User } from "./types";

type AuthStatus = "loading" | "anonymous" | "authenticated";

const PERSPECTIVE_KEY = "civiclens.perspective";

function readPerspective(): string | null {
  try {
    return window.localStorage.getItem(PERSPECTIVE_KEY);
  } catch {
    return null;
  }
}

function writePerspective(id: string): void {
  try {
    window.localStorage.setItem(PERSPECTIVE_KEY, id);
  } catch {
    // Session-only fallback is fine.
  }
}

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  /** Why the automatic demo session failed, if it did. */
  error: string | null;
  /** Perspectives offered by the deployment (empty when the demo is off). */
  perspectives: DemoPerspective[];
  /** Id of the open perspective, e.g. "admin" or "ward-12". */
  perspective: string | null;
  demoEnabled: boolean;
  /** Switch the console to another perspective. */
  choose: (id: string) => Promise<void>;
  /** Re-open the current perspective after a failure. */
  retry: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [perspectives, setPerspectives] = useState<DemoPerspective[]>([]);
  const [demoEnabled, setDemoEnabled] = useState(true);
  const [perspective, setPerspective] = useState<string | null>(readPerspective);
  const perspectiveRef = useRef(perspective);
  perspectiveRef.current = perspective;

  /** Open `id`, falling back to the deployment default, then to credentials. */
  const open = useCallback(async (id: string | null) => {
    setError(null);
    try {
      const directory = await api.demoPerspectives();
      setDemoEnabled(directory.enabled);
      setPerspectives(directory.perspectives);

      if (!directory.enabled) {
        // The deployment turned DEMO_MODE off, so the console deliberately has
        // no session to open. Say so, rather than blaming a sleeping backend.
        setStatus(authStore.get() ? "loading" : "anonymous");
        setError(
          "This deployment has the public demo switched off, so the console needs a signed-in account.",
        );
        return;
      }

      const wanted = id && directory.perspectives.some((item) => item.id === id) ? id : directory.default;
      if (!wanted) {
        setStatus("anonymous");
        setError("No demo perspectives are configured for this deployment.");
        return;
      }

      const pair = await api.openDemoSession(wanted);
      writePerspective(wanted);
      setPerspective(wanted);
      setUser(pair.user ?? (await api.me()).user);
      setStatus("authenticated");
    } catch (cause) {
      setUser(null);
      setStatus("anonymous");
      setError(
        cause instanceof Error
          ? cause.message
          : "The console could not open a session. Check the API connection and try again.",
      );
    }
  }, []);

  // Open a session on first load, and whenever an existing token is cleared
  // (e.g. an admin revoked it) so the console never shows a dead screen.
  useEffect(() => {
    if (authStore.get()) {
      // A stored token may still be valid; verify before opening a new session.
      let cancelled = false;
      api
        .me()
        .then((me) => {
          if (cancelled) return;
          setUser(me.user);
          setStatus("authenticated");
          // Refresh the perspective list for the switcher itself.
          void api
            .demoPerspectives()
            .then((directory) => {
              if (cancelled) return;
              setDemoEnabled(directory.enabled);
              setPerspectives(directory.perspectives);
            })
            .catch(() => undefined);
        })
        .catch(() => {
          if (cancelled) return;
          authStore.set(null);
          void open(perspectiveRef.current);
        });
      return () => {
        cancelled = true;
      };
    }
    void open(perspectiveRef.current);
    return undefined;
  }, [open]);

  const choose = useCallback(
    async (id: string) => {
      if (id === perspectiveRef.current) return;
      setStatus("loading");
      await open(id);
    },
    [open],
  );

  const retry = useCallback(async () => {
    setStatus("loading");
    await open(perspectiveRef.current);
  }, [open]);

  const value = useMemo(
    () => ({
      user,
      status,
      error,
      perspectives,
      perspective,
      demoEnabled,
      choose,
      retry,
    }),
    [user, status, error, perspectives, perspective, demoEnabled, choose, retry],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

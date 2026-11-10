import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, authStore } from "./api";
import type { User } from "./types";

type AuthStatus = "loading" | "anonymous" | "authenticated";

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  signIn: (email: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>(() =>
    authStore.get() ? "loading" : "anonymous",
  );

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      if (!authStore.get()) {
        setStatus("anonymous");
        return;
      }
      try {
        const me = await api.me();
        if (cancelled) return;
        setUser(me.user);
        setStatus("authenticated");
      } catch {
        if (cancelled) return;
        authStore.set(null);
        setUser(null);
        setStatus("anonymous");
      }
    }

    void bootstrap();
    const unsubscribe = authStore.subscribe((next) => {
      if (!next) {
        setUser(null);
        setStatus("anonymous");
      }
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    await api.login(email, password);
    const me = await api.me();
    setUser(me.user);
    setStatus("authenticated");
    return me.user;
  }, []);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo(
    () => ({ user, status, signIn, signOut }),
    [user, status, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

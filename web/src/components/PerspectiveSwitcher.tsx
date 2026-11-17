import { useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  Check,
  ChevronDown,
  MapPin,
  MessageSquare,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { clsx } from "clsx";
import { useAuth } from "../lib/auth";
import type { DemoPerspective } from "../lib/api";
import type { Role } from "../lib/types";

const ROLE_ICON: Record<Role, typeof Building2> = {
  admin: ShieldCheck,
  ward_officer: MapPin,
  citizen: UserRound,
};

const ROLE_GROUP: Record<Role, { title: string; hint: string }> = {
  admin: { title: "City-wide", hint: "Every ward, all analytics and bulk actions" },
  ward_officer: { title: "By ward", hint: "Scoped to a single ward's queue and map" },
  citizen: { title: "As a citizen", hint: "Reporter view and resolution confirmation" },
};

const GROUP_ORDER: Role[] = ["admin", "ward_officer", "citizen"];

/**
 * Lets a visitor pick which view of the city they are looking at. This replaces
 * the old login form: switching here swaps the underlying demo perspective, so
 * role scoping, permissions and the audit trail all behave as in production.
 */
export function PerspectiveSwitcher() {
  const { perspective, perspectives, choose, user, status } = useAuth();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const current = perspectives.find((item) => item.id === perspective);

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matches = perspectives.filter(
      (item) => !needle || item.label.toLowerCase().includes(needle),
    );
    return GROUP_ORDER.map((role) => ({
      role,
      items: matches.filter((item) => item.role === role),
    })).filter((group) => group.items.length > 0);
  }, [perspectives, query]);

  const total = grouped.reduce((sum, group) => sum + group.items.length, 0);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  if (perspectives.length === 0) return null;

  const label = current?.label ?? (user?.role === "admin" ? "City-wide" : "Current view");
  const Icon = current ? ROLE_ICON[current.role] : Building2;

  const pick = async (item: DemoPerspective) => {
    if (item.id === perspective) {
      setOpen(false);
      return;
    }
    setPending(item.id);
    try {
      await choose(item.id);
      setOpen(false);
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="relative" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={clsx(
          "flex h-9 items-center gap-2 rounded-full border border-line bg-surface pl-1.5 pr-2.5 text-left transition-colors hover:border-[color:var(--primary)]",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--primary)]",
        )}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={status === "loading"}
      >
        <span
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[color:var(--on-primary)]"
          style={{ background: "var(--primary)" }}
          aria-hidden
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="flex min-w-0 flex-col leading-none">
          <span className="hidden text-[9px] font-semibold uppercase tracking-[0.09em] text-faint sm:block">
            Viewing as
          </span>
          <span className="mt-0 max-w-[132px] truncate text-[12px] font-semibold text-ink sm:mt-0.5 sm:max-w-[190px]">
            {label}
          </span>
        </span>
        <span className="sr-only">Change view</span>
        <ChevronDown
          className={clsx("h-3.5 w-3.5 shrink-0 text-faint transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="Choose a view"
          className="absolute right-0 z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-line bg-surface shadow-pop"
        >
          <div className="border-b border-line px-3.5 py-3">
            <p className="text-[13px] font-semibold text-ink">Choose what you want to see</p>
            <p className="mt-0.5 text-[11px] leading-4 text-muted">
              Every view is open. Switching changes the scope and permissions, not just the filters.
            </p>
          </div>

          {perspectives.length > 8 ? (
            <div className="border-b border-line px-3 py-2">
              <label htmlFor="perspective-search" className="sr-only">
                Search views
              </label>
              <input
                id="perspective-search"
                type="search"
                className="field h-8 text-[12px]"
                placeholder="Search wards…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                autoComplete="off"
              />
            </div>
          ) : null}

          <div className="max-h-[min(60vh,26rem)] overflow-y-auto p-1.5">
            {total === 0 ? (
              <p className="px-3 py-6 text-center text-[12px] text-muted">
                No view matches “{query.trim()}”.
              </p>
            ) : (
              grouped.map((group) => {
                const meta = ROLE_GROUP[group.role];
                return (
                  <div key={group.role} className="mb-1 last:mb-0">
                    <p className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-[0.09em] text-faint">
                      {meta.title}
                    </p>
                    {group.items.map((item) => {
                      const ItemIcon = ROLE_ICON[item.role];
                      const active = item.id === perspective;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => void pick(item)}
                          disabled={pending !== null}
                          className={clsx(
                            "flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left transition-colors",
                            active
                              ? "bg-[color:var(--primary-soft)]"
                              : "hover:bg-raised disabled:opacity-60",
                          )}
                          aria-current={active ? "true" : undefined}
                        >
                          <span
                            className={clsx(
                              "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
                              active
                                ? "bg-[color:var(--primary)] text-[color:var(--on-primary)]"
                                : "bg-raised text-muted",
                            )}
                            aria-hidden
                          >
                            <ItemIcon className="h-3.5 w-3.5" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[12.5px] font-medium text-ink">
                              {item.label}
                            </span>
                            <span className="mt-0.5 block text-[11px] leading-4 text-muted">
                              {item.description}
                            </span>
                          </span>
                          {active ? (
                            <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-[color:var(--primary)]" aria-hidden />
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                );
              })
            )}
          </div>

          <div className="flex items-center gap-1.5 border-t border-line bg-raised px-3.5 py-2 text-[10.5px] text-muted">
            <MessageSquare className="h-3 w-3 shrink-0" aria-hidden />
            Seeded demo data. No account or password needed.
          </div>
        </div>
      ) : null}
    </div>
  );
}

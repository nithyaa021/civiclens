import { Link } from "react-router-dom";
import { clsx } from "clsx";

export function Wordmark({ compact = false, inverse = false }: { compact?: boolean; inverse?: boolean }) {
  return (
    <Link
      to="/"
      className={clsx("inline-flex items-center gap-2.5 rounded", inverse && "text-[color:var(--sidebar-ink)]")}
    >
      <span
        className={clsx(
          "flex h-7 w-7 items-center justify-center rounded-[7px]",
          inverse ? "bg-white/12" : "bg-primary",
        )}
        aria-hidden
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none">
          <path
            d="M5 6.5h8.1a4.4 4.4 0 0 1 0 8.8H5V6.5Z"
            stroke={inverse ? "#dbe7ea" : "var(--on-primary)"}
            strokeWidth="1.9"
            strokeLinejoin="round"
          />
          <path
            d="M5 11h7"
            stroke={inverse ? "#9fd0d8" : "var(--primary-soft)"}
            strokeWidth="1.9"
            strokeLinecap="round"
          />
          <circle cx="18.2" cy="16.4" r="2" fill={inverse ? "#9fd0d8" : "var(--primary-soft)"} />
        </svg>
      </span>
      {!compact ? (
        <span className="flex flex-col leading-none">
          <span className="text-[15px] font-semibold tracking-[-0.02em]">CivicLens</span>
          <span
            className={clsx(
              "mt-0.5 text-[10px] font-medium uppercase tracking-[0.1em]",
              inverse ? "text-[color:var(--sidebar-muted)]" : "text-faint",
            )}
          >
            Municipal operations
          </span>
        </span>
      ) : (
        <span className="sr-only">CivicLens</span>
      )}
    </Link>
  );
}

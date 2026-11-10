import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { clsx } from "clsx";

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && panelRef.current) {
        const focusables = panelRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const timer = window.setTimeout(() => {
      panelRef.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    }, 20);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(timer);
      previous?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-end justify-center p-0 sm:items-center sm:p-6"
      style={{ background: "var(--overlay)" }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx(
          "max-h-[92vh] w-full overflow-y-auto rounded-t-lg border border-line bg-surface shadow-pop sm:rounded-lg",
          width,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
            {description ? (
              <p className="mt-1 text-[12px] leading-5 text-muted">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            className="btn btn-ghost -mr-2 -mt-1 h-8 w-8 px-0"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer ? (
          <div className="flex justify-end gap-2 border-t border-line bg-raised px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { ImageOff } from "lucide-react";
import { clsx } from "clsx";
import { fetchMedia } from "../lib/api";
import { Skeleton } from "./Skeleton";
import { Dialog } from "./Dialog";
import type { Attachment } from "../lib/types";

export function AuthImage({
  mediaId,
  alt,
  className,
}: {
  mediaId: string;
  alt: string;
  className?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    fetchMedia(mediaId)
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [mediaId]);

  if (failed) {
    return (
      <div
        className={clsx(
          "flex flex-col items-center justify-center gap-1 bg-raised text-faint",
          className,
        )}
        role="img"
        aria-label={`${alt} — image unavailable`}
      >
        <ImageOff className="h-4 w-4" aria-hidden />
        <span className="text-[10px]">Unavailable</span>
      </div>
    );
  }

  if (!url) return <Skeleton className={clsx("h-full w-full", className)} />;

  return <img src={url} alt={alt} className={clsx("object-cover", className)} loading="lazy" />;
}

const KIND_LABEL: Record<Attachment["kind"], string> = {
  before: "Before",
  after: "After",
  general: "Attachment",
};

export function PhotoGallery({ attachments }: { attachments: Attachment[] }) {
  const [active, setActive] = useState<Attachment | null>(null);

  if (attachments.length === 0) {
    return (
      <p className="rounded border border-dashed border-line-strong px-3 py-6 text-center text-[12px] text-muted">
        No photos were submitted with this report.
      </p>
    );
  }

  return (
    <>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {attachments.map((attachment) => (
          <li key={attachment.id}>
            <button
              type="button"
              className="group relative block aspect-[4/3] w-full overflow-hidden rounded border border-line bg-raised"
              onClick={() => setActive(attachment)}
            >
              <AuthImage
                mediaId={attachment.id}
                alt={`${KIND_LABEL[attachment.kind]} evidence photo`}
                className="h-full w-full transition-transform duration-200 group-hover:scale-[1.02]"
              />
              <span className="absolute left-1.5 top-1.5 rounded bg-surface/90 px-1.5 py-0.5 text-[10px] font-medium text-muted backdrop-blur-sm">
                {KIND_LABEL[attachment.kind]}
              </span>
            </button>
          </li>
        ))}
      </ul>

      <Dialog
        open={active !== null}
        onClose={() => setActive(null)}
        title={active ? `${KIND_LABEL[active.kind]} photo` : "Photo"}
        description={active ? `Stored ${active.content_type} · uploaded ${new Date(active.created_at).toLocaleString()}` : undefined}
        width="max-w-3xl"
      >
        {active ? (
          <div className="overflow-hidden rounded border border-line bg-raised">
            <AuthImage
              mediaId={active.id}
              alt={`${KIND_LABEL[active.kind]} evidence photo, enlarged`}
              className="max-h-[70vh] w-full object-contain"
            />
          </div>
        ) : null}
      </Dialog>
    </>
  );
}

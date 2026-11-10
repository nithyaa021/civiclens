import { useEffect } from "react";

export function usePageTitle(title: string): void {
  useEffect(() => {
    const previous = document.title;
    document.title = title.includes("CivicLens") ? title : `${title} — CivicLens`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}

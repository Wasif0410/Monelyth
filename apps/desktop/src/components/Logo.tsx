import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The app mark, the same drawing as the app icon (src-tauri/icons/source/app-icon.svg): an "M"
 * whose last stroke climbs higher than the first. Size it with `className` (e.g. `size-8`).
 */
export function Logo({ className }: { className?: string }) {
  // Gradient ids must be unique when several logos are on screen at once.
  const id = useId();
  const tile = `${id}-tile`;
  const shine = `${id}-shine`;
  return (
    <svg
      aria-hidden="true"
      viewBox="64 64 896 896"
      className={cn("shrink-0 drop-shadow-sm", className)}
    >
      <defs>
        <linearGradient id={tile} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#14a676" />
          <stop offset="1" stopColor="#0b7553" />
        </linearGradient>
        <linearGradient id={shine} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.18" />
          <stop offset="0.5" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect x="64" y="64" width="896" height="896" rx="208" fill={`url(#${tile})`} />
      <rect x="64" y="64" width="896" height="896" rx="208" fill={`url(#${shine})`} />
      <path
        d="M262 728 V430 L494 640 L762 268 V728"
        fill="none"
        stroke="#ffffff"
        strokeWidth="104"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

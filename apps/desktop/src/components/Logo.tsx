import { cn } from "@/lib/utils";

/** The app mark. Size it with `className` (e.g. `size-8 text-sm`). */
export function Logo({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "bg-primary text-primary-foreground flex shrink-0 items-center justify-center rounded-[28%] font-semibold shadow-sm",
        className,
      )}
    >
      M
    </div>
  );
}

import type { UseMutationResult } from "@tanstack/react-query";
import { ChevronRight, Compass, FileUp, LoaderCircle, type LucideIcon } from "lucide-react";
import { useId } from "react";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { CurrencyCode } from "@/screens/onboarding/currencies";
import { CurrencySelect } from "@/screens/onboarding/CurrencySelect";
import { InlineError } from "@/screens/onboarding/InlineError";
import type { DemoResult } from "@/screens/onboarding/useAddDemoData";

interface StartChoicesProps {
  currency: CurrencyCode;
  onCurrencyChange: (currency: CurrencyCode) => void;
  /** The demo-data mutation, for its progress and error. */
  demo: Pick<UseMutationResult<DemoResult, Error, string>, "isPending" | "isError" | "error">;
  onExploreDemo: () => void;
  onImportOwn: () => void;
  /** Put focus back on "Import my own statement", e.g. after returning from its form. */
  focusImportChoice: boolean;
}

/** The currency and the two ways in: demo data, or the user's own statement. */
export function StartChoices({
  currency,
  onCurrencyChange,
  demo,
  onExploreDemo,
  onImportOwn,
  focusImportChoice,
}: StartChoicesProps) {
  const ids = { heading: useId(), currency: useId(), currencyHint: useId() };
  const busy = demo.isPending;

  return (
    <section aria-labelledby={ids.heading} aria-busy={busy} className="flex flex-col gap-6">
      <div>
        <h2 id={ids.heading} className="text-lg font-semibold tracking-tight">
          Get started
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          Look around with demo data, or bring in your own.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor={ids.currency}>Currency</Label>
        <CurrencySelect
          id={ids.currency}
          value={currency}
          onChange={onCurrencyChange}
          disabled={busy}
          aria-describedby={ids.currencyHint}
        />
        <p id={ids.currencyHint} className="text-muted-foreground text-xs">
          Used for your first accounts. Accounts in other currencies can be added later.
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <Choice
          icon={busy ? LoaderCircle : Compass}
          spin={busy}
          title={busy ? "Adding demo data…" : "Explore with demo data"}
          detail={
            busy
              ? "Importing a year of transactions. This only takes a moment."
              : "Two demo accounts with a year of made-up transactions."
          }
          emphasis
          disabled={busy}
          onClick={onExploreDemo}
        />
        <Choice
          icon={FileUp}
          title="Import my own statement"
          detail="Add your first account, then bring in a CSV or OFX file from your bank."
          disabled={busy}
          onClick={onImportOwn}
          autoFocus={focusImportChoice}
        />
      </div>

      {demo.isError ? <InlineError error={demo.error} /> : null}
      <p role="status" className="sr-only">
        {busy ? "Adding demo data" : ""}
      </p>
    </section>
  );
}

interface ChoiceProps {
  icon: LucideIcon;
  title: string;
  detail: string;
  onClick: () => void;
  disabled: boolean;
  /** The recommended way in, drawn a little stronger. */
  emphasis?: boolean;
  spin?: boolean;
  autoFocus?: boolean;
}

function Choice({
  icon: Icon,
  title,
  detail,
  onClick,
  disabled,
  emphasis = false,
  spin = false,
  autoFocus = false,
}: ChoiceProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      autoFocus={autoFocus}
      className={cn(
        "group flex w-full items-center gap-4 rounded-lg border p-4 text-left transition-colors outline-none",
        "hover:bg-accent focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
        "disabled:cursor-not-allowed disabled:hover:bg-transparent",
        // The choice in progress stays fully visible; the other one steps back.
        !spin && "disabled:opacity-50",
        emphasis &&
          "border-primary/40 bg-primary/5 hover:bg-primary/10 disabled:hover:bg-primary/5",
      )}
    >
      <span
        className={cn(
          "flex size-10 shrink-0 items-center justify-center rounded-lg",
          emphasis ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
        )}
      >
        <Icon
          aria-hidden="true"
          className={cn("size-5", spin && "animate-spin motion-reduce:animate-none")}
        />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{title}</span>
        <span className="text-muted-foreground mt-0.5 block text-sm">{detail}</span>
      </span>
      {spin ? null : (
        <ChevronRight
          aria-hidden="true"
          className="text-muted-foreground size-4 shrink-0 transition-transform group-enabled:group-hover:translate-x-0.5 motion-reduce:transition-none"
        />
      )}
    </button>
  );
}

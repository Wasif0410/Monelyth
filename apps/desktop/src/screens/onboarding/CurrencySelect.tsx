import { useMemo } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { currencyOptions, type CurrencyCode } from "@/screens/onboarding/currencies";

interface CurrencySelectProps {
  id: string;
  value: CurrencyCode;
  onChange: (currency: CurrencyCode) => void;
  disabled?: boolean;
  className?: string;
  "aria-describedby"?: string;
}

/** A dropdown of the currencies Monelyth offers, labelled in the user's language. */
export function CurrencySelect({
  id,
  value,
  onChange,
  disabled = false,
  className,
  "aria-describedby": describedBy,
}: CurrencySelectProps) {
  const options = useMemo(() => currencyOptions(), []);
  return (
    <Select
      value={value}
      onValueChange={(next) => {
        const option = options.find((candidate) => candidate.code === next);
        if (option) onChange(option.code);
      }}
      disabled={disabled}
    >
      <SelectTrigger id={id} aria-describedby={describedBy} className={cn("w-full", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map(({ code, label }) => (
          <SelectItem key={code} value={code}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

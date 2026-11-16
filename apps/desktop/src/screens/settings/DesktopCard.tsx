import { MonitorCog } from "lucide-react";
import { useId } from "react";
import { toast } from "sonner";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  useDesktopPreferences,
  useSetDesktopPreference,
  type DesktopPreferences,
} from "@/desktop/preferences";
import { errorMessage } from "@/lib/utils";
import { SettingsSection } from "@/screens/settings/SettingsSection";

interface Option {
  key: keyof DesktopPreferences;
  label: string;
  description: string;
}

const OPTIONS: readonly Option[] = [
  {
    key: "startAtSignIn",
    label: "Open Monelyth when you sign in",
    description: "It starts quietly in the system tray, ready when you need it.",
  },
  {
    key: "closeToTray",
    label: "Keep running in the tray when you close the window",
    description: "Click the tray icon to bring it back, or right-click it to quit.",
  },
  {
    key: "notifications",
    label: "Notifications",
    description: "A Windows notification when categorizing finishes while you're in another app.",
  },
];

/** How Monelyth behaves as a Windows app: sign-in, tray and notifications. */
export function DesktopCard() {
  const preferences = useDesktopPreferences();
  const setPreference = useSetDesktopPreference();

  return (
    <SettingsSection
      title="Desktop"
      description="How Monelyth behaves on your computer."
      icon={MonitorCog}
    >
      <ul className="divide-border flex flex-col divide-y">
        {OPTIONS.map((option) => (
          <PreferenceRow
            key={option.key}
            option={option}
            checked={preferences.data?.[option.key] ?? false}
            disabled={!preferences.isSuccess || setPreference.isPending}
            onChange={(value) => {
              setPreference.mutate(
                { key: option.key, value },
                {
                  onError: (error) => {
                    toast.error(`Couldn't change "${option.label}". ${errorMessage(error)}`);
                  },
                },
              );
            }}
          />
        ))}
      </ul>
    </SettingsSection>
  );
}

interface PreferenceRowProps {
  option: Option;
  checked: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}

function PreferenceRow({ option, checked, disabled, onChange }: PreferenceRowProps) {
  const id = useId();
  const descriptionId = `${id}-description`;
  return (
    <li className="flex items-center justify-between gap-6 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0">
        <Label htmlFor={id} className="text-sm font-medium">
          {option.label}
        </Label>
        <p id={descriptionId} className="text-muted-foreground mt-0.5 text-sm">
          {option.description}
        </p>
      </div>
      <Switch
        id={id}
        aria-describedby={descriptionId}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onChange}
      />
    </li>
  );
}

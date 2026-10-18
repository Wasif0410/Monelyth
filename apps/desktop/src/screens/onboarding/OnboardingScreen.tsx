import { Cpu, ShieldCheck, UserRoundX, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { useAccounts } from "@/api/queries";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { paths } from "@/paths";
import { defaultCurrency, type CurrencyCode } from "@/screens/onboarding/currencies";
import { FirstAccountForm } from "@/screens/onboarding/FirstAccountForm";
import { StartChoices } from "@/screens/onboarding/StartChoices";
import { useAddDemoData } from "@/screens/onboarding/useAddDemoData";

interface PrivacyPromise {
  icon: LucideIcon;
  title: string;
  detail: string;
}

const PROMISES: readonly PrivacyPromise[] = [
  {
    icon: ShieldCheck,
    title: "Your data never leaves this computer",
    detail: "Statements are read and stored here. Nothing is uploaded.",
  },
  {
    icon: UserRoundX,
    title: "No account or sign-up",
    detail: "Open the app and start. There is nothing to register.",
  },
  {
    icon: Cpu,
    title: "AI that runs locally",
    detail: "The assistant, coming in a later version, will run on this computer too.",
  },
];

type Step = "choose" | "first-account";

/** First launch: what Monelyth is, what it promises, and a one-click way in. */
export function OnboardingScreen() {
  const navigate = useNavigate();
  const accounts = useAccounts();
  const addDemoData = useAddDemoData();
  const [currency, setCurrency] = useState<CurrencyCode>(() =>
    defaultCurrency(navigator.languages.length > 0 ? navigator.languages : [navigator.language]),
  );
  const [step, setStep] = useState<Step>("choose");
  const [returnedFromForm, setReturnedFromForm] = useState(false);

  const hasAccounts = (accounts.data?.length ?? 0) > 0;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center justify-end px-6">
        {hasAccounts ? (
          <Button asChild variant="ghost" size="sm">
            <Link to={paths.transactions}>Go to my transactions</Link>
          </Button>
        ) : null}
      </header>

      <main className="flex flex-1 items-center justify-center px-8 pb-14">
        <div className="grid w-full max-w-5xl items-center gap-x-16 gap-y-10 md:grid-cols-[minmax(0,1fr)_minmax(0,25rem)]">
          <section aria-labelledby="welcome-heading" className="max-w-lg">
            <Logo className="size-12 text-xl" />
            <h1 id="welcome-heading" className="mt-6 text-4xl font-semibold tracking-tight">
              Welcome to Monelyth
            </h1>
            <p className="text-muted-foreground mt-3 text-lg text-pretty">
              See where your money goes, from the statements your bank already gives you.
            </p>

            <ul aria-label="Privacy" className="mt-10 flex flex-col gap-5 border-t pt-8">
              {PROMISES.map(({ icon: Icon, title, detail }) => (
                <li key={title} className="flex items-start gap-3.5">
                  <span className="bg-primary/10 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg">
                    <Icon aria-hidden="true" className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{title}</p>
                    <p className="text-muted-foreground mt-0.5 text-sm">{detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <Card>
            <CardContent className="p-6">
              {step === "choose" ? (
                <StartChoices
                  currency={currency}
                  onCurrencyChange={setCurrency}
                  demo={addDemoData}
                  onExploreDemo={() => {
                    addDemoData.mutate(currency, {
                      onSuccess: () => void navigate(paths.transactions),
                    });
                  }}
                  onImportOwn={() => {
                    addDemoData.reset();
                    setStep("first-account");
                  }}
                  focusImportChoice={returnedFromForm}
                />
              ) : (
                <FirstAccountForm
                  currency={currency}
                  onBack={() => {
                    setReturnedFromForm(true);
                    setStep("choose");
                  }}
                  onCreated={() => void navigate(paths.import)}
                />
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}

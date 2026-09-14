import { ProductOnboardingForm } from "@/components/product-onboarding-form";

export default function OnboardingPage() {
  return (
    <div className="stack">
      <div className="topbar">
        <h1>Onboarding</h1>
        <span className="badge warn">Manual approval path</span>
      </div>
      <ProductOnboardingForm />
    </div>
  );
}

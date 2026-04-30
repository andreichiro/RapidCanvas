import { type ExplainResponse } from "../api/client";

type TrustBadgeProps = {
  fallbackMode: ExplainResponse["trace"]["fallback_mode"];
  trustScore: number;
};

const fallbackLabels: Record<ExplainResponse["trace"]["fallback_mode"], string> = {
  none: "Normal",
  partial: "Partial",
  abstain: "Abstain",
  safe_summary: "Safe summary",
};

export default function TrustBadge({ fallbackMode, trustScore }: TrustBadgeProps) {
  return (
    <div className={`trust-badge trust-badge-${fallbackMode}`} aria-label="trust and fallback status">
      <span>{fallbackLabels[fallbackMode]}</span>
      <strong>{Math.round(trustScore * 100)}%</strong>
    </div>
  );
}

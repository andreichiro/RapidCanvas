import { type ProviderInfo } from "../api/client";

type ProviderSelectProps = {
  disabled?: boolean;
  onChange: (provider: string) => void;
  provider: string;
  providers: ProviderInfo[];
};

function comparisonLabel(status: ProviderInfo["comparison_status"]): string | null {
  if (status === "ran") {
    return "comparison ran";
  }
  if (status === "skipped") {
    return "comparison skipped";
  }
  if (status === "configured_not_run") {
    return "configured, not run";
  }
  return null;
}

function providerOptionLabel(provider: ProviderInfo): string {
  const status = provider.runnable
    ? "runnable"
    : provider.skipped_reason || !provider.configured
      ? "skipped"
      : "configured";
  const details = [
    status,
    provider.default_model ? `default ${provider.default_model}` : null,
    comparisonLabel(provider.comparison_status),
  ].filter(Boolean);

  return details.length ? `${provider.name} (${details.join(", ")})` : provider.name;
}

export default function ProviderSelect({ disabled = false, onChange, provider, providers }: ProviderSelectProps) {
  const options = providers.length
    ? providers
    : [
        {
          name: "openai",
          configured: false,
          skipped_reason: null,
          runnable: false,
          default_model: null,
          comparison_status: null,
        },
      ];

  return (
    <select
      aria-describedby="provider-status"
      disabled={disabled}
      id="provider"
      onChange={(event) => onChange(event.target.value)}
      value={provider}
    >
      {options.map((item) => (
        <option key={item.name} value={item.name}>
          {providerOptionLabel(item)}
        </option>
      ))}
    </select>
  );
}

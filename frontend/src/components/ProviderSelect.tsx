import { type ProviderInfo } from "../api/client";

type ProviderSelectProps = {
  disabled?: boolean;
  onChange: (provider: string) => void;
  provider: string;
  providers: ProviderInfo[];
};

export default function ProviderSelect({ disabled = false, onChange, provider, providers }: ProviderSelectProps) {
  const options = providers.length ? providers : [{ name: "openai", configured: false, skipped_reason: null, default_model: null }];

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
          {item.name}
        </option>
      ))}
    </select>
  );
}

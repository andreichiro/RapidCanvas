type GuardrailFlagsProps = {
  flags: string[];
};

function readableFlag(flag: string): string {
  return flag.replaceAll("_", " ");
}

export default function GuardrailFlags({ flags }: GuardrailFlagsProps) {
  if (!flags.length) {
    return <span className="muted-text">No active flags</span>;
  }

  return (
    <ul className="guardrail-flags" aria-label="guardrail flags">
      {flags.map((flag, index) => (
        <li key={`${flag}-${index}`}>{readableFlag(flag)}</li>
      ))}
    </ul>
  );
}

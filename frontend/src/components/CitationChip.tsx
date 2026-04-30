import { type Source } from "../api/client";

type CitationChipProps = {
  sourceId: string;
  source?: Source;
};

export default function CitationChip({ sourceId, source }: CitationChipProps) {
  const label = source ? `Citation ${sourceId}: ${source.title}` : `Citation ${sourceId}`;

  return (
    <a aria-label={label} className="citation-chip" href={`#source-${sourceId}`}>
      {sourceId}
    </a>
  );
}

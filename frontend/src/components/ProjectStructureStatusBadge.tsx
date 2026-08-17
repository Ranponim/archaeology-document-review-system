type Props = {
  text: string;
};

export function ProjectStructureStatusBadge({ text }: Props) {
  const normalized = text.toLowerCase();
  const tone =
    normalized.includes('누락') || normalized.includes('failed') || normalized.includes('미해결')
      ? 'danger'
      : normalized.includes('완료') || normalized.includes('존재') || normalized.includes('resolved')
        ? 'success'
        : normalized.includes('running') || normalized.includes('queued')
          ? 'active'
          : 'neutral';
  return <span className={`structure-badge structure-badge-${tone}`}>{text}</span>;
}

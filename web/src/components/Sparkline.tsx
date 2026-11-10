export function Sparkline({
  values,
  width = 92,
  height = 26,
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
}) {
  if (!values.length) {
    return (
      <span className="text-[10px] text-faint" aria-hidden>
        —
      </span>
    );
  }
  const max = Math.max(1, ...values);
  const min = Math.min(...values);
  const span = Math.max(1, max - min);
  const stepX = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => {
    const x = index * stepX;
    const y = height - 2 - ((value - min) / span) * (height - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = values[values.length - 1];

  return (
    <span className={className} aria-hidden>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="overflow-visible"
        role="presentation"
      >
        <polyline
          points={points.join(" ")}
          fill="none"
          stroke="var(--primary)"
          strokeWidth="1.4"
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity={0.8}
        />
        <circle
          cx={width}
          cy={height - 2 - ((last - min) / span) * (height - 4)}
          r="2"
          fill="var(--primary)"
        />
      </svg>
    </span>
  );
}

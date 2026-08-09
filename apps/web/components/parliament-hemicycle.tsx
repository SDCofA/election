type SeatOutcome = {
  contestant_id: string;
  projected_seats: number | null;
};

type SeatContestant = {
  id: string;
  short_name: string;
  color: string;
};

export function ParliamentHemicycle({
  contestants,
  outcomes,
  totalSeats
}: {
  contestants: SeatContestant[];
  outcomes: SeatOutcome[];
  totalSeats: number;
}) {
  const seatColors: string[] = [];
  const labels: string[] = [];
  for (const contestant of contestants) {
    const seats = outcomes.find((outcome) => outcome.contestant_id === contestant.id)?.projected_seats ?? 0;
    labels.push(`${contestant.short_name} ${seats}`);
    seatColors.push(...Array.from({ length: Math.max(0, seats) }, () => contestant.color));
  }
  seatColors.length = Math.min(seatColors.length, totalSeats);
  while (seatColors.length < totalSeats) seatColors.push("#344156");

  const rowCount = Math.max(5, Math.ceil(Math.sqrt(totalSeats / 2.4)));
  const weights = Array.from({ length: rowCount }, (_, index) => index + 4);
  const weightTotal = weights.reduce((sum, value) => sum + value, 0);
  const rowSeats = weights.map((weight) => Math.floor(totalSeats * weight / weightTotal));
  let unallocated = totalSeats - rowSeats.reduce((sum, value) => sum + value, 0);
  for (let row = 0; unallocated > 0; row = (row + 1) % rowCount) {
    rowSeats[row] += 1;
    unallocated -= 1;
  }

  let seatIndex = 0;
  const circles = rowSeats.flatMap((count, row) => {
    const radius = 26 + row * (68 / Math.max(rowCount - 1, 1));
    return Array.from({ length: count }, (_, position) => {
      const angle = Math.PI - (position + 0.5) * Math.PI / count;
      const x = 110 + radius * Math.cos(angle);
      const y = 105 - radius * Math.sin(angle);
      const color = seatColors[seatIndex];
      seatIndex += 1;
      return <circle cx={x} cy={y} fill={color} key={`${row}-${position}`} r="1.8" />;
    });
  });

  return (
    <svg
      aria-label={`Projected parliament: ${labels.join(", ")}`}
      className="parliament-hemicycle"
      role="img"
      viewBox="0 0 220 112"
    >
      {circles}
    </svg>
  );
}

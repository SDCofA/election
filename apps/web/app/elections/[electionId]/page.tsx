import { ForecastDashboard } from "@/components/forecast-dashboard";

const electionIds = [
  "us-2028-president",
  "gb-next-commons",
  "de-next-bundestag",
  "eu-2029-parliament",
  "eg-next-president",
  "au-next-chair",
  "se-2026-riksdag",
  "br-2026-president",
  "lv-2026-saeima",
  "il-2026-knesset",
  "nz-2026-general",
  "tr-next-president"
];

export function generateStaticParams() {
  return electionIds.map((electionId) => ({ electionId }));
}

export default async function ElectionPage({
  params
}: {
  params: Promise<{ electionId: string }>;
}) {
  const { electionId } = await params;
  return <ForecastDashboard electionId={electionId} />;
}

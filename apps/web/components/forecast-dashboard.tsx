"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";

import type { components } from "@elexion/contracts";
import { FlagIcon } from "@/components/flag-icon";
import { ParliamentHemicycle } from "@/components/parliament-hemicycle";
import { formatDate, formatDateTime, formatNumber, message as t } from "@/lib/i18n";
import { publicAsset, publicEndpoint } from "@/lib/public-data";

type Contestant = {
  id: string;
  name: string;
  short_name: string;
  color: string;
  incumbent?: boolean;
  ideology?: string | null;
  ballot_status?: string;
  basis?: string | null;
};
type Outcome = {
  contestant_id: string;
  win_probability: number;
  projected_share: number;
  share_low: number;
  share_high: number;
  projected_seats: number | null;
  seats_low: number | null;
  seats_high: number | null;
};
type Driver = { key: string; label: string; value: string; contribution: number; direction: string; confidence: number };
type DriverSensitivity = {
  driver_key: string;
  label: string;
  negative_incumbent_share_shift: number;
  observed_incumbent_share_shift: number;
  positive_incumbent_share_shift: number;
  confidence: number;
  clipped: boolean;
};
type ModelComparison = components["schemas"]["ModelComparison"];
type CoalitionReport = components["schemas"]["CoalitionReport"];
type ForecastSnapshot = components["schemas"]["ForecastSnapshot"];
type ElectionSummary = components["schemas"]["Election"];
type JurisdictionSummary = components["schemas"]["Jurisdiction"];

type InstitutionalFigure = {
  name: string;
  role: string;
  portrait: string;
  source: string;
  credit: string;
};

const INSTITUTIONAL_FIGURES: Record<string, InstitutionalFigure[]> = {
  "us-2028-president": [
    {
      name: "Donald J. Trump",
      role: "President · incumbency context",
      portrait: "/portraits/donald-trump.png",
      source: "https://www.whitehouse.gov/administration/donald-j-trump/",
      credit: "Official White House portrait"
    },
    {
      name: "JD Vance",
      role: "Vice President · succession context",
      portrait: "/portraits/jd-vance.jpg",
      source: "https://www.whitehouse.gov/administration/jd-vance/",
      credit: "Official White House portrait"
    }
  ],
  "de-next-bundestag": [
    {
      name: "Friedrich Merz",
      role: "Federal Chancellor · incumbency context",
      portrait: "/portraits/friedrich-merz.webp",
      source: "https://www.bundesregierung.de/breg-en/federal-cabinet/2343412-2343412",
      credit: "Federal Government / Steffen Kugler"
    }
  ]
};

function SiteBrand({ href = "/" }: { href?: string }) {
  return (
    <Link className="brand" href={href} aria-label="SDCofA Election Desk home">
      <Image
        className="brand-lockup"
        src={publicAsset("/brand/sdcofa-logo-dark.png")}
        alt="Strategic Data Company of Ankara"
        width={360}
        height={145}
        priority
      />
      <b>ELECTION DESK</b>
    </Link>
  );
}
type ElectionDetail = {
  jurisdiction: {
    name: string;
    flag: string;
    eligibility: string;
    is_exception: boolean;
    coverage_status: string;
    blocking_reasons?: string[];
  };
  election: {
    id: string;
    name: string;
    election_date: string | null;
    date_confidence: string;
    system: string;
    status: string;
    last_updated: string;
    seats_total: number | null;
    majority: number | null;
    contestants: Contestant[];
    potential_candidates?: Contestant[];
    sources?: Array<{ label: string; url: string; authority: string; license: string }>;
  };
  forecast: {
    id: string;
    as_of: string;
    model_version: string;
    model_family: string;
    selection_status: string;
    simulation_count: number;
    data_quality: string;
    freshness: string;
    headline: string;
    majority_probability: number;
    turnout_median: number;
    forecast_horizon_days?: number;
    uncertainty_scale?: number;
    effective_volatility?: number;
    outcomes: Outcome[];
    scenario_outcomes?: Array<{
      scenario_id: string;
      label: string;
      weight: number;
      assumption: string;
      source_ids: string[];
      outcomes: Outcome[];
    }>;
    drivers: Driver[];
    driver_sensitivity: DriverSensitivity[];
    input_provenance: Array<{ source_id: string; label: string; url: string }>;
  } | null;
};

type CatalogStatus = {
  total_jurisdictions: number;
  forecast_ready: number;
  calendar_only: number;
  mechanics_blocked: number;
  sourced_calendars: number;
};

function PossibleField({ contestants }: { contestants: Contestant[] }) {
  return (
    <article className="panel calendar-panel possible-field-panel">
      <header><span>POSSIBLE FIELD</span><small>Not the official ballot</small></header>
      <h2>Candidates, parties and blocs worth tracking</h2>
      <p>Uncertainty does not require an empty page. These are sourced possibilities, not certified nominees; forecast probabilities may represent broader nominee scenarios.</p>
      <div className="possible-field-grid">
        {contestants.map((contestant) => (
          <div key={contestant.id} style={{ "--party": contestant.color } as React.CSSProperties}>
            <i>{contestant.short_name}</i>
            <span><strong>{contestant.name}</strong><small>{contestant.ballot_status ?? "possible"} · {contestant.ideology ?? "affiliation evolving"}</small></span>
            {contestant.basis && <p>{contestant.basis}</p>}
          </div>
        ))}
      </div>
    </article>
  );
}

const FALLBACK: ElectionDetail = {
  jurisdiction: { name: "United States", flag: "US", eligibility: "v-dem:liberal-democracy", is_exception: false, coverage_status: "forecast_ready" },
  election: {
    id: "us-2028-president",
    name: "2028 Presidential Election",
    election_date: "2028-11-07",
    date_confidence: "constitutional",
    system: "electoral_college",
    status: "structural forecast",
    last_updated: "2026-08-09T09:00:00Z",
    seats_total: 538,
    majority: 270,
    contestants: [
      { id: "dem", name: "Democratic coalition", short_name: "DEM", color: "#2f7df6", incumbent: true },
      { id: "gop", name: "Republican coalition", short_name: "GOP", color: "#ef3e4a" },
      { id: "other", name: "Other candidates", short_name: "OTH", color: "#a8b1bf" }
    ]
  },
  forecast: {
    id: "fallback",
    as_of: "2026-08-09T09:00:00Z",
    model_version: "structural-ensemble-0.2.0",
    model_family: "baseline_ensemble",
    selection_status: "baseline retained until reliable walk-forward promotion evidence",
    simulation_count: 1000000,
    data_quality: "D",
    freshness: "structural-only",
    headline: "A structurally even race with unusually wide early-cycle uncertainty.",
    majority_probability: 0.49,
    turnout_median: 0.655,
    outcomes: [
      { contestant_id: "dem", win_probability: 0.51, projected_share: 0.493, share_low: 0.438, share_high: 0.548, projected_seats: 272, seats_low: 241, seats_high: 303 },
      { contestant_id: "gop", win_probability: 0.49, projected_share: 0.487, share_low: 0.432, share_high: 0.542, projected_seats: 266, seats_low: 235, seats_high: 297 },
      { contestant_id: "other", win_probability: 0, projected_share: 0.02, share_low: 0.008, share_high: 0.04, projected_seats: 0, seats_low: 0, seats_high: 0 }
    ],
    drivers: [
      { key: "income", label: "Real disposable income", value: "Baseline", contribution: 0.18, direction: "incumbent", confidence: 0.54 },
      { key: "approval", label: "Executive approval", value: "Early cycle", contribution: -0.11, direction: "challenger", confidence: 0.38 },
      { key: "polarization", label: "Partisan alignment", value: "High", contribution: 0.31, direction: "stability", confidence: 0.82 },
      { key: "polling", label: "Polling signal", value: "Not yet available", contribution: 0, direction: "neutral", confidence: 0.05 }
    ],
    driver_sensitivity: [],
    input_provenance: []
  }
};

const WATCHLIST = [
  { id: "us-2028-president", flag: "US", country: "United States", label: "President · Electoral College", date: "NOV 2028", color: "" },
  { id: "gb-next-commons", flag: "GB", country: "United Kingdom", label: "Commons · FPTP", date: "PROJECTED", color: "cyan" },
  { id: "de-next-bundestag", flag: "DE", country: "Germany", label: "Bundestag · mixed member", date: "MAR 2029", color: "gold" },
  { id: "br-2026-president", flag: "BR", country: "Brazil", label: "President · runoff", date: "OCT 2026", color: "violet" },
  { id: "tr-next-president", flag: "TR", country: "Türkiye", label: "President · runoff", date: "MAY 2028", color: "amber" },
  { id: "arg-next-national", flag: "AR", country: "Argentina", label: "National control · scenario", date: "AUG 2029", color: "violet" }
];

const pct = (value: number) => `${Math.round(value * 100)}%`;
const signedPoints = (value: number) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)} pp`;
const probabilityLabel = (value: number) => {
  if (value >= 0.8) return "STRONG FAVORITE";
  if (value >= 0.6) return "FAVORED";
  if (value >= 0.4) return "COMPETITIVE";
  if (value >= 0.2) return "UNDERDOG · REAL PATH";
  return "LONG SHOT";
};
type ConnectionState = "connecting" | "live" | "fallback";

function GlobalWatch({
  catalog,
  electionId,
  elections,
  jurisdictions
}: {
  catalog: CatalogStatus | null;
  electionId: string;
  elections: ElectionSummary[];
  jurisdictions: JurisdictionSummary[];
}) {
  const jurisdictionById = new Map(jurisdictions.map((item) => [item.id, item]));
  const liveWatchlist = [...elections]
    .sort((left, right) => {
      if (left.election_date == null) return right.election_date == null ? 0 : 1;
      if (right.election_date == null) return -1;
      return left.election_date.localeCompare(right.election_date);
    })
    .slice(0, 12)
    .map((election) => {
      const jurisdiction = jurisdictionById.get(election.jurisdiction_id);
      return {
        id: election.id,
        flag: jurisdiction?.flag ?? election.jurisdiction_id.slice(0, 2).toUpperCase(),
        country: jurisdiction?.name ?? election.jurisdiction_id,
        label: `${election.name.replace(/^\d{4}\s+/, "")} · ${election.system.replaceAll("_", " ")}`,
        date: election.election_date
          ? formatDate(`${election.election_date}T00:00:00Z`, {
              month: "short",
              year: "numeric",
              timeZone: "UTC"
            }).toUpperCase()
          : "TBD",
        color: jurisdiction?.forecast_enabled ? "cyan" : "amber"
      };
    });
  const watchlist = liveWatchlist.length ? liveWatchlist : WATCHLIST;
  return (
    <aside className="rail" id="calendar" aria-label="Election watchlist">
      <div className="rail-heading"><span>G20 WATCH</span><b>{String(watchlist.length).padStart(2, "0")}</b></div>
      {watchlist.map((item) => (
        <Link
          aria-current={item.id === electionId ? "page" : undefined}
          className={`watch ${item.id === electionId ? "active-watch" : ""}`}
          href={`/elections/${item.id}`}
          key={item.id}
        >
          <i className={item.color}><FlagIcon code={item.flag} label={item.country} /></i>
          <span><strong>{item.country}</strong><small>{item.label}</small></span>
          <em>{item.date}</em>
        </Link>
      ))}
      <div className="coverage">
        <span>CATALOG STATUS</span>
        <div><b>{catalog?.total_jurisdictions ?? 19}</b><small>G20 COUNTRIES</small></div>
        <div><b>{catalog?.forecast_ready ?? 16}</b><small>FORECAST READY</small></div>
        <p>{catalog?.sourced_calendars ?? watchlist.length} sourced country records · {catalog?.forecast_ready ?? 0} forecasts · {catalog?.calendar_only ?? 0} calendar-only.</p>
      </div>
    </aside>
  );
}

function CalendarOnlyView({
  catalog,
  connection,
  currentTime,
  detail,
  electionId,
  elections,
  jurisdictions
}: {
  catalog: CatalogStatus | null;
  connection: ConnectionState;
  currentTime: number;
  detail: ElectionDetail;
  electionId: string;
  elections: ElectionSummary[];
  jurisdictions: JurisdictionSummary[];
}) {
  const sources = detail.election.sources ?? [];
  const coverageLabel = detail.jurisdiction.coverage_status === "mechanics_blocked"
    ? "MECHANICS BLOCKED"
    : "CALENDAR ONLY";
  return (
    <div className="shell">
      <header className="topbar">
        <SiteBrand />
        <nav aria-label="Primary navigation">
          <Link href="/">Forecast</Link>
          <Link className="active" href="/calendar">Calendar</Link>
          <Link href="/methodology">Methodology</Link>
        </nav>
        <div className="status-cluster">
          <span className={`live-dot ${connection}`} />
          <span>{connection === "live" ? "API LIVE" : "CONNECTING"}</span>
          <time>{currentTime ? formatDate(currentTime, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "--:--"}</time>
        </div>
      </header>
      <div className="breaking" role="status">
        <span>{coverageLabel}</span>
        <p>Forecast withheld because no defensible national probability target currently exists</p>
        <b>FAIL CLOSED</b>
      </div>
      <main id="top">
        <GlobalWatch
          catalog={catalog}
          electionId={electionId}
          elections={elections}
          jurisdictions={jurisdictions}
        />
        <section className="workspace calendar-workspace" id="calendar-view">
          <div className="election-title">
            <div>
              <span className="eyebrow election-eyebrow"><FlagIcon code={detail.jurisdiction.flag} label={detail.jurisdiction.name} /> INSTITUTIONAL VIEW</span>
              <h1>{detail.jurisdiction.name} <strong>{detail.election.name}</strong></h1>
              <p>No probability is published for this limited-coverage election.</p>
            </div>
            <div className="countdown"><span>SCHEDULED DATE</span><b>{detail.election.election_date ? formatDate(`${detail.election.election_date}T00:00:00Z`, { month: "short", day: "numeric", timeZone: "UTC" }) : "TBD"}</b><small>{detail.election.election_date ? new Date(`${detail.election.election_date}T00:00:00Z`).getUTCFullYear() : "AWAITING AUTHORITY"}</small></div>
          </div>
          <div className="confidence-banner">
            <span className="grade">D</span>
            <div><b>CALENDAR / MECHANICS VIEW</b><small>{detail.election.date_confidence} · {detail.election.system.replaceAll("_", " ")}</small></div>
            <p>Calendar metadata remains visible; forecast and live-result claims stay suppressed.</p>
          </div>
          <div className="calendar-grid">
            <article className="panel calendar-panel">
              <header><span>PUBLICATION GATE</span><small>Explicit quality state</small></header>
              <h2>Forecast unavailable</h2>
              {(detail.jurisdiction.blocking_reasons ?? ["Election mechanics or contestant identities remain unresolved."]).map((reason) => <p key={reason}>{reason}</p>)}
              <dl>
                <div><dt>Election date</dt><dd>{detail.election.election_date ? formatDate(`${detail.election.election_date}T00:00:00Z`, { dateStyle: "medium", timeZone: "UTC" }) : "To be determined"}</dd></div>
                <div><dt>Date confidence</dt><dd>{detail.election.date_confidence}</dd></div>
                <div><dt>Results feed</dt><dd>Unavailable</dd></div>
              </dl>
            </article>
            <article className="panel calendar-panel source-panel">
              <header><span>SOURCE LEDGER</span><small>{sources.length} records</small></header>
              {sources.map((source) => (
                <a href={source.url} key={source.url} rel="noreferrer">
                  <b>{source.label}</b><small>{source.authority} · {source.license}</small>
                </a>
              ))}
            </article>
            {(detail.election.potential_candidates?.length ?? detail.election.contestants.length) > 0 && (
              <PossibleField contestants={detail.election.potential_candidates?.length ? detail.election.potential_candidates : detail.election.contestants} />
            )}
          </div>
        </section>
        <aside className="insight-rail">
          <article className="mini-panel model-card">
            <span>QUALITY STATE</span><div className="pulse-ring"><b>D</b><small>LIMITED</small></div>
            <p>Calendar view only. No simulated or unverified vote totals.</p>
          </article>
          <article className="mini-panel methodology">
            <span>TRANSPARENCY</span>
            <Link href="/methodology">OPEN METHODOLOGY →</Link>
            <a href={publicEndpoint(`/v1/elections/${electionId}/mechanics`)}>OPEN MECHANICS →</a>
            <a href={publicEndpoint(`/v1/elections/${electionId}/sources`)}>OPEN SOURCES →</a>
          </article>
        </aside>
      </main>
      <footer className="footer">
        <span>SDCOFA ELECTION DESK / CALENDAR</span>
        <p>{coverageLabel} is an explicit limitation, not a forecast. Part of <a href="https://github.com/MonarchCastleTech" rel="noreferrer">Monarch Castle Technologies</a>.</p>
        <span>UPDATED {formatDateTime(detail.election.last_updated)}</span>
      </footer>
    </div>
  );
}

function DataUnavailableView({ electionId }: { electionId: string }) {
  return (
    <main className="unavailable-view">
      <span className="grade">D</span>
      <h1>{t("forecast.unavailable")}</h1>
      <p>Live API data for {electionId} could not be verified. No substitute election or probability is shown.</p>
      <Link href="/">Return to command center</Link>
    </main>
  );
}

export function ForecastDashboard({ electionId = "us-2028-president" }: { electionId?: string }) {
  const [detail, setDetail] = useState(FALLBACK);
  const [comparison, setComparison] = useState<ModelComparison | null>(null);
  const [coalitions, setCoalitions] = useState<CoalitionReport | null>(null);
  const [history, setHistory] = useState<ForecastSnapshot[]>([]);
  const [coalitionSelection, setCoalitionSelection] = useState<string[]>([]);
  const [catalog, setCatalog] = useState<CatalogStatus | null>(null);
  const [elections, setElections] = useState<ElectionSummary[]>([]);
  const [jurisdictions, setJurisdictions] = useState<JurisdictionSummary[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [currentTime, setCurrentTime] = useState(0);
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

  useEffect(() => {
    const firstTick = window.setTimeout(() => setCurrentTime(Date.now()), 0);
    const clock = window.setInterval(() => setCurrentTime(Date.now()), 60_000);
    const controller = new AbortController();
    const optionalJson = async <T,>(path: string): Promise<T | null> => {
      try {
        const response = await fetch(publicEndpoint(path), { signal: controller.signal });
        return response.ok ? await response.json() as T : null;
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        return null;
      }
    };
    Promise.all([
      fetch(publicEndpoint(`/v1/elections/${encodeURIComponent(electionId)}`), { signal: controller.signal }),
      optionalJson<CatalogStatus>("/v1/catalog/status"),
      optionalJson<ElectionSummary[]>("/v1/elections"),
      optionalJson<JurisdictionSummary[]>("/v1/jurisdictions")
    ])
      .then(async ([detailResponse, catalogData, electionsData, jurisdictionsData]) => {
        if (!detailResponse.ok) throw new Error("Election data unavailable");
        const detailData = await detailResponse.json() as ElectionDetail;
        let comparisonData: ModelComparison | null = null;
        let coalitionData: CoalitionReport | null = null;
        let historyData: ForecastSnapshot[] = [];
        if (detailData.forecast) {
          const [comparisonResponse, historyResponse, optionalCoalitionData] = await Promise.all([
            fetch(
              publicEndpoint(`/v1/elections/${encodeURIComponent(electionId)}/model-comparison`),
              { signal: controller.signal }
            ),
            fetch(
              publicEndpoint(`/v1/elections/${encodeURIComponent(electionId)}/forecasts`),
              { signal: controller.signal }
            ),
            optionalJson<CoalitionReport>(`/v1/elections/${encodeURIComponent(electionId)}/coalitions`)
          ]);
          if (!comparisonResponse.ok || !historyResponse.ok) {
            throw new Error("Forecast evidence unavailable");
          }
          comparisonData = await comparisonResponse.json() as ModelComparison;
          historyData = await historyResponse.json() as ForecastSnapshot[];
          coalitionData = optionalCoalitionData;
        }
        return [detailData, catalogData, electionsData, jurisdictionsData, comparisonData, coalitionData, historyData] as const;
      })
      .then(([detailData, catalogData, electionsData, jurisdictionsData, comparisonData, coalitionData, historyData]) => {
        setDetail(detailData);
        setCatalog(catalogData);
        setElections(electionsData ?? []);
        setJurisdictions(jurisdictionsData ?? []);
        setComparison(comparisonData);
        setCoalitions(coalitionData);
        setHistory(historyData);
        setCoalitionSelection(coalitionData?.coalitions[0]?.member_ids ?? []);
        setConnection("live");
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setConnection("fallback");
        }
      });
    return () => {
      controller.abort();
      window.clearTimeout(firstTick);
      window.clearInterval(clock);
    };
  }, [electionId]);

  const outcomes = useMemo(
    () => (detail.forecast?.outcomes ?? []).map((outcome) => ({
      ...outcome,
      contestant: detail.election.contestants.find((item) => item.id === outcome.contestant_id)!
    })),
    [detail]
  );
  const leaders = [...outcomes]
    .sort((left, right) => right.win_probability - left.win_probability)
    .slice(0, 2);
  const daysAway = currentTime && detail.election.election_date
    ? Math.max(0, Math.ceil((new Date(detail.election.election_date).getTime() - currentTime) / 86_400_000))
    : 0;
  const forecast = detail.forecast;
  const coalitionOutcome = useMemo(() => {
    if (!coalitions) return null;
    const selected = new Set(coalitionSelection);
    return coalitions.coalitions.find((item) => (
      item.member_ids.length === selected.size
      && item.member_ids.every((memberId) => selected.has(memberId))
    )) ?? null;
  }, [coalitionSelection, coalitions]);
  const parliamentary = ["fptp", "proportional", "mixed_member"].includes(
    detail.election.system
  );

  if (connection === "fallback" && electionId !== FALLBACK.election.id) {
    return <DataUnavailableView electionId={electionId} />;
  }

  if (forecast === null) {
    return (
      <CalendarOnlyView
        catalog={catalog}
        connection={connection}
        currentTime={currentTime}
        detail={detail}
        electionId={electionId}
        elections={elections}
        jurisdictions={jurisdictions}
      />
    );
  }

  const figures = INSTITUTIONAL_FIGURES[electionId] ?? [];
  const leadingProbability = leaders[0]?.win_probability ?? 0.5;
  const monteCarloSe = Math.sqrt(
    leadingProbability * (1 - leadingProbability) / forecast.simulation_count
  ) * 100;
  const entropy = -[
    leadingProbability,
    1 - leadingProbability
  ].reduce((sum, probability) => (
    probability > 0 ? sum + probability * Math.log2(probability) : sum
  ), 0);
  const intervalWidth = leaders[0]
    ? (leaders[0].share_high - leaders[0].share_low) * 100
    : 0;

  return (
    <div className="shell">
      <header className="topbar">
        <SiteBrand href="#top" />
        <nav aria-label="Primary navigation">
          <a className="active" data-i18n-key="nav.forecast" href="#forecast">{t("nav.forecast")}</a>
          <a data-i18n-key="nav.map" href="#map">{t("nav.map")}</a>
          <a data-i18n-key="nav.model" href="#drivers">{t("nav.model")}</a>
          <Link data-i18n-key="nav.calendar" href="/calendar">{t("nav.calendar")}</Link>
        </nav>
        <div className="status-cluster">
          <span className={`live-dot ${connection}`} />
          <span>{connection === "live" ? t("status.apiLive") : connection === "fallback" ? t("status.sample") : t("status.connecting")}</span>
          <time>{currentTime ? formatDate(currentTime, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) : "--:--"}</time>
        </div>
      </header>

      <div className="breaking" role="status">
        <span>SDCOFA MODEL WATCH</span>
        <p>Baseline ensemble active · Gaussian and Markov challengers gated by walk-forward evidence</p>
        <b>{formatNumber(forecast.simulation_count)} RUNS</b>
      </div>

      <main id="top">
        <GlobalWatch
          catalog={catalog}
          electionId={electionId}
          elections={elections}
          jurisdictions={jurisdictions}
        />

        <section className="workspace" id="forecast">
          <div className="election-title">
            <div>
              <span className="eyebrow election-eyebrow"><FlagIcon code={detail.jurisdiction.flag} label={detail.jurisdiction.name} /> NATIONAL FORECAST</span>
              <h1>{detail.jurisdiction.name} <strong>{detail.election.name.replace(" Election", "")}</strong></h1>
              <p>{forecast.headline}</p>
            </div>
            <div className="countdown"><span>ELECTION WINDOW</span><b>{formatNumber(daysAway)}</b><small>DAYS</small></div>
          </div>

          <div className="confidence-banner">
            <span className="grade">{forecast.data_quality}</span>
            <div><b>{detail.election.status.toUpperCase()}</b><small>{forecast.freshness} · {detail.election.date_confidence}</small></div>
            <p>{comparison?.fold_count
              ? `Backtest evidence: ${comparison.fold_count} verified out-of-sample folds.`
              : "UNVALIDATED SCENARIO: 0 jurisdiction-specific out-of-sample folds. This is not a backtested call."}</p>
          </div>

          <div className="hero-grid">
            <article className="panel probability-panel">
              <header><span>{t("forecast.winProbability")}</span><small>Monte Carlo ensemble</small></header>
              <div className="duel">
                {leaders.map(({ contestant, win_probability }) => (
                  <div className="candidate" key={contestant.id}>
                    <div className="avatar" style={{ "--party": contestant.color } as React.CSSProperties}>
                      {contestant.short_name.slice(0, 1)}<span>{contestant.incumbent ? "INC" : "CHL"}</span>
                    </div>
                    <small>{contestant.name}</small>
                    <strong>{pct(win_probability)}</strong>
                    <em>{probabilityLabel(win_probability)}</em>
                  </div>
                ))}
                <div className="probability-gauge" style={{ "--value": `${leaders[0].win_probability * 360}deg` } as React.CSSProperties}>
                  <div><small>MODEL</small><b>±{Math.round((leaders[0].share_high - leaders[0].share_low) * 50)}<sup>pt</sup></b><span>90% RANGE</span></div>
                </div>
              </div>
              <div className="probability-scale"><span>SAFE {leaders[0].contestant.short_name}</span><i /><b>TOSS-UP</b><i /><span>SAFE {leaders[1].contestant.short_name}</span></div>
            </article>

            <article className="panel pathway-panel" id="map">
              <header><span>{t("forecast.pathway")}</span><small>{detail.election.majority ?? "50%"} needed</small></header>
              <div className="seat-total">
                {leaders.map(({ contestant, projected_seats }, index) => (
                  <div key={contestant.id} className={index ? "right" : ""}>
                    <small>{contestant.short_name} MEDIAN</small><b>{projected_seats ?? pct(leaders[index].projected_share)}</b>
                  </div>
                ))}
              </div>
              <div className="electoral-track">
                <span style={{ width: `${(leaders[0].projected_seats ?? 269) / (detail.election.seats_total ?? 538) * 100}%`, background: leaders[0].contestant.color }} />
                <i>{detail.election.majority ?? "50%"}</i>
                <span style={{ background: leaders[1].contestant.color }} />
              </div>
              {parliamentary && detail.election.seats_total ? (
                <ParliamentHemicycle
                  contestants={detail.election.contestants}
                  outcomes={forecast.outcomes}
                  totalSeats={detail.election.seats_total}
                />
              ) : (
                <div className="state-grid" aria-label="Illustrative seat pathway matrix" role="img">
                  {Array.from({ length: 54 }, (_, i) => <i key={i} className={i < 23 ? "blue" : i < 29 ? "swing" : "red"} />)}
                </div>
              )}
              <p className="panel-note">National layout only · official regional model activates after validated boundaries and inputs.</p>
            </article>
          </div>

          {!!detail.election.potential_candidates?.length && (
            <PossibleField contestants={detail.election.potential_candidates} />
          )}

          {!!forecast.scenario_outcomes?.length && (
            <article className="panel scenario-panel" aria-labelledby="scenario-heading">
              <header><span id="scenario-heading">CONDITIONAL MATCHUPS</span><small>Candidate uncertainty modeled explicitly</small></header>
              <p>Each row conditions on a different ballot. Headline probabilities mix these scenarios using the displayed structural weights; weights are not nomination forecasts.</p>
              <div className="scenario-grid">
                {forecast.scenario_outcomes.map((scenario) => (
                  <section key={scenario.scenario_id}>
                    <div className="scenario-title"><b>{scenario.label}</b><small>{pct(scenario.weight)} MIXTURE WEIGHT</small></div>
                    <div className="scenario-results">
                      {scenario.outcomes.slice(0, 2).map((outcome) => {
                        const contestant = detail.election.contestants.find((item) => item.id === outcome.contestant_id);
                        return contestant ? (
                          <span key={outcome.contestant_id} style={{ "--party": contestant.color } as React.CSSProperties}>
                            <i />
                            <small>{contestant.short_name} WIN</small>
                            <b>{pct(outcome.win_probability)}</b>
                            <em>{pct(outcome.projected_share)} vote · {pct(outcome.share_low)}–{pct(outcome.share_high)}</em>
                          </span>
                        ) : null;
                      })}
                    </div>
                    <p>{scenario.assumption}</p>
                    <small className="scenario-source">EVIDENCE: {scenario.source_ids.join(" · ")}</small>
                  </section>
                ))}
              </div>
            </article>
          )}

          <div className="lower-grid">
            <article className="panel projection-panel">
              <header><span>VOTE & SEAT PROJECTION</span><small>90% credible interval</small></header>
              <div className="projection-table">
                {outcomes.map(({ contestant, projected_share, share_low, share_high, projected_seats, seats_low, seats_high }) => (
                  <div className="projection-row" key={contestant.id}>
                    <b>{contestant.short_name}</b>
                    <span><i style={{ width: `${projected_share * 100}%`, background: contestant.color }} /></span>
                    <strong>{pct(projected_share)}</strong>
                    <small>{pct(share_low)}–{pct(share_high)}</small>
                    <em>{projected_seats == null ? "—" : `${projected_seats} (${seats_low}–${seats_high})`}</em>
                  </div>
                ))}
              </div>
              <div className="turnout"><span>TURNOUT MEDIAN</span><b>{pct(forecast.turnout_median)}</b><i><span style={{ width: `${forecast.turnout_median * 100}%` }} /></i></div>
            </article>

            <article className="panel drivers-panel" id="drivers">
              <header><span>{t("forecast.drivers")}</span><small>Directional contribution</small></header>
              <div className="drivers">
                {forecast.drivers.map((driver) => (
                  <div className="driver" key={driver.key}>
                    <span><b>{driver.label}</b><small>{driver.value}</small></span>
                    <div><i className="midline" /><em className={driver.contribution < 0 ? "negative" : "positive"} style={{ width: `${Math.abs(driver.contribution) * 48}%`, [driver.contribution < 0 ? "insetInlineEnd" : "insetInlineStart"]: "50%" } as React.CSSProperties} /></div>
                    <strong>{Math.round(driver.confidence * 100)}</strong>
                  </div>
                ))}
              </div>
              <footer><span>CHALLENGER ←</span><b>CONFIDENCE</b><span>→ INCUMBENT</span></footer>
              {forecast.driver_sensitivity.length > 0 && (
                <div className="sensitivity-wrap">
                  <div className="sensitivity-title">
                    <b>DRIVER SENSITIVITY MATRIX</b>
                    <small>One driver varied from −1 to +1; all other inputs held constant</small>
                  </div>
                  <div className="sensitivity-matrix" role="table" aria-label="Driver sensitivity matrix">
                    <div className="sensitivity-head" role="row">
                      <b role="columnheader">DRIVER</b>
                      <b role="columnheader">−1 SIGNAL</b>
                      <b role="columnheader">OBSERVED</b>
                      <b role="columnheader">+1 SIGNAL</b>
                    </div>
                    {forecast.driver_sensitivity.map((item) => (
                      <div className="sensitivity-row" role="row" key={item.driver_key}>
                        <span role="cell">{item.label}{item.clipped ? <sup title="Scenario reaches the model's structural shift cap">CAP</sup> : null}</span>
                        <span role="cell">{signedPoints(item.negative_incumbent_share_shift)}</span>
                        <strong role="cell">{signedPoints(item.observed_incumbent_share_shift)}</strong>
                        <span role="cell">{signedPoints(item.positive_incumbent_share_shift)}</span>
                      </div>
                    ))}
                  </div>
                  <p>Values are incumbent vote-share shifts, in percentage points—not win-probability claims.</p>
                </div>
              )}
            </article>
          </div>
          <article className="panel comparison-panel" aria-labelledby="model-comparison-heading">
            <header><span id="model-comparison-heading">PUBLIC BASELINE VS CHALLENGERS</span><small>Strict walk-forward promotion gate</small></header>
            <div className="comparison-summary">
              <div><small>PUBLIC MODEL</small><b>{forecast.model_family.replaceAll("_", " ")}</b></div>
              <div><small>CHALLENGERS</small><b>Gaussian · Markov momentum</b></div>
              <div><small>HISTORICAL BRIER LEADER</small><b>{comparison?.historical_leader?.replaceAll("_", " ") ?? "Not established"}</b></div>
              <div><small>DECISION</small><b>{comparison?.winner ? `${comparison.winner.replaceAll("_", " ")} promoted` : "Baseline retained"}</b></div>
            </div>
            {comparison && comparison.simulation_count_per_model_fold > 0 && (
              <p>{comparison.simulation_count_per_model_fold.toLocaleString()} predictive draws per model-fold across {comparison.held_out_election_count} held-out elections.</p>
            )}
            {comparison?.evaluated_horizon_min_days != null && comparison.evaluated_horizon_max_days != null && comparison.target_horizon_days != null && (
              <p>Evaluated horizon: {comparison.evaluated_horizon_min_days}–{comparison.evaluated_horizon_max_days} days. Current target: {comparison.target_horizon_days} days.</p>
            )}
            <p>{comparison?.message ?? "Eight or more strict source-vintage folds required before either challenger can replace baseline."}</p>
            {comparison && comparison.fold_count > 0 ? (
              <div className="comparison-metrics" role="table" aria-label="Walk-forward model metrics">
                <div className="comparison-metrics-head" role="row">
                  <b>MODEL</b><b>FOLDS</b><b>BRIER</b><b>RMSE</b><b>COVER</b><b>CAL ERR</b>
                </div>
                {comparison.metrics.map((metric) => (
                  <div className="comparison-metrics-row" role="row" key={metric.model_family}>
                    <span>{metric.model_family.replaceAll("_", " ")}</span>
                    <span>{metric.folds}</span>
                    <span>{metric.brier_score.toFixed(4)}</span>
                    <span>{metric.vote_share_rmse.toFixed(4)}</span>
                    <span>{Math.round(metric.interval_coverage * 100)}%</span>
                    <span>{Math.round(metric.calibration_error * 100)}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="comparison-evidence-empty">0 VERIFIED OUT-OF-SAMPLE FOLDS · NO WINNER DECLARED</div>
            )}
            {!!comparison?.validation_constraints?.length && (
              <div className="validation-constraints">
                <div>
                  <span><small>DIRECT ELECTIONS</small><b>{comparison.historical_election_count}</b></span>
                  <span><small>HISTORY SPAN</small><b>{comparison.historical_span_years} years</b></span>
                  <span><small>MAXIMUM HOLDOUTS</small><b>{comparison.maximum_held_out_elections}</b></span>
                </div>
                <strong>WHY THIS IS NOT A RELIABLE BACKTEST</strong>
                <ul>{comparison.validation_constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul>
              </div>
            )}
          </article>
          <article className="panel diagnostics-panel" aria-labelledby="diagnostics-heading">
            <header><span id="diagnostics-heading">MODEL DIAGNOSTICS</span><small>For the statistically curious</small></header>
            <div>
              <span><small>BINARY ENTROPY</small><b>{entropy.toFixed(3)} bits</b><em>1.000 = maximum uncertainty</em></span>
              <span><small>SIMULATION NOISE ONLY</small><b>±{monteCarloSe.toFixed(3)} pp</b><em>Not total forecast error</em></span>
              <span><small>90% SHARE WIDTH</small><b>{intervalWidth.toFixed(1)} pp</b><em>Leading modeled bloc</em></span>
              <span><small>FORECAST HORIZON</small><b>{forecast.forecast_horizon_days ?? daysAway} days</b><em>Measured from model as-of date</em></span>
              <span><small>HORIZON MULTIPLIER</small><b>×{(forecast.uncertainty_scale ?? 1).toFixed(2)}</b><em>Applied to structural volatility</em></span>
              <span><small>EFFECTIVE VOLATILITY</small><b>{pct(forecast.effective_volatility ?? 0)}</b><em>After horizon and evidence adjustments</em></span>
              <span><small>VERIFIED FOLDS</small><b>{comparison?.fold_count ?? 0}</b><em>Strict walk-forward only</em></span>
            </div>
          </article>
          {figures.length > 0 && (
            <article className="panel institutional-panel" aria-labelledby="institutional-heading">
              <header><span id="institutional-heading">INSTITUTIONAL CONTEXT</span><small>Official portraits · not candidate assumptions</small></header>
              <div>
                {figures.map((figure) => (
                  <a href={figure.source} key={figure.name} rel="noreferrer">
                    <Image alt={figure.name} height={180} src={publicAsset(figure.portrait)} width={180} />
                    <span><b>{figure.name}</b><small>{figure.role}</small><em>{figure.credit}</em></span>
                  </a>
                ))}
              </div>
              <p>Portraits identify current institutional actors only. The forecast remains coalition-level until candidature is officially verified.</p>
            </article>
          )}
          <article className="panel history-panel" aria-labelledby="history-heading">
            <header><h2 id="history-heading">{t("forecast.history")}</h2><small>Snapshot replay</small></header>
            <div className="history-list">
              {history.slice(0, 5).map((snapshot, index) => (
                <a href={publicEndpoint(`/v1/forecast-snapshots/${snapshot.id}`)} key={snapshot.id}>
                  <time>{formatDateTime(snapshot.published_at)}</time>
                  <b>{snapshot.model_family.replaceAll("_", " ")}</b>
                  <span>{index === 0 ? "LATEST VALID" : "ARCHIVED"} · {snapshot.data_quality}</span>
                </a>
              ))}
              {history.length < 2 && (
                <p>Historical comparison activates after a second immutable publication.</p>
              )}
            </div>
          </article>
          <article className="panel source-ledger-panel" aria-labelledby="source-ledger-heading">
            <header><h2 id="source-ledger-heading">{t("forecast.sources")}</h2><small>{detail.election.sources?.length ?? 0} records</small></header>
            <div>
              {(detail.election.sources ?? []).map((source) => (
                <a href={source.url} key={source.url} rel="noreferrer">
                  <b>{source.label}</b><small>{source.authority} · {source.license}</small>
                </a>
              ))}
            </div>
          </article>
          {coalitions && (
            <article className="panel coalition-panel" aria-labelledby="coalition-heading">
              <header><span id="coalition-heading">{t("forecast.coalition")}</span><small>{coalitions.majority} seats for a majority</small></header>
              <div className="coalition-builder" role="group" aria-label="Select coalition members">
                {detail.election.contestants.map((contestant) => {
                  const selected = coalitionSelection.includes(contestant.id);
                  return (
                    <button
                      aria-pressed={selected}
                      key={contestant.id}
                      onClick={() => setCoalitionSelection((current) => (
                        current.includes(contestant.id)
                          ? current.filter((id) => id !== contestant.id)
                          : [...current, contestant.id]
                      ))}
                      style={{ "--party": contestant.color } as React.CSSProperties}
                      type="button"
                    >
                      <i />{contestant.short_name}
                    </button>
                  );
                })}
              </div>
              <div className="coalition-result" aria-live="polite">
                {coalitionOutcome ? (
                  <>
                    <div><small>MAJORITY PROBABILITY</small><b>{pct(coalitionOutcome.majority_probability)}</b></div>
                    <meter min="0" max="1" value={coalitionOutcome.majority_probability}>{pct(coalitionOutcome.majority_probability)}</meter>
                    <p>Median {coalitionOutcome.seats_median} seats · 90% interval {coalitionOutcome.seats_low}–{coalitionOutcome.seats_high}</p>
                  </>
                ) : <p>Select two or more parties matching a modeled coalition.</p>}
              </div>
            </article>
          )}
        </section>

        <aside className="insight-rail">
          <article className="mini-panel model-card">
            <span>MODEL PULSE</span><div className="pulse-ring"><b>{forecast.data_quality}</b><small>QUALITY</small></div>
            <p>{formatNumber(forecast.simulation_count)} scenarios processed with reproducible seed.</p>
            <small>{forecast.model_family.replaceAll("_", " ").toUpperCase()}</small>
          </article>
          <article className="mini-panel">
            <span>UNCERTAINTY WATCH</span>
            <h3>Early-cycle variance remains dominant.</h3>
            <p>Candidate field and polling inputs are unresolved. Structural priors carry most weight.</p>
            <small>UPDATED {formatDate(forecast.as_of)}</small>
          </article>
          <article className="mini-panel methodology">
            <span>TRANSPARENCY</span>
            <div><b>1M</b><small>SIMULATIONS</small></div>
            <div><b>{forecast.drivers.length}</b><small>ACTIVE DRIVERS</small></div>
            <div><b>{forecast.input_provenance.length}</b><small>MODEL INPUT SOURCES</small></div>
            <Link href="/methodology">OPEN METHODOLOGY →</Link>
            <a href={apiUrl ? `${apiUrl}/docs` : publicAsset("/data/openapi-v1.json")}>OPEN API SCHEMA →</a>
          </article>
        </aside>
      </main>

      <footer className="footer">
        <span>SDCOFA ELECTION DESK / MODEL {forecast.model_version}</span>
        <p>Decision intelligence by SDCofA · Part of <a href="https://github.com/MonarchCastleTech" rel="noreferrer">Monarch Castle Technologies</a>.</p>
        <span>AS OF {formatDateTime(forecast.as_of)}</span>
      </footer>
    </div>
  );
}

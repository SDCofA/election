"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";

import type { components } from "@elexion/contracts";
import { FlagIcon } from "@/components/flag-icon";
import { formatDate } from "@/lib/i18n";
import { publicAsset, publicEndpoint } from "@/lib/public-data";

type Election = components["schemas"]["Election"];
type Jurisdiction = components["schemas"]["Jurisdiction"];
type CatalogStatus = components["schemas"]["CatalogStatus"];

export function CalendarDirectory() {
  const [elections, setElections] = useState<Election[]>([]);
  const [jurisdictions, setJurisdictions] = useState<Jurisdiction[]>([]);
  const [status, setStatus] = useState<CatalogStatus | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetch(publicEndpoint("/v1/elections"), { signal: controller.signal }),
      fetch(publicEndpoint("/v1/jurisdictions"), { signal: controller.signal }),
      fetch(publicEndpoint("/v1/catalog/status"), { signal: controller.signal }),
    ])
      .then(async ([electionResponse, jurisdictionResponse, statusResponse]) => {
        if (![electionResponse, jurisdictionResponse, statusResponse].every((item) => item.ok)) {
          throw new Error("Catalog request failed");
        }
        const [electionData, jurisdictionData, statusData] = await Promise.all([
          electionResponse.json() as Promise<Election[]>,
          jurisdictionResponse.json() as Promise<Jurisdiction[]>,
          statusResponse.json() as Promise<CatalogStatus>,
        ]);
        setElections(electionData);
        setJurisdictions(jurisdictionData);
        setStatus(statusData);
      })
      .catch((requestError: unknown) => {
        if (!(requestError instanceof DOMException && requestError.name === "AbortError")) {
          setError(true);
        }
      });
    return () => controller.abort();
  }, []);

  const entries = useMemo(() => {
    const byJurisdiction = new Map<string, Election>();
    elections.forEach((election) => {
      const current = byJurisdiction.get(election.jurisdiction_id);
      if (!current || (!current.election_date && election.election_date)) {
        byJurisdiction.set(election.jurisdiction_id, election);
      }
    });
    const normalized = query.trim().toLocaleLowerCase();
    return jurisdictions
      .map((jurisdiction) => ({ jurisdiction, election: byJurisdiction.get(jurisdiction.id) }))
      .filter(({ election, jurisdiction }) => {
        if (!normalized) return true;
        return `${jurisdiction.name} ${jurisdiction.iso3} ${jurisdiction.region} ${election?.name ?? ""} ${election?.system ?? ""}`
          .toLocaleLowerCase()
          .includes(normalized);
      })
      .sort((a, b) => a.jurisdiction.name.localeCompare(b.jurisdiction.name));
  }, [elections, jurisdictions, query]);

  return (
    <main className="calendar-directory-page">
      <header className="calendar-directory-header">
        <div className="directory-brand-row">
          <Link className="directory-brand" href="/" aria-label="SDCofA Election Desk home">
            <Image alt="Strategic Data Company of Ankara" height={145} src={publicAsset("/brand/sdcofa-logo.png")} width={360} priority />
            <b>ELECTION DESK</b>
          </Link>
          <nav className="calendar-directory-nav" aria-label="Directory navigation">
            <Link href="/">FORECAST DESK</Link>
            <Link href="/methodology">METHODOLOGY</Link>
          </nav>
        </div>
        <span>G20 ELECTION DIRECTORY / SDCofA</span>
        <h1>G20 countries only.</h1>
        <p>The 19 sovereign G20 countries appear alphabetically. Regional bodies are excluded. Every country has a sourced national election-status record; forecasts publish only where an electoral event and defensible probability target exist.</p>
        <div>
          <b>{status?.total_jurisdictions ?? jurisdictions.length}</b><small>LISTED</small>
          <b>{status?.sourced_calendars ?? elections.length}</b><small>SOURCED RECORDS</small>
          <b>{status?.forecast_ready ?? 0}</b><small>FORECAST READY</small>
          <b>{status?.calendar_only ?? 0}</b><small>CALENDAR ONLY</small>
        </div>
      </header>
      <label className="calendar-search">
        <span>SEARCH G20 COUNTRIES</span>
        <input
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Country or election system"
          type="search"
          value={query}
        />
      </label>
      {error ? (
        <p className="calendar-directory-error" role="alert">Election directory unavailable. No substitute data shown.</p>
      ) : (
        <section className="calendar-directory-grid" aria-label="Election calendar records">
          {entries.map(({ election, jurisdiction }) => {
            const content = (
              <>
              <i><FlagIcon code={jurisdiction.flag} label={jurisdiction.name} /></i>
              <span>
                <strong>{jurisdiction.name}</strong>
                <small>{election ? `${election.name} · ${election.system.replaceAll("_", " ")}` : `${jurisdiction.iso3} · CATALOG LISTING`}</small>
              </span>
              <em>
                {election?.election_date
                  ? formatDate(`${election.election_date}T00:00:00Z`, { dateStyle: "medium", timeZone: "UTC" })
                  : election ? "TBD" : "LISTED"}
              </em>
              </>
            );
            return election ? (
              <Link href={`/elections/${election.id}`} key={jurisdiction.id}>{content}</Link>
            ) : (
              <article key={jurisdiction.id}>{content}</article>
            );
          })}
        </section>
      )}
    </main>
  );
}

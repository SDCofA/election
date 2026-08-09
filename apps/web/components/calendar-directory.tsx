"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import type { components } from "@elexion/contracts";
import { FlagIcon } from "@/components/flag-icon";
import { formatDate } from "@/lib/i18n";
import { publicEndpoint } from "@/lib/public-data";

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
    const byId = new Map(jurisdictions.map((item) => [item.id, item]));
    const normalized = query.trim().toLocaleLowerCase();
    return elections
      .map((election) => ({ election, jurisdiction: byId.get(election.jurisdiction_id) }))
      .filter(({ election, jurisdiction }) => {
        if (!normalized) return true;
        return `${jurisdiction?.name ?? ""} ${election.name} ${election.system}`
          .toLocaleLowerCase()
          .includes(normalized);
      });
  }, [elections, jurisdictions, query]);

  return (
    <main className="calendar-directory-page">
      <header className="calendar-directory-header">
        <Link href="/">← SDCOFA ELECTION DESK</Link>
        <span>GLOBAL ELECTION DIRECTORY / SDCofA</span>
        <h1>Every covered jurisdiction</h1>
        <p>Known dates appear first. TBD records link only to official authorities and remain mechanics-blocked—never silently forecast.</p>
        <div>
          <b>{status?.sourced_calendars ?? elections.length}</b><small>SOURCED RECORDS</small>
          <b>{status?.forecast_ready ?? 0}</b><small>FORECAST READY</small>
          <b>{status?.mechanics_blocked ?? 0}</b><small>MECHANICS BLOCKED</small>
        </div>
      </header>
      <label className="calendar-search">
        <span>SEARCH JURISDICTIONS</span>
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
          {entries.map(({ election, jurisdiction }) => (
            <Link href={`/elections/${election.id}`} key={election.id}>
              <i><FlagIcon code={jurisdiction?.flag ?? election.jurisdiction_id.slice(0, 2)} label={jurisdiction?.name} /></i>
              <span>
                <strong>{jurisdiction?.name ?? election.jurisdiction_id}</strong>
                <small>{election.name} · {election.system.replaceAll("_", " ")}</small>
              </span>
              <em>
                {election.election_date
                  ? formatDate(`${election.election_date}T00:00:00Z`, { dateStyle: "medium", timeZone: "UTC" })
                  : "TBD"}
              </em>
            </Link>
          ))}
        </section>
      )}
    </main>
  );
}

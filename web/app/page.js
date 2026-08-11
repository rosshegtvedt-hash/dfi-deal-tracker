"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

// Fixed color per institution (dataviz reference palette, validated for both
// modes). Color follows the entity — filtering never repaints survivors.
// Every institution in the data — drives the filter, stats and table.
const INSTITUTIONS = ["IFC", "EBRD", "DFC", "IDB Invest", "ADB", "AfDB", "BII",
                      "FMO", "Proparco", "EIB Global"];

// The categorical palette has exactly 8 slots and a 9th series never gets an
// invented hue, so the stacked time series colours the SEVEN LARGEST
// institutions by committed USD and groups the rest into a fixed "Other".
// Membership is hardcoded (not computed at runtime), so filtering can never
// repaint a survivor; it is revised only when a loader is added. Everything
// else on the page still shows all ten institutions separately.
const OTHER_SERIES = "Other (ADB, Proparco, FMO)";
const FOLDED_INTO_OTHER = new Set(["ADB", "Proparco", "FMO"]);
const CHART_SERIES = ["IFC", "EBRD", "AfDB", "EIB Global", "BII", "DFC",
                      "IDB Invest", OTHER_SERIES];
const seriesFor = (institution) =>
  FOLDED_INTO_OTHER.has(institution) ? OTHER_SERIES : institution;

const COLORS = {
  light: { IFC: "#2a78d6", EBRD: "#1baf7a", DFC: "#eda100", "IDB Invest": "#008300", "EIB Global": "#4a3aa7", AfDB: "#e34948", BII: "#e87ba4", [OTHER_SERIES]: "#eb6834" },
  dark:  { IFC: "#3987e5", EBRD: "#199e70", DFC: "#c98500", "IDB Invest": "#008300", "EIB Global": "#9085e9", AfDB: "#e66767", BII: "#d55181", [OTHER_SERIES]: "#d95926" },
};
const CHROME = {
  light: { grid: "#e1e0d9", muted: "#898781", ink2: "#52514e", surface: "#fcfcfb", bar: "#2a78d6" },
  dark:  { grid: "#2c2c2a", muted: "#898781", ink2: "#c3c2b7", surface: "#1a1a19", bar: "#3987e5" },
};
const TABLE_LIMIT = 200;

const fmtUSD = (v) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  return `$${(v / 1e6).toFixed(1)}M`;
};
const fmtBn = (v) => `$${v.toFixed(v >= 10 ? 0 : 1)}B`;

function useDarkMode() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(mq.matches);
    const onChange = (e) => setDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return dark;
}

function MultiSelect({ label, options, selected, onChange }) {
  const summary = selected.length ? `${label} (${selected.length})` : label;
  const toggle = (opt) =>
    onChange(selected.includes(opt) ? selected.filter((o) => o !== opt) : [...selected, opt]);
  return (
    <details>
      <summary>{summary} ▾</summary>
      <div className="dropdown">
        {selected.length > 0 && (
          <button className="clear" onClick={() => onChange([])}>Clear selection</button>
        )}
        {options.map((opt) => (
          <label key={opt}>
            <input type="checkbox" checked={selected.includes(opt)} onChange={() => toggle(opt)} />
            {opt}
          </label>
        ))}
      </div>
    </details>
  );
}

// Mirror of the pipeline's dedupe rule: keep each probable co-financing
// group's largest single commitment so one deal counts once.
function excludeDuplicates(rows) {
  const best = new Map();
  for (const r of rows) {
    if (!r.dup) continue;
    const prev = best.get(r.dup);
    if (!prev || (r.amount_usd ?? -1) > (prev.amount_usd ?? -1)) best.set(r.dup, r);
  }
  return rows.filter((r) => !r.dup || best.get(r.dup) === r);
}

export default function Page() {
  const dark = useDarkMode();
  const palette = dark ? COLORS.dark : COLORS.light;
  const chrome = dark ? CHROME.dark : CHROME.light;

  const [data, setData] = useState(null);
  const [inst, setInst] = useState([]);
  const [region, setRegion] = useState([]);
  const [country, setCountry] = useState([]);
  const [sector, setSector] = useState([]);
  const [instrument, setInstrument] = useState([]);
  const [yearFrom, setYearFrom] = useState(null);
  const [yearTo, setYearTo] = useState(null);
  const [includeUndated, setIncludeUndated] = useState(true);
  const [excludeDupes, setExcludeDupes] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetch("/data.json")
      .then((r) => r.json())
      .then((raw) => {
        const rows = raw.rows.map((r) =>
          Object.fromEntries(raw.columns.map((c, i) => [c, r[i]])));
        setData({ rows, asOf: raw.as_of });
      });
  }, []);

  const options = useMemo(() => {
    if (!data) return null;
    const uniq = (key) =>
      [...new Set(data.rows.map((r) => r[key]).filter(Boolean))].sort();
    const years = data.rows.map((r) => r.year).filter((y) => y != null);
    return {
      region: uniq("region"), country: uniq("country"), sector: uniq("sector"),
      instrument: uniq("instrument"),
      yearMin: Math.min(...years), yearMax: Math.max(...years),
    };
  }, [data]);

  const view = useMemo(() => {
    if (!data) return [];
    let rows = data.rows;
    if (excludeDupes) rows = excludeDuplicates(rows);
    if (inst.length) rows = rows.filter((r) => inst.includes(r.institution));
    if (region.length) rows = rows.filter((r) => region.includes(r.region));
    if (country.length) rows = rows.filter((r) => country.includes(r.country));
    if (sector.length) rows = rows.filter((r) => sector.includes(r.sector));
    if (instrument.length) rows = rows.filter((r) => instrument.includes(r.instrument));
    const lo = yearFrom ?? options.yearMin, hi = yearTo ?? options.yearMax;
    rows = rows.filter((r) =>
      r.year == null ? includeUndated : r.year >= lo && r.year <= hi);
    return rows;
  }, [data, options, inst, region, country, sector, instrument,
      yearFrom, yearTo, includeUndated, excludeDupes]);

  const stats = useMemo(() => {
    const amounts = view.filter((r) => r.amount_usd != null);
    const total = amounts.reduce((s, r) => s + r.amount_usd, 0);
    return {
      total, deals: view.length,
      avg: amounts.length ? total / amounts.length : null,
      noAmount: view.length - amounts.length,
    };
  }, [view]);

  const byYear = useMemo(() => {
    const acc = new Map();
    for (const r of view) {
      if (r.year == null || r.amount_usd == null) continue;
      if (!acc.has(r.year)) acc.set(r.year, { year: r.year });
      const bucket = acc.get(r.year);
      const key = seriesFor(r.institution);
      bucket[key] = (bucket[key] || 0) + r.amount_usd / 1e9;
    }
    return [...acc.values()].sort((a, b) => a.year - b.year);
  }, [view]);

  const topOf = (key, n, excludeRegional) => {
    const acc = new Map();
    for (const r of view) {
      const k = r[key];
      if (!k || r.amount_usd == null) continue;
      if (excludeRegional && /^(Regional|Undisclosed|Unclassified)/.test(k)) continue;
      acc.set(k, (acc.get(k) || 0) + r.amount_usd / 1e9);
    }
    return [...acc.entries()].map(([name, bn]) => ({ name, bn }))
      .sort((a, b) => b.bn - a.bn).slice(0, n);
  };
  const topCountries = useMemo(() => topOf("country", 15, true), [view]);
  const bySector = useMemo(() => topOf("sector", 99, false), [view]);

  const tableRows = useMemo(() => {
    let rows = view;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((r) =>
        (r.name || "").toLowerCase().includes(q) ||
        (r.sponsor || "").toLowerCase().includes(q));
    }
    return [...rows].sort((a, b) =>
      (b.year ?? -1) - (a.year ?? -1) || (b.amount_usd ?? -1) - (a.amount_usd ?? -1));
  }, [view, search]);

  if (!data || !options) {
    return <main className="shell"><p className="sub">Loading deal data…</p></main>;
  }

  const years = [];
  for (let y = options.yearMin; y <= options.yearMax; y++) years.push(y);
  const axisProps = {
    stroke: chrome.grid, tick: { fill: chrome.muted, fontSize: 12 },
    tickLine: false, axisLine: { stroke: chrome.grid },
  };
  const tooltipStyle = {
    contentStyle: {
      background: chrome.surface, border: `1px solid ${chrome.grid}`,
      borderRadius: 8, color: chrome.ink2, fontSize: 12,
    },
  };

  return (
    <main className="shell">
      <h1>DFI Deal Flow Tracker</h1>
      <p className="sub">
        Development finance commitments from public disclosures · data as of {data.asOf} ·
        cumulative disclosed operations — coverage periods differ by institution (see notes below)
      </p>

      <div className="filters">
        <MultiSelect label="Institution" options={INSTITUTIONS} selected={inst} onChange={setInst} />
        <MultiSelect label="Region" options={options.region} selected={region} onChange={setRegion} />
        <MultiSelect label="Country" options={options.country} selected={country} onChange={setCountry} />
        <MultiSelect label="Sector" options={options.sector} selected={sector} onChange={setSector} />
        <MultiSelect label="Instrument" options={options.instrument} selected={instrument} onChange={setInstrument} />
        <span className="year-picks">
          <select value={yearFrom ?? options.yearMin} onChange={(e) => setYearFrom(+e.target.value)}>
            {years.map((y) => <option key={y}>{y}</option>)}
          </select>
          –
          <select value={yearTo ?? options.yearMax} onChange={(e) => setYearTo(+e.target.value)}>
            {years.map((y) => <option key={y}>{y}</option>)}
          </select>
        </span>
        <label className="check">
          <input type="checkbox" checked={excludeDupes}
                 onChange={(e) => setExcludeDupes(e.target.checked)} />
          Exclude probable duplicates
        </label>
        <label className="check">
          <input type="checkbox" checked={includeUndated}
                 onChange={(e) => setIncludeUndated(e.target.checked)} />
          Include undated deals
        </label>
      </div>

      <div className="tiles">
        <div className="tile">
          <div className="label">Total commitments</div>
          <div className="value">{fmtUSD(stats.total)}</div>
        </div>
        <div className="tile">
          <div className="label">Deals</div>
          <div className="value">{stats.deals.toLocaleString()}</div>
        </div>
        <div className="tile">
          <div className="label">Average ticket</div>
          <div className="value">{fmtUSD(stats.avg)}</div>
        </div>
      </div>
      {stats.noAmount > 0 && (
        <p className="note">
          {stats.noAmount.toLocaleString()} deals have no disclosed amount — counted in deal
          totals but not in dollar figures.
        </p>
      )}

      <div className="card">
        <h2>Commitments over time (US$ bn)</h2>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={byYear} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={chrome.grid} />
            <XAxis dataKey="year" {...axisProps} interval={0}
                   tickFormatter={(y) => (y % 5 === 0 ? y : "")} />
            <YAxis {...axisProps} width={36} />
            <Tooltip {...tooltipStyle} formatter={(v, n) => [fmtBn(v), n]}
                     cursor={{ fill: chrome.grid, opacity: 0.35 }} />
            <Legend wrapperStyle={{ fontSize: 12, color: chrome.ink2 }} />
            {CHART_SERIES.map((i) => (
              <Bar key={i} dataKey={i} stackId="a" fill={palette[i]}
                   stroke={chrome.surface} strokeWidth={1} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="two-col">
        <div className="card">
          <h2>Top countries (US$ bn)</h2>
          <ResponsiveContainer width="100%" height={420}>
            <BarChart data={topCountries} layout="vertical"
                      margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid horizontal={false} stroke={chrome.grid} />
              <XAxis type="number" {...axisProps} />
              <YAxis type="category" dataKey="name" {...axisProps} width={120} />
              <Tooltip {...tooltipStyle} formatter={(v) => [fmtBn(v), "Committed"]}
                       cursor={{ fill: chrome.grid, opacity: 0.35 }} />
              <Bar dataKey="bn" fill={chrome.bar} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <p className="note">
            Country-specific deals only; regional/multi-country operations excluded.
          </p>
        </div>
        <div className="card">
          <h2>Sector breakdown (US$ bn)</h2>
          <ResponsiveContainer width="100%" height={440}>
            <BarChart data={bySector} layout="vertical"
                      margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid horizontal={false} stroke={chrome.grid} />
              <XAxis type="number" {...axisProps} />
              <YAxis type="category" dataKey="name" {...axisProps} width={160} />
              <Tooltip {...tooltipStyle} formatter={(v) => [fmtBn(v), "Committed"]}
                       cursor={{ fill: chrome.grid, opacity: 0.35 }} />
              <Bar dataKey="bn" fill={chrome.bar} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <h2>Deals</h2>
        <input className="search" placeholder="Search project name or sponsor…"
               value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Institution</th><th>Project</th><th>Country</th><th>Sector</th>
                <th>Instrument</th><th style={{ textAlign: "right" }}>US$ m</th>
                <th>Year</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {tableRows.slice(0, TABLE_LIMIT).map((r, i) => (
                <tr key={i}>
                  <td>{r.institution}</td>
                  <td>{r.name}</td>
                  <td>{r.country}</td>
                  <td>{r.sector}</td>
                  <td>{r.instrument}</td>
                  <td className="num">
                    {r.amount_usd == null ? "—" : (r.amount_usd / 1e6).toLocaleString(undefined, { maximumFractionDigits: 1 })}
                  </td>
                  <td>{r.year ?? "—"}</td>
                  <td>{r.status}</td>
                  <td>{r.url ? <a href={r.url} target="_blank" rel="noreferrer">View</a> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">
          Showing {Math.min(TABLE_LIMIT, tableRows.length)} of {tableRows.length.toLocaleString()} deals
          {tableRows.length > TABLE_LIMIT ? " — refine filters or search to narrow down." : "."}
        </p>
      </div>

      <footer>
        <p>
          <strong>Notes:</strong> coverage periods differ by institution — IFC (~1994→),
          EBRD (1991→), IDB Invest (1989→), AfDB (1967→) and BII (2003→) disclose
          cumulative history including completed deals; DFC covers currently-active
          projects only; ADB non-sovereign covers 2004→. EBRD and AfDB include
          state/sovereign operations (flagged per record); the others are private-sector
          only. <strong>EIB Global is a deliberate subset of EIB</strong> — only its
          operations outside the EU are included, and its rows are loan tranches
          rather than projects, so its deal count is not comparable with the others.
          <strong>Proparco&apos;s coverage is systematically incomplete</strong> —
          AFD publishes only projects signed since 1 January 2014 whose clients
          authorised disclosure, so its totals are a floor, not a complete picture.
          Amounts are each institution&apos;s own commitment converted to US dollars
          (ECB annual-average rates; IMF SDR rates for AfDB&apos;s Units of Account);
          BII figures are lifetime commitment totals per activity rather than single
          approvals. <strong>FMO here is not FMO&apos;s own investment portfolio</strong> —
          its IATI publication covers the Dutch government funds it manages (MASSIF,
          Building Prospects, AEF-I and others), including technical-assistance
          contracts, so its counts and countries are not comparable with the other
          institutions&apos;. Probable duplicates are fuzzy-matched co-financing leads;
          the toggle keeps each group&apos;s largest single commitment.
        </p>
        <p>
          Source: public project disclosures of DFC, IFC (via WBG Finances One), EBRD,
          IDB Invest, ADB, AfDB (MapAfrica), BII and FMO (IATI), Proparco (AFD open
          data) and EIB Global · compiled by RCFH Advisory · DFI Deal Flow Tracker
        </p>
      </footer>
    </main>
  );
}

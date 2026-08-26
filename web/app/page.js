"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis, Cell,
} from "recharts";

// Every institution in the data — drives the filter, stats and table.
const INSTITUTIONS = ["IFC", "EBRD", "DFC", "IDB Invest", "ADB", "AfDB", "BII",
                      "FMO", "Proparco", "EIB Global"];

// Only SIX categorical hues clear the CVD, normal-vision and lightness checks
// together at all-pairs (verified with the dataviz validator; an 8-hue set
// fails — magenta/orange are indistinguishable even with full colour vision,
// and green/orange fail CVD). So the six largest institutions by committed USD
// get a fixed hue each and the rest share a neutral "Other". Membership is
// hardcoded, not computed at runtime, so filtering can never repaint a
// survivor. Everything else on the page still shows all ten separately.
const OTHER_SERIES = "Other DFIs";
const FOLDED_INTO_OTHER = new Set(["BII", "ADB", "Proparco", "FMO"]);
const CHART_SERIES = ["IFC", "EBRD", "AfDB", "EIB Global", "IDB Invest", "DFC",
                      OTHER_SERIES];
const seriesFor = (institution) =>
  FOLDED_INTO_OTHER.has(institution) ? OTHER_SERIES : institution;

// Bathymetric. Depth carries magnitude and the ramp encodes an ordering;
// a single flat fill across every bar is not an option in this system.
// Light ground stops at Silver (Ice on Chart white nearly vanishes); the dark
// ground reverses and stops before Trench for the mirror-image reason.
const RAMP_LIGHT = ["#0E2A3F", "#2E6187", "#7FA3BC", "#B7C8D3", "#E2E9ED"];
const RAMP_DARK = ["#E2E9ED", "#B7C8D3", "#7FA3BC", "#2E6187", "#0E2A3F"];

// n colours interpolated along the ramp, so a fifteen-row table still reads
// as one ordering rather than a repeat.
function ramp(n, dark, full = false) {
  const stops = (dark ? RAMP_DARK : RAMP_LIGHT).slice(0, full ? 5 : 4);
  if (n <= 1) return [stops[0]];
  const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const out = [];
  for (let i = 0; i < n; i++) {
    const t = (i / (n - 1)) * (stops.length - 1);
    const lo = Math.floor(t), hi = Math.min(lo + 1, stops.length - 1);
    const f = t - lo, a = hex(stops[lo]), b = hex(stops[hi]);
    const mix = a.map((v, k) => Math.round(v + (b[k] - v) * f));
    out.push("#" + mix.map((v) => v.toString(16).padStart(2, "0")).join(""));
  }
  return out;
}

const CHROME = {
  light: { grid: "#D6DEE3", muted: "#5D6C77", ink2: "#2A3540",
           surface: "#FFFFFF", brass: "#A8853F" },
  dark:  { grid: "#24323C", muted: "#8C9BA6", ink2: "#B7C8D3",
           surface: "#12212C", brass: "#C9A45A" },
};
const ALL_TEN = ["DFC", "IFC", "EBRD", "IDB Invest", "ADB", "AfDB", "BII",
                 "FMO", "Proparco", "EIB Global"];
const TABLE_LIMIT = 200;

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];
// 2026-08-20 -> 20 August 2026. The house style runs dates long form.
const longDate = (iso) => {
  if (!iso || iso.length < 10) return iso || "";
  return `${+iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}`;
};

const fmtUSD = (v) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  return `$${(v / 1e6).toFixed(1)}M`;
};
const fmtBn = (v) => `$${v.toFixed(v >= 10 ? 0 : 1)}B`;

// Effective theme, not just the operating system's. An explicit choice wins,
// and is remembered; with no choice stored we follow the OS and keep
// following it if the user changes it mid-session.
const THEME_KEY = "rcfh-theme";

function readStored() {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "dark" || t === "light" ? t : null;
  } catch (e) {
    return null;           // private windows can throw on localStorage
  }
}

function useTheme() {
  // Start light so server and first client render agree; the pre-paint script
  // in layout.js has already set data-theme, so nothing visibly flips.
  const [choice, setChoice] = useState(null);
  const [osDark, setOsDark] = useState(false);

  useEffect(() => {
    setChoice(readStored());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setOsDark(mq.matches);
    const onChange = (e) => setOsDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const dark = choice ? choice === "dark" : osDark;

  // Reads the LIVE theme off the document rather than the closure's `dark`,
  // so two clicks in one tick cannot both act on the same stale value.
  const toggle = () => {
    const root = document.documentElement;
    const current = root.getAttribute("data-theme")
      || (window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    setChoice(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (e) {
      /* the choice still applies for this page view */
    }
  };

  return [dark, toggle];
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
  const [dark, toggleTheme] = useTheme();
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
        (r.counterparty || "").toLowerCase().includes(q));
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
      <div className="band">
        <span className="wordmark">RCFH ADVISORY</span>
        <span className="right">
          <span className="series">DFI DEAL FLOW TRACKER</span>
          <button className="theme-toggle" onClick={toggleTheme}
                  aria-label={`Switch to ${dark ? "light" : "dark"} mode`}>
            {dark ? "LIGHT" : "DARK"}
          </button>
        </span>
      </div>
      <div className="brass-rule" />
      <h1>DFI Deal Flow Tracker</h1>
      <p className="sub">
        Development finance commitments from public disclosures · data as of {longDate(data.asOf)} ·
        cumulative disclosed operations — coverage periods differ by institution (see notes below)
      </p>

      {/* Coverage runs on every view, including the unfiltered one. A strip
          that appears only when something is missing trains the reader to
          ignore it, so it is always present and always live. */}
      <div className="coverage">
        <span className="label">COVERAGE</span>
        {ALL_TEN.map((i) => {
          const shown = inst.length === 0 || inst.includes(i);
          return (
            <span key={i} className={shown ? "chip in" : "chip out"}>{i}</span>
          );
        })}
      </div>
      <p className="coverage-key">
        Filled = in the current view. Outlined = filtered out. Coverage periods
        and completeness differ by institution; see the notes below.
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
            {CHART_SERIES.map((i, n) => (
              <Bar key={i} dataKey={i} stackId="a"
                   fill={ramp(CHART_SERIES.length, dark, true)[n]}
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
              <Bar dataKey="bn" radius={[0, 2, 2, 0]}>
                {topCountries.map((_, i) => (
                  <Cell key={i} fill={ramp(topCountries.length, dark)[i]} />
                ))}
              </Bar>
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
              <Bar dataKey="bn" radius={[0, 2, 2, 0]}>
                {bySector.map((_, i) => (
                  <Cell key={i} fill={ramp(bySector.length, dark)[i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card">
        <h2>Deals</h2>
        <input className="search" placeholder="Search project name or client…"
               value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Institution</th><th>Project</th><th>Client</th><th>Country</th><th>Sector</th>
                <th>Instrument</th><th style={{ textAlign: "right" }}>US$ m</th>
                <th>Year</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {tableRows.slice(0, TABLE_LIMIT).map((r, i) => (
                <tr key={i}>
                  <td>{r.institution}</td>
                  <td>{r.name}</td>
                  <td>
                    {r.counterparty || "—"}
                    {r.cp_derived ? (
                      <span className="derived" title="Derived from the project name — the source did not publish a client field">*</span>
                    ) : null}
                  </td>
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
          <p className="sub" style={{ marginTop: 10 }}>
            Client names marked <span className="derived">*</span> were derived from the project
            title because the institution publishes no client field. AfDB and EIB Global
            name projects rather than clients, so their deals show no client at all.
          </p>
        </div>
        <p className="note">
          Showing {Math.min(TABLE_LIMIT, tableRows.length)} of {tableRows.length.toLocaleString()} deals
          {tableRows.length > TABLE_LIMIT ? " — refine filters or search to narrow down." : "."}
        </p>
      </div>

      <footer>
        <div className="brass-hair" />
        <p className="notes-label">NOTES</p>
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
          <strong>FMO rows name their fund</strong> — &quot;Fund: FMO&quot; is FMO&apos;s
          own account, while MASSIF, Building Prospects and the rest are Dutch
          government funds it administers.
          Amounts are each institution&apos;s own commitment converted to US dollars
          (ECB annual-average rates; IMF SDR rates for AfDB&apos;s Units of Account);
          BII figures are lifetime commitment totals per activity rather than single
          approvals. Probable duplicates are fuzzy-matched co-financing leads;
          the toggle keeps each group&apos;s largest single commitment.
        </p>
        <p>
          Source: public project disclosures of DFC, IFC (via WBG Finances One), EBRD,
          IDB Invest, ADB, AfDB (MapAfrica), BII and FMO (IATI), Proparco (AFD open
          data) and EIB Global. FMO is its own account only.
          <br />Compiled by RCFH Advisory · DFI Deal Flow Tracker · Data as of{" "}
          {longDate(data.asOf)}
        </p>
        <p className="disclaimer">
          This piece reflects my own analysis. It does not constitute investment,
          legal, or tax advice.
        </p>
      </footer>
    </main>
  );
}

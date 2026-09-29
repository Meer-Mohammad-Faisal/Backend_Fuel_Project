# Fuel-price dataset analysis

## Scope and source

This document records the first implementation phase only. No Django application has been implemented yet.

Source inspected: `D:\Download\fuel-prices-for-be-assessment.csv` (UTF-8 with BOM handling, 8,151 data rows). The workspace was also inspected; `E:\Django_Assignement` is currently empty and is not a Git repository (`git status` reported that it is not a repository).

All counts below were calculated programmatically from the complete CSV. Duplicate comparisons described as “normalized” trim leading/trailing whitespace, collapse internal whitespace, and compare case-insensitively.

## Dataset statistics

| Metric | Result |
|---|---:|
| Data rows | 8,151 |
| Columns | 7 |
| Unique OPIS Truckstop IDs | 6,738 |
| Unique `(Address, City, State)` locations | 6,337 |
| Unique states/provinces | 57 |
| Unique Rack IDs | 306 |

Columns, in source order:

1. `OPIS Truckstop ID`
2. `Truckstop Name`
3. `Address`
4. `City`
5. `State`
6. `Rack ID`
7. `Retail Price`

### Inferred types

| Column | Observed type | Proposed application type |
|---|---|---|
| `OPIS Truckstop ID` | Integer-like text | `PositiveIntegerField` or string source identifier; preserve source value exactly |
| `Truckstop Name` | Text | `CharField` |
| `Address` | Text | `CharField` |
| `City` | Text | `CharField` |
| `State` | Text | `CharField(max_length=2)` with an explicit country/region interpretation |
| `Rack ID` | Integer-like text | String/integer source attribute; not a station key |
| `Retail Price` | Decimal-like numeric text | `DecimalField`, never binary float for persisted prices |

### Missing and parse quality

No column contains blank or whitespace-only values. All 8,151 retail prices parsed as numeric decimals. There are no non-positive retail prices.

Whitespace is present inside otherwise populated fields: 97 address values, 1,256 city values, and 3 truckstop names have leading/trailing whitespace. Import normalization should trim values while retaining the raw source values if auditability is important.

## Prices

Retail-price statistics, using all 8,151 rows and linear interpolation for percentiles:

| Statistic | Value |
|---|---:|
| Minimum | 2.68733333 |
| 1st percentile | 2.85900000 |
| 5th percentile | 2.95900000 |
| 25th percentile | 3.21566666 |
| Median | 3.43233333 |
| Mean | 3.4989739290 |
| 75th percentile | 3.69900000 |
| 95th percentile | 4.40630048 |
| 99th percentile | 4.90860199 |
| Maximum | 6.39900000 |

The source has no observation timestamp or price-effective date. Therefore, the CSV cannot prove which repeated value is “current”; an application must not silently label an arbitrary duplicate as current without a documented import policy.

## Duplicate and identity findings

| Comparison key | Duplicate groups | Excess rows beyond one per group |
|---|---:|---:|
| Full normalized record across all columns | 15 | 26 |
| Normalized OPIS Truckstop ID | 678 | 1,413 |
| Normalized `(Truckstop Name, Address)` | 493 | 1,193 |
| Normalized `(Truckstop Name, Address, City, State)` | 490 | 1,187 |

The OPIS ID is not unique in the file. Of the 6,738 IDs, 6,060 occur once, 381 occur twice, 99 occur three times, 63 occur four times, 30 occur five times, and 105 occur six times. The maximum rows for one ID is six.

There are 226 ID groups where the normalized station fields `(Truckstop Name, Address, City, State)` differ. Examples include ID `20` appearing as `PILOT TRAVEL CENTER #1243` and `PILOT #1243`, and ID `3221` appearing as `PILOT #1440` and `SOUTHERN TRAVEL PLAZA`. Many differences are naming aliases or singular/plural variants, but the data also contains meaningful-looking alias changes. This is a source-data issue, not evidence that every row is a different physical station.

There are 597 OPIS IDs with more than one distinct retail-price string. Because no timestamp exists, these must be retained as separate observations or resolved by an explicit deterministic import rule; they should not be overwritten silently.

Rack IDs are also not unique: only 306 unique Rack IDs exist, resulting in 7,845 excess rows. Rack ID therefore cannot identify a station.

## States and geography

The 57 two-letter values are:

`AB, AL, AR, AZ, BC, CA, CO, CT, DE, FL, GA, IA, ID, IL, IN, KS, KY, LA, MA, MB, MD, ME, MI, MN, MO, MS, MT, NB, NC, ND, NE, NH, NJ, NM, NS, NV, NY, OH, OK, ON, OR, PA, QC, RI, SC, SD, SK, TN, TX, UT, VA, VT, WA, WI, WV, WY, YT`.

This includes Canadian provinces (`AB`, `BC`, `MB`, `NB`, `NS`, `ON`, `QC`, `SK`, `YT`) as well as US states. There is no country column. The application should model the source region explicitly, or maintain a documented mapping from these values to country/region, rather than assuming all values are US states.

## Address usefulness and geocoding readiness

The address values are useful for route-oriented matching but are not conventional postal addresses:

- 7,986 of 8,151 rows contain a highway or exit signal (98.0%).
- 7,367 rows contain a recognizable route designator such as `I-`, `US-`, or `SR-` (90.4%).
- 4,605 rows contain the word `EXIT` (56.5%).
- 6,337 normalized `(Address, City, State)` locations are present.
- Example values include `I-44, EXIT 283 & US-69`, `US-46`, and `I-540, EXIT 12 & US-71`.

The file has no latitude, longitude, ZIP/postal code, street number, country, or formal address field. It is therefore not sufficient for deterministic exact geocoding on its own. The station name plus highway/exit/city/state can often identify a truck stop, but the result is provider-dependent and can be ambiguous. The Canadian values make an implicit US-only geocoder assumption unsafe.

## Proposed station representation

Use separate station identity and price-observation concepts:

### `Station`

- Internal database primary key (UUID or integer), independent of source IDs.
- `opis_truckstop_id` as a non-unique source attribute until the importer has resolved its aliases.
- Canonical `name`, `address`, `city`, `region_code`, and explicit `country_code`/region classification.
- Nullable `latitude` and `longitude`, with a database check that both are present together and are within valid ranges.
- Geocoding metadata: provider, query/input fingerprint, result quality, retrieved time, and optional raw provider reference.
- A uniqueness constraint on a documented normalized identity key, likely source ID plus normalized location, rather than on OPIS ID alone.

### `StationAlias` or source-row audit data

Keep alternate source names and the original source fields instead of destroying them during canonicalization. This is needed for the 226 conflicting ID groups and for reproducible imports.

### `FuelPriceObservation`

- Foreign key to `Station`.
- Decimal retail price.
- Source OPIS ID and Rack ID as imported attributes.
- Import batch/source-file identifier and source row number/hash.
- No `observed_at` should be invented from the CSV. If the application later receives dated feeds, add a real observation timestamp then.

This representation lets the API return a station once while preserving repeated prices and aliases. For an initial take-home import, a documented deterministic rule can select a display price per station (for example, the last source row in the import only if the assessment explicitly treats file order as authoritative); absent that requirement, the safer default is to expose the ambiguity or retain all observations.

## Proposed geocoding and routing strategy

### Options considered

1. **Geocode every row on every request:** rejected. It is slow, non-deterministic, expensive in request latency, and would repeat external calls.
2. **Bulk call a free public geocoder during every import:** rejected. Public services such as Nominatim have usage policies and rate limits; 6,337 locations is not an appropriate request burst. The source addresses are also incomplete, so failure rates may be high.
3. **Geocode only stations relevant to each route:** useful for reducing volume, but route relevance cannot be calculated reliably before stations have coordinates. It also creates unpredictable first-request latency.
4. **Generate coordinates locally without a real source:** rejected. Invented or centroid coordinates would produce misleading route results and violate the requirement not to hardcode example results.
5. **One-time, cached enrichment:** selected. Run a management command or separate import/enrichment job that attempts geocoding once per normalized station query, rate-limits requests, stores successful results and failures permanently, and never geocodes in the normal API request path.

### Selected approach

The application should import the CSV first with nullable coordinates, then run an explicitly configured enrichment command. The command should:

- build a stable query from station name, route-oriented address, city, region, and country;
- use a configurable free provider only when its policy permits this workload, with a descriptive User-Agent and conservative rate limiting;
- cache both successes and failures keyed by a normalized query/provider version;
- persist provider attribution, result quality, and the exact query;
- support retries only for transient errors and a dry-run/report mode;
- leave unresolved stations visible rather than fabricating coordinates; and
- allow replacing the provider later through an adapter interface.

For a reproducible take-home demonstration, the repository should not require network access to start, migrate, test, or serve non-routing endpoints. Coordinate enrichment should be opt-in and documented. A committed, provenance-traceable coordinate fixture may be added later only if it is generated from an allowed source and includes its licensing/attribution; it must not be synthetic.

Routing calls should likewise be isolated behind a provider adapter, configured by environment variables, and cached by normalized origin/destination/waypoint inputs. The route API should make at most one routing call for a cache miss, with timeouts and clear upstream-error handling. The exact routing provider is a later implementation decision because this phase has not yet inspected the assessment text or route contract.

## Assumptions

- Each CSV row is retained as source data until a later, explicit station/price import policy is agreed.
- OPIS IDs and Rack IDs are source identifiers, not automatically unique station keys.
- File order is not treated as recency because there is no timestamp requirement in the supplied data.
- Highway/exit descriptions are treated as geocoding hints, not exact coordinates.
- Canadian province codes are valid input and must not be rejected as invalid US states.
- The CSV is the authoritative input for this phase; no external API was called during analysis.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Duplicate IDs and aliases cause incorrect station merges | Use internal station keys, preserve aliases/source rows, and require explicit normalized identity rules |
| Multiple prices have no timestamp | Preserve observations and expose/resolve ambiguity deterministically only with a documented rule |
| Incomplete highway/exit addresses geocode inaccurately | Nullable coordinates, quality/status fields, cached results, review/reporting, and no fabricated fallback coordinates |
| Free geocoder usage limits or policy changes | Provider adapter, opt-in enrichment, rate limiting, persistent cache, and configurable provider |
| No country column | Derive and persist country/region classification from the observed code set with validation |
| Route results depend on external services | Cache route responses, set timeouts, handle upstream failures, and keep the API contract provider-neutral |
| Source formatting noise | Normalize for matching, trim imported values, and retain raw values/source-row hashes for auditability |

## Verification performed

The statistics in this document were checked against a fresh full-file parse after writing the document. The verification confirmed the row count, seven column names, no missing fields, duplicate counts, 57 region codes, 6,738 unique OPIS IDs, and all listed retail-price statistics. No application code was started in this phase.

## Phase handoff

Implemented: complete CSV inspection and this analysis document.

Files changed: `DATA_ANALYSIS.md` only (temporary audit helpers were removed after verification).

Checks performed: full CSV parse, type/blank/price validation, normalized duplicate analysis, station-ID conflict analysis, address-signal analysis, and document consistency verification.

Remaining risks: the precise route endpoint contract and assessment-specific acceptance criteria have not yet been inspected in this workspace; coordinates are not present in the source data; the workspace is not yet initialized as a Git repository.

Next command to run: `Get-ChildItem -Force; git status --short --branch` after the assessment files/repository are supplied or initialized, before application design begins.

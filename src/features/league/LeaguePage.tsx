import { useMemo, useState, type ReactNode } from "react";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Crown, Search, Trophy, UsersRound } from "lucide-react";
import type { LeagueManager } from "./types";
import { ManagerSquadDrawer } from "./ManagerSquadDrawer";
import "./league.css";

function compareNullableNumbers(a: number | null, b: number | null) {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  return a - b;
}

const columns: ColumnDef<LeagueManager>[] = [
  {
    accessorKey: "place",
    header: "Rang",
    sortingFn: (a, b) => compareNullableNumbers(a.original.place, b.original.place),
    cell: ({ row }) => (
      <span className={`league-rank${row.original.place === 1 ? " is-first" : ""}`}>
        {row.original.place ?? "—"}
      </span>
    ),
  },
  {
    accessorKey: "name",
    header: "Manager",
    cell: ({ row }) => (
      <div className="manager-cell">
        <span className="manager-cell__avatar" aria-hidden>
          {row.original.name.slice(0, 1).toUpperCase()}
        </span>
        <div className="manager-cell__name">
          <strong>{row.original.name}</strong>
          {row.original.isSelf ? <span className="manager-cell__self">DU</span> : null}
        </div>
      </div>
    ),
  },
  {
    accessorKey: "teamValue",
    header: "Teamwert",
    sortingFn: (a, b) => compareNullableNumbers(a.original.teamValue, b.original.teamValue),
    cell: ({ row }) => <NumericCell value={row.original.teamValue} format="currency" />,
  },
  {
    accessorKey: "profit",
    header: "Profit",
    sortingFn: (a, b) => compareNullableNumbers(a.original.profit, b.original.profit),
    cell: ({ row }) => <SignedCurrency value={row.original.profit} />,
  },
  {
    accessorKey: "points",
    header: "Punkte",
    sortingFn: (a, b) => compareNullableNumbers(a.original.points, b.original.points),
    cell: ({ row }) => <NumericCell value={row.original.points} />,
  },
  {
    accessorKey: "currentMatchdayPoints",
    header: "ST-Pkt.",
    sortingFn: (a, b) => compareNullableNumbers(a.original.currentMatchdayPoints, b.original.currentMatchdayPoints),
    cell: ({ row }) => <NumericCell value={row.original.currentMatchdayPoints} />,
  },
  {
    accessorKey: "averagePoints",
    header: "Ø Pkt.",
    sortingFn: (a, b) => compareNullableNumbers(a.original.averagePoints, b.original.averagePoints),
    cell: ({ row }) => <NumericCell value={row.original.averagePoints} decimals={1} />,
  },
  {
    accessorKey: "matchdayWins",
    header: "ST-Siege",
    sortingFn: (a, b) => compareNullableNumbers(a.original.matchdayWins, b.original.matchdayWins),
    cell: ({ row }) => <NumericCell value={row.original.matchdayWins} />,
  },
];

export function LeaguePage({
  managers,
  leagueId,
}: {
  managers: LeagueManager[];
  leagueId: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "place", desc: false }]);
  const [query, setQuery] = useState("");
  const [selectedManager, setSelectedManager] = useState<LeagueManager | null>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("de-DE");
    return needle
      ? managers.filter((manager) => manager.name.toLocaleLowerCase("de-DE").includes(needle))
      : managers;
  }, [managers, query]);

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const stats = useMemo(() => {
    const values = managers.map((manager) => manager.teamValue).filter(isNumber);
    const leader = [...managers]
      .filter((manager) => manager.place != null)
      .sort((a, b) => (a.place ?? 999999) - (b.place ?? 999999))[0] ?? null;
    return {
      averageTeamValue: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null,
      leader,
    };
  }, [managers]);

  return (
    <section className="league-page">
      <header className="league-page__header">
        <div>
          <h1 className="league-page__title">LIGA</h1>
          <p className="league-page__subtitle">Ranking und Manager deiner aktiven Liga.</p>
        </div>
      </header>

      <div className="league-summary">
        <SummaryMetric icon={<UsersRound size={16} />} label="Manager" value={formatNumber(managers.length)} />
        <SummaryMetric
          icon={<Trophy size={16} />}
          label="Ø Teamwert"
          value={stats.averageTeamValue == null ? "—" : formatCompactCurrency(stats.averageTeamValue)}
        />
        <SummaryMetric
          icon={<Crown size={16} />}
          label="Führender"
          value={stats.leader?.name ?? "—"}
          subvalue={stats.leader?.points == null ? undefined : `${formatNumber(stats.leader.points)} Punkte`}
        />
      </div>

      <div className="league-toolbar">
        <div className="league-toolbar__hint">Managerübersicht</div>
        <label className="league-search">
          <Search size={16} aria-hidden />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Manager suchen …"
            aria-label="Manager suchen"
          />
        </label>
      </div>

      <div className="league-table-frame">
        <div className="league-table-scroll">
          <table className="league-table">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const sortable = header.column.getCanSort();
                    const direction = header.column.getIsSorted();
                    return (
                      <th key={header.id}>
                        <button
                          type="button"
                          className="league-table-sort"
                          disabled={!sortable}
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sortable ? <SortIcon direction={direction} /> : null}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={`${row.original.isSelf ? "is-self " : ""}is-clickable`.trim()}
                  tabIndex={0}
                  onClick={() => setSelectedManager(row.original)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedManager(row.original);
                    }
                  }}
                  aria-label={`Kader von ${row.original.name} öffnen`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <ManagerSquadDrawer
        leagueId={leagueId}
        manager={selectedManager}
        onClose={() => setSelectedManager(null)}
      />
    </section>
  );
}

function SummaryMetric({
  icon,
  label,
  value,
  subvalue,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  subvalue?: string;
}) {
  return (
    <div className="league-summary__metric">
      <div className="league-summary__label">{icon}{label}</div>
      <strong>{value}</strong>
      {subvalue ? <span>{subvalue}</span> : null}
    </div>
  );
}

function NumericCell({ value, format, decimals = 0 }: { value: number | null; format?: "currency"; decimals?: number }) {
  if (value == null) return <span className="league-value-empty">—</span>;
  return <span className="league-value">{format === "currency" ? formatCurrency(value) : formatNumber(value, decimals)}</span>;
}

function SignedCurrency({ value }: { value: number | null }) {
  if (value == null) return <span className="league-value-empty">—</span>;
  return <span className={`league-value league-value--${value > 0 ? "positive" : value < 0 ? "negative" : "neutral"}`}>
    {value > 0 ? "+" : ""}{formatCompactCurrency(value)}
  </span>;
}

function SortIcon({ direction }: { direction: false | "asc" | "desc" }) {
  if (direction === "asc") return <ArrowUp size={13} />;
  if (direction === "desc") return <ArrowDown size={13} />;
  return <ArrowUpDown size={13} />;
}

function isNumber(value: number | null): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatCompactCurrency(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 }).format(value / 1_000_000)} Mio. €`;
  if (abs >= 1_000) return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 }).format(value / 1_000)} Tsd. €`;
  return formatCurrency(value);
}

function formatNumber(value: number, decimals = 0) {
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

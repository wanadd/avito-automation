import Link from "next/link";
import { isValidElement } from "react";
import { dt, money, text } from "@/lib/format";
import { StatusBadge } from "@/components/status-badge";

type Column = {
  key: string;
  label: string;
  kind?: "text" | "status" | "money" | "date" | "link";
  href?: (row: Record<string, unknown>) => string;
};

export function DataTable({ columns, rows, empty }: { columns: Column[]; rows: Record<string, unknown>[]; empty: string }) {
  if (rows.length === 0) {
    return <div className="empty">{empty}</div>;
  }
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id ?? row.variant_id ?? index)}>
              {columns.map((column) => (
                <td key={column.key}>{renderCell(column, row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderCell(column: Column, row: Record<string, unknown>) {
  const value = row[column.key];
  if (isValidElement(value)) {
    return value;
  }
  if (column.kind === "status") {
    return <StatusBadge value={value} />;
  }
  if (column.kind === "money") {
    return money(value);
  }
  if (column.kind === "date") {
    return dt(value);
  }
  if (column.kind === "link" && column.href) {
    return <Link href={column.href(row)}>{text(value)}</Link>;
  }
  return text(value);
}

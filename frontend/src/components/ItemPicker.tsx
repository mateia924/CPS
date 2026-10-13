"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import type { Paginated, Product } from "@/lib/types";

/** Sprint 7.4: the one item picker for stock documents — searches
 * /products/ by name, code, barcode or part number (the server-side
 * search_fields 7.1's D9 fixed for every item picker), stock items only.
 * A scanner types the barcode and presses Enter: Enter picks the first
 * match, so a scan lands without touching the mouse. */
export function ItemPicker({
  value,
  onChange,
  required,
}: {
  value: Product | null;
  onChange: (item: Product | null) => void;
  required?: boolean;
}) {
  const { t } = useLocale();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [open, setOpen] = useState(false);
  const requestId = useRef(0);

  useEffect(() => {
    if (!open || query.trim().length < 1) {
      setResults([]);
      return;
    }
    const id = ++requestId.current;
    const timer = setTimeout(() => {
      api
        .get<Paginated<Product>>(`/products/?item_type=stock&search=${encodeURIComponent(query.trim())}`)
        .then((data) => {
          if (id === requestId.current) setResults(data.results.slice(0, 10));
        })
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [query, open]);

  const pick = (item: Product) => {
    onChange(item);
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  if (value && !open) {
    return (
      <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
        <span>
          {value.sku} — {value.name}
        </span>
        <button type="button" className="secondary" onClick={() => setOpen(true)} aria-label={t("edit")}>
          ✎
        </button>
      </div>
    );
  }

  return (
    <div style={{ position: "relative", minWidth: "240px" }}>
      <input
        value={query}
        placeholder={t("stockItemSearch")}
        required={required && !value}
        autoFocus={open}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (results.length > 0) pick(results[0]);
          }
          if (e.key === "Escape" && value) setOpen(false);
        }}
      />
      {open && results.length > 0 && (
        <ul
          role="listbox"
          style={{
            position: "absolute", insetInlineStart: 0, top: "100%", zIndex: 20, margin: 0, padding: 0,
            listStyle: "none", minWidth: "100%", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          {results.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                style={{
                  display: "block", width: "100%", textAlign: "start", padding: "0.35rem 0.6rem",
                  background: "transparent", border: "none", color: "inherit", cursor: "pointer", font: "inherit",
                }}
                onClick={() => pick(item)}
              >
                {item.sku} — {item.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

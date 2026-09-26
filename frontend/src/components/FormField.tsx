"use client";

import { cloneElement, type ReactElement } from "react";
import { useLocale } from "@/lib/i18n";

function snakeToCamel(name: string): string {
  return name.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

interface FormFieldProps {
  /** The backend field name (as it appears in fieldErrors(body)) —
   * also the default label lookup key, converted to camelCase (e.g.
   * "legal_entity" -> t("legalEntity")). */
  name: string;
  /** Overrides the dictionary lookup — required when `name` has no
   * matching i18n key, or collides with an unrelated one. */
  label?: string;
  required?: boolean;
  /** fieldErrors(body)[name] — a single resolved message, already in
   * the active locale (the backend translates via Accept-Language). */
  error?: string;
  hint?: string;
  style?: React.CSSProperties;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  children: ReactElement<any>;
}

/** Sprint 6.5.6 (docs/SYSTEM_ANALYSIS.md §3.18 standing rule): the one
 * wrapper every data-entry field in the app goes through — a required
 * field's label carries a red *, an API field error renders in red
 * under the field by its own Arabic label (never the raw backend
 * field name), and the input itself gets a red border. A non-field
 * error (network failure, {detail: "..."}) never belongs here — see
 * WarningsBanner's `variant="error"`, rendered once above the form. */
export function FormField({ name, label, required, error, hint, style, children }: FormFieldProps) {
  const { t } = useLocale();
  const resolvedLabel = label ?? t(snakeToCamel(name));
  const child = cloneElement(children, {
    "aria-invalid": error ? true : undefined,
    "aria-describedby": error ? `${name}-error` : undefined,
  });
  return (
    <div className={`form-field${error ? " has-error" : ""}`} style={style}>
      <label>
        {resolvedLabel}
        {required && <span style={{ color: "var(--danger)" }}> *</span>}
      </label>
      {child}
      {hint && !error && <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>{hint}</div>}
      {error && (
        <p id={`${name}-error`} className="error-text">
          {error}
        </p>
      )}
    </div>
  );
}

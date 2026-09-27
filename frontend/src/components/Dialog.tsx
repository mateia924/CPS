"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale } from "@/lib/i18n";

/** Sprint 6.5.10 (UAT note 9): the one shared way to ask the user for a
 * short piece of text before confirming an action — `window.prompt()`
 * is an unstyled native browser dialog with no brand/RTL/theming at
 * all. Renders nothing until `open()` is called; only one instance is
 * ever needed app-wide (mounted once, e.g. in the dashboard layout),
 * same as a portal-less modal keyed by its own open state. */
interface PromptOptions {
  title: string;
  message?: string;
  placeholder?: string;
  confirmLabel?: string;
  /** Required by default — an empty submission re-shows the field
   * instead of resolving. */
  required?: boolean;
}

let openPromptImpl: ((options: PromptOptions) => Promise<string | null>) | null = null;

/** Promise-based replacement for `window.prompt()` — resolves to the
 * typed string on confirm, or `null` on cancel/dismiss. Must only be
 * called after <DialogHost /> has mounted (see layout.tsx). */
export function promptDialog(options: PromptOptions): Promise<string | null> {
  if (!openPromptImpl) {
    throw new Error("DialogHost is not mounted yet");
  }
  return openPromptImpl(options);
}

export function DialogHost() {
  const { t, dir } = useLocale();
  const [state, setState] = useState<PromptOptions | null>(null);
  const [value, setValue] = useState("");
  const [touched, setTouched] = useState(false);
  const resolveRef = useRef<((value: string | null) => void) | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    openPromptImpl = (options) =>
      new Promise((resolve) => {
        setState(options);
        setValue("");
        setTouched(false);
        resolveRef.current = resolve;
      });
    return () => {
      openPromptImpl = null;
    };
  }, []);

  useEffect(() => {
    if (state) inputRef.current?.focus();
  }, [state]);

  if (!state) return null;

  const isRequired = state.required ?? true;
  const invalid = touched && isRequired && value.trim() === "";

  const finish = (result: string | null) => {
    resolveRef.current?.(result);
    resolveRef.current = null;
    setState(null);
  };

  const confirm = () => {
    if (isRequired && value.trim() === "") {
      setTouched(true);
      return;
    }
    finish(value.trim());
  };

  return (
    <div
      role="presentation"
      onClick={() => finish(null)}
      style={{
        position: "fixed",
        inset: 0,
        background: "var(--overlay)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        dir={dir}
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{ width: "min(420px, 90vw)", margin: 0 }}
      >
        <h3 style={{ marginTop: 0 }}>{state.title}</h3>
        {state.message && <p style={{ color: "var(--muted)" }}>{state.message}</p>}
        <div className={`form-field${invalid ? " has-error" : ""}`}>
          <input
            ref={inputRef}
            value={value}
            placeholder={state.placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") confirm();
              if (e.key === "Escape") finish(null);
            }}
            // form-ok: a generic one-off prompt value, not a backend
            // field — the caller supplies its own label/message text,
            // so FormField's name->i18n-key lookup doesn't apply here.
          />
          {invalid && <p className="error-text">{t("fieldRequired")}</p>}
        </div>
        <div style={{ marginTop: "1rem", display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
          <button type="button" className="secondary" onClick={() => finish(null)}>
            {t("cancel")}
          </button>
          <button type="button" className="primary" onClick={confirm}>
            {state.confirmLabel ?? t("confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import { DialogHost } from "@/components/Dialog";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ScreenErrors } from "@/components/ScreenErrors";
import { APPROVAL_INBOX, NAV_SECTIONS, PROFILE, canSee } from "@/lib/nav";
import type { PendingApprovalsResponse } from "@/lib/types";

// BRAND.md §4 "الشريط الجانبي": the active item gets a filled background
// plus a --sidebar-active-bar stripe on the leading edge.
function SidebarLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link href={href} className={active ? "active" : undefined}>
      {children}
    </Link>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, tenant, me, meError, isReady, logout, refreshMe } = useAuth();
  const { t } = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    if (isReady && !user) {
      router.replace("/login");
    }
  }, [isReady, user, router]);

  // Sprint 6.6.2 (items 1/2): the backend's own middleware already
  // rejects every other request while must_change_password is set —
  // this is purely the UX half, so the user lands on the one screen
  // that works instead of a page full of failed requests.
  useEffect(() => {
    if (!me) return;
    const forced = me.user.must_change_password || me.requires_2fa_setup;
    if (forced && pathname !== "/dashboard/profile") {
      router.replace("/dashboard/profile");
    }
  }, [me, pathname, router]);

  useEffect(() => {
    if (!user) return;
    api
      .get<PendingApprovalsResponse>("/approvals/pending/")
      .then((data) => setPendingCount(data.results.length))
      .catch(() => undefined);
  }, [user]);

  if (!isReady || !user) return null;

  // Block 8.0.1: every link comes from lib/nav.ts, where each entry
  // names the permission its screen's API requires (or why it needs
  // none) — a link the user's roles can't open is never rendered.
  const showApprovalInbox = canSee(me, APPROVAL_INBOX);
  // Sprint 6.6.2 (items 1/2): mirrors the backend middleware's own
  // gate — every link below would just 403, so don't show them at all.
  const forced = !!me && (me.user.must_change_password || me.requires_2fa_setup);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <img
          src="/brand/cps-logo-stacked-compact-white.svg"
          alt="CPS"
          style={{ width: 120, display: "block", marginBottom: "0.5rem" }}
        />
        <h2 style={{ margin: "0 0 0.75rem", fontSize: "0.95rem", fontWeight: 500, color: "var(--sidebar-text)" }}>
          {tenant?.name}
        </h2>
        {meError && (
          // Sprint 4.8: /me failing must never look like "this tenant
          // just has fewer permissions" — a visible, explicit error
          // instead of a silently truncated menu (permission/feature
          // -gated sections below all evaluate to false when `me` is
          // null, which is otherwise indistinguishable from a real,
          // intentionally limited menu).
          <div
            className="card"
            style={{ padding: "0.6rem 0.75rem", marginBottom: "0.75rem", borderColor: "var(--danger)" }}
          >
            <p style={{ margin: 0, fontSize: "0.85rem" }}>{meError}</p>
            <button
              type="button"
              className="secondary"
              style={{ marginTop: "0.4rem" }}
              onClick={() => refreshMe()}
            >
              {t("retry")}
            </button>
          </div>
        )}
        {forced && (
          <div className="card" style={{ padding: "0.6rem 0.75rem", marginBottom: "0.75rem" }}>
            <p style={{ margin: 0, fontSize: "0.85rem" }}>
              {me?.user.must_change_password ? t("forcedPasswordChangeNotice") : t("forced2faSetupNotice")}
            </p>
          </div>
        )}
        {!forced && (
        <>
        {showApprovalInbox && (
        <div className="topbar" style={{ marginBottom: "0.5rem" }}>
          <Link href={APPROVAL_INBOX.href} style={{ color: "var(--sidebar-text)" }}>
            {t("approvalInbox")}
            {pendingCount > 0 && (
              <span
                style={{
                  marginInlineStart: "0.4rem",
                  background: "var(--danger)",
                  color: "var(--color-on-primary)",
                  borderRadius: "var(--radius-pill)",
                  padding: "0.05rem 0.5rem",
                  fontSize: "0.75rem",
                }}
              >
                {pendingCount}
              </span>
            )}
          </Link>
        </div>
        )}
        {NAV_SECTIONS.map((section, i) => {
          const visible = section.entries.filter((entry) => canSee(me, entry, section));
          if (visible.length === 0) return null;
          return (
            <Fragment key={section.label ?? i}>
              {section.label && <div className="sidebar-section-label">{t(section.label)}</div>}
              {visible.map((entry) => (
                <SidebarLink key={entry.href} href={entry.href}>
                  {t(typeof entry.label === "function" ? (me ? entry.label(me) : "") : entry.label)}
                </SidebarLink>
              ))}
            </Fragment>
          );
        })}
        </>
        )}

        <div style={{ marginTop: "auto", paddingTop: "1rem" }}>
          <SidebarLink href={PROFILE.href}>{t(PROFILE.label as string)}</SidebarLink>
          <LocaleSwitcher />
          <button
            className="secondary"
            style={{ marginTop: "0.5rem", width: "100%" }}
            onClick={() => {
              logout();
              router.replace("/login");
            }}
          >
            {t("logout")}
          </button>
        </div>
      </aside>
      <main className="main-content">
        {tenant?.status === "past_due" && (
          <div className="banner-warning" role="alert">
            {t("pastDueWarning")}
          </div>
        )}
        <ScreenErrors>{children}</ScreenErrors>
      </main>
      <DialogHost />
    </div>
  );
}

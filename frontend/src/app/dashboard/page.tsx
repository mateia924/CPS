"use client";

import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";

export default function DashboardHome() {
  const { user, tenant } = useAuth();
  const { t } = useLocale();

  return (
    <div className="card">
      <h1>
        {t("welcome")}, {user?.first_name || user?.email}
      </h1>
      <p>{tenant?.name}</p>
    </div>
  );
}

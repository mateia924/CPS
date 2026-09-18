"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function PlatformDashboardIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/platform/dashboard/tenants");
  }, [router]);
  return null;
}

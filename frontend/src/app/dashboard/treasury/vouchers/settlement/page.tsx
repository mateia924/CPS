"use client";

import { Suspense } from "react";
import { TransferVoucherScreen } from "@/components/TransferVoucherScreen";

export default function SettlementVouchersPage() {
  return (
    <Suspense fallback={null}>
      <TransferVoucherScreen />
    </Suspense>
  );
}

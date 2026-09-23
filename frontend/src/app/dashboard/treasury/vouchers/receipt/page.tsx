"use client";

import { Suspense } from "react";
import { VoucherScreen } from "@/components/VoucherScreen";

export default function ReceiptVouchersPage() {
  return (
    <Suspense fallback={null}>
      <VoucherScreen voucherType="receipt" />
    </Suspense>
  );
}

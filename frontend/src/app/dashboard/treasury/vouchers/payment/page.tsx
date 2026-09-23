"use client";

import { Suspense } from "react";
import { VoucherScreen } from "@/components/VoucherScreen";

export default function PaymentVouchersPage() {
  return (
    <Suspense fallback={null}>
      <VoucherScreen voucherType="payment" />
    </Suspense>
  );
}

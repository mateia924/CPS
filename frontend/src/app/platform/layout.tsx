"use client";

import { PlatformAuthProvider } from "@/lib/platform-auth-context";

// Deliberately its own auth provider, entirely separate from the
// customer-facing AuthProvider in the root layout (different
// localStorage keys, different backend auth realm — see
// apps/platform/auth.py). Nothing under /platform links back to, or is
// linked from, the customer dashboard.
export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  return <PlatformAuthProvider>{children}</PlatformAuthProvider>;
}

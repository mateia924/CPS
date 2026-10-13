"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { Money } from "@/components/Money";
import { formatDate } from "@/lib/date";
import type { LegalEntity, StockDocument, StockDocumentKind } from "@/lib/types";

const DOC_LABEL: Record<StockDocumentKind, string> = {
  receipt: "stockReceiptDoc",
  issue: "stockIssueDoc",
  transfer: "stockTransferDoc",
};

/** Sprint 7.4: /print/stock/<kind>/<id> — same layout as
 * /print/vouchers/<id>: logo + the entity's effective profile, the
 * document data, its lines, server totals, and signature boxes. */
export default function StockDocumentPrintPage() {
  const { id } = useParams<{ kind: string; id: string }>();
  const { t } = useLocale();
  const [doc, setDoc] = useState<StockDocument | null>(null);
  const [entity, setEntity] = useState<LegalEntity | null>(null);

  useEffect(() => {
    api.get<StockDocument>(`/stock-documents/${id}/`).then(async (d) => {
      setDoc(d);
      setEntity(await api.get<LegalEntity>(`/legal-entities/${d.legal_entity}/`));
    });
  }, [id]);

  if (!doc || !entity) return null;

  const profile = entity.effective_profile;
  const addressLine = [profile.building_number, profile.street, profile.district, profile.city]
    .filter(Boolean)
    .join("، ");
  const isTransfer = doc.kind === "transfer";
  const showCost = doc.status === "posted" || doc.status === "reversed" || doc.kind === "receipt";

  return (
    <div>
      <div className="print-actions">
        <button className="primary" onClick={() => window.print()}>{t("printButton")}</button>
      </div>
      <div className="print-page">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "start" }}>
            <img src="/brand/cps-logo-horizontal.svg" alt="CPS" style={{ height: 48 }} />
            <div>
              <h2 style={{ margin: 0 }}>{entity.name}</h2>
              {entity.tax_number && <p>{t("taxNumber")}: {entity.tax_number}</p>}
              {addressLine && <p>{addressLine}</p>}
            </div>
          </div>
          <div style={{ textAlign: "end" }}>
            <h2>{t(DOC_LABEL[doc.kind])}</h2>
            <p>{t("number")}: {doc.number}</p>
            <p>{t("stockDocDate")}: {formatDate(doc.date, "form")}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <p><strong>{isTransfer ? t("stockFromWarehouse") : t("warehouse")}:</strong> {doc.warehouse_name}</p>
        {isTransfer && (
          <p><strong>{t("stockToWarehouse")}:</strong> {doc.to_warehouse_name} ({doc.to_legal_entity_name})</p>
        )}
        {doc.party_name && <p><strong>{t("stockParty")}:</strong> {doc.party_name}</p>}
        {doc.reference && <p><strong>{t("reference")}:</strong> {doc.reference}</p>}
        {doc.notes && <p><strong>{t("notes")}:</strong> {doc.notes}</p>}

        <table style={{ marginTop: "1rem", width: "100%" }}>
          <thead>
            <tr>
              <th>#</th>
              <th>{t("stockItem")}</th>
              <th>{t("stockUnit")}</th>
              <th>{t("quantity")}</th>
              {showCost && <th>{t("stockUnitCost")}</th>}
              <th>{t("stockBatch")}</th>
              <th>{t("stockSerials")}</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((line, i) => (
              <tr key={line.id}>
                <td>{i + 1}</td>
                <td>{line.item_sku} — {line.item_name}</td>
                <td>{line.uom_name || t("stockBaseUnit")}</td>
                <td className="money">{line.qty}</td>
                {showCost && <td><Money amount={line.unit_cost} /></td>}
                <td>{line.batch_number || "—"}</td>
                <td>{line.serial_numbers.join("، ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <p style={{ marginTop: "1rem" }}>
          <strong>{t("stockTotalQty")}:</strong> <span className="money">{doc.total_qty}</span>
          {showCost && (
            <>
              {" — "}<strong>{t("stockTotalValue")}:</strong> <Money amount={doc.total_value} />
            </>
          )}
        </p>

        <div className="print-signatures">
          <div>{t("stockSignatureStorekeeper")}</div>
          <div>{t("stockSignatureReceiver")}</div>
          <div>{t("signatureAccountant")}</div>
        </div>
      </div>
    </div>
  );
}

import { SupplierManagement } from "@/components/supplier-management";
import { apiGet, type Page } from "@/lib/api";

export default async function SuppliersPage() {
  const page = await apiGet<Page>("/api/v1/operator/suppliers");
  return <SupplierManagement initialRows={page.items as never[]} initialTotal={page.total} />;
}

import { apiRequest } from "./client";
import type { CaseMeta, PublicCaseDetail } from "../types/public-api";

export function listCases(): Promise<CaseMeta[]> {
  return apiRequest<CaseMeta[]>("/cases");
}

export function getCaseDetail(caseId: string): Promise<PublicCaseDetail> {
  return apiRequest<PublicCaseDetail>(`/cases/${encodeURIComponent(caseId)}`);
}

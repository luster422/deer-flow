import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  KnowledgeBase,
  KnowledgeBindingSelection,
  KnowledgeDocument,
  KnowledgeSearchHit,
  KnowledgeUploadResult,
} from "./types";

const baseUrl = () => `${getBackendBaseURL()}/api/knowledge-bases`;

async function checked<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) await throwGatewayApiError(response, fallback);
  return response.json() as Promise<T>;
}

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const response = await fetch(baseUrl());
  const data = await checked<{ knowledge_bases: KnowledgeBase[] }>(
    response,
    `Failed to load knowledge bases: ${response.statusText}`,
  );
  return data.knowledge_bases;
}

export async function createKnowledgeBase(payload: {
  name: string;
  description?: string;
}): Promise<KnowledgeBase> {
  const response = await fetch(baseUrl(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return checked(
    response,
    `Failed to create knowledge base: ${response.statusText}`,
  );
}

export async function deleteKnowledgeBase(id: string): Promise<void> {
  const response = await fetch(`${baseUrl()}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  await checked(
    response,
    `Failed to delete knowledge base: ${response.statusText}`,
  );
}

export async function listKnowledgeDocuments(
  knowledgeBaseId: string,
): Promise<KnowledgeDocument[]> {
  const response = await fetch(
    `${baseUrl()}/${encodeURIComponent(knowledgeBaseId)}/documents`,
  );
  const data = await checked<{ documents: KnowledgeDocument[] }>(
    response,
    `Failed to load knowledge documents: ${response.statusText}`,
  );
  return data.documents;
}

export async function uploadKnowledgeDocument(
  knowledgeBaseId: string,
  file: File,
): Promise<KnowledgeUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${baseUrl()}/${encodeURIComponent(knowledgeBaseId)}/documents`,
    { method: "POST", body: form },
  );
  return checked(response, `Failed to upload document: ${response.statusText}`);
}

export async function deleteKnowledgeDocument(
  knowledgeBaseId: string,
  documentId: string,
): Promise<void> {
  const response = await fetch(
    `${baseUrl()}/${encodeURIComponent(knowledgeBaseId)}/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );
  await checked(response, `Failed to delete document: ${response.statusText}`);
}

export async function retryKnowledgeDocument(
  knowledgeBaseId: string,
  documentId: string,
): Promise<void> {
  const response = await fetch(
    `${baseUrl()}/${encodeURIComponent(knowledgeBaseId)}/documents/${encodeURIComponent(documentId)}/retry`,
    { method: "POST" },
  );
  await checked(response, `Failed to retry document: ${response.statusText}`);
}

export async function searchKnowledgeBase(
  knowledgeBaseId: string,
  payload: { query: string; top_k?: number; document_ids?: string[] },
): Promise<KnowledgeSearchHit[]> {
  const response = await fetch(
    `${baseUrl()}/${encodeURIComponent(knowledgeBaseId)}/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  const data = await checked<{ query: string; hits: KnowledgeSearchHit[] }>(
    response,
    `Failed to search knowledge base: ${response.statusText}`,
  );
  return data.hits;
}

function threadBindingUrl(threadId: string): string {
  return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/knowledge-bases`;
}

export async function getThreadKnowledgeBindings(
  threadId: string,
): Promise<KnowledgeBindingSelection> {
  const response = await fetch(threadBindingUrl(threadId));
  return checked(
    response,
    `Failed to load knowledge selection: ${response.statusText}`,
  );
}

export async function updateThreadKnowledgeBindings(
  threadId: string,
  payload: KnowledgeBindingSelection,
): Promise<KnowledgeBindingSelection> {
  const response = await fetch(threadBindingUrl(threadId), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return checked(
    response,
    `Failed to update knowledge selection: ${response.statusText}`,
  );
}

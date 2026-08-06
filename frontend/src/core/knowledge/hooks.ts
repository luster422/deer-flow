import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  getThreadKnowledgeBindings,
  listKnowledgeBases,
  listKnowledgeDocuments,
  retryKnowledgeDocument,
  searchKnowledgeBase,
  updateThreadKnowledgeBindings,
  uploadKnowledgeDocument,
} from "./api";
import type { KnowledgeBindingSelection } from "./types";

const knowledgeKey = ["knowledge-bases"] as const;

export function useKnowledgeBases(enabled = true) {
  return useQuery({
    queryKey: knowledgeKey,
    queryFn: listKnowledgeBases,
    enabled,
    retry: false,
  });
}

export function useKnowledgeDocuments(knowledgeBaseId?: string | null) {
  return useQuery({
    queryKey: [...knowledgeKey, knowledgeBaseId, "documents"],
    queryFn: () => listKnowledgeDocuments(knowledgeBaseId ?? ""),
    enabled: Boolean(knowledgeBaseId),
    refetchInterval: (query) =>
      query.state.data?.some((document) =>
        ["queued", "parsing", "embedding", "indexing", "deleting"].includes(
          document.status,
        ),
      )
        ? 1500
        : false,
  });
}

function useInvalidateKnowledge() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: knowledgeKey });
}

export function useCreateKnowledgeBase() {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: createKnowledgeBase,
    onSuccess: invalidate,
  });
}

export function useDeleteKnowledgeBase() {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: deleteKnowledgeBase,
    onSuccess: invalidate,
  });
}

export function useUploadKnowledgeDocument(knowledgeBaseId: string) {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: (file: File) => uploadKnowledgeDocument(knowledgeBaseId, file),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useDeleteKnowledgeDocument(knowledgeBaseId: string) {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: (documentId: string) =>
      deleteKnowledgeDocument(knowledgeBaseId, documentId),
    onSuccess: invalidate,
  });
}

export function useRetryKnowledgeDocument(knowledgeBaseId: string) {
  const invalidate = useInvalidateKnowledge();
  return useMutation({
    mutationFn: (documentId: string) =>
      retryKnowledgeDocument(knowledgeBaseId, documentId),
    onSuccess: invalidate,
  });
}

export function useSearchKnowledgeBase(knowledgeBaseId: string) {
  return useMutation({
    mutationFn: (query: string) =>
      searchKnowledgeBase(knowledgeBaseId, { query }),
  });
}

export function useThreadKnowledgeBindings(threadId: string, enabled = true) {
  return useQuery({
    queryKey: [...knowledgeKey, "thread", threadId],
    queryFn: () => getThreadKnowledgeBindings(threadId),
    enabled: enabled && Boolean(threadId),
    retry: false,
  });
}

export function useUpdateThreadKnowledgeBindings(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (selection: KnowledgeBindingSelection) =>
      updateThreadKnowledgeBindings(threadId, selection),
    onSuccess: (selection) => {
      queryClient.setQueryData(
        [...knowledgeKey, "thread", threadId],
        selection,
      );
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

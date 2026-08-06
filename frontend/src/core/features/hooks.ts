import { useQuery } from "@tanstack/react-query";

import { fetchBrowserControlEnabled, fetchKnowledgeBasesEnabled } from "./api";

export function useBrowserControlEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "browser_control"],
    queryFn: () => fetchBrowserControlEnabled(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useKnowledgeBasesEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "knowledge_bases"],
    queryFn: fetchKnowledgeBasesEnabled,
    retry: false,
  });
  return { enabled: data ?? false, isLoading: isPending };
}

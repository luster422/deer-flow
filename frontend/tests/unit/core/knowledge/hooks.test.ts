import { beforeEach, describe, expect, it, rs } from "@rstest/core";

const queryMocks = rs.hoisted(() => ({
  useQuery: rs.fn((options: unknown) => ({ options })),
}));

rs.mock("@tanstack/react-query", () => ({
  useMutation: rs.fn(),
  useQuery: queryMocks.useQuery,
  useQueryClient: rs.fn(),
}));

import {
  useKnowledgeBases,
  useThreadKnowledgeBindings,
} from "@/core/knowledge/hooks";

describe("knowledge query gating", () => {
  beforeEach(() => {
    queryMocks.useQuery.mockClear();
  });

  it("does not query knowledge APIs while the feature is disabled", () => {
    useKnowledgeBases(false);
    useThreadKnowledgeBindings("thread-1", false);

    expect(queryMocks.useQuery.mock.calls[0]?.[0]).toMatchObject({
      enabled: false,
    });
    expect(queryMocks.useQuery.mock.calls[1]?.[0]).toMatchObject({
      enabled: false,
    });
  });
});

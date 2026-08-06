import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch } from "@/core/api/fetcher";
import {
  createKnowledgeBase,
  listKnowledgeBases,
  searchKnowledgeBase,
  updateThreadKnowledgeBindings,
  uploadKnowledgeDocument,
} from "@/core/knowledge/api";

const mockedFetch = rs.mocked(fetch);

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Bad Request" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

describe("knowledge api", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("lists and creates knowledge bases", async () => {
    mockedFetch
      .mockResolvedValueOnce(jsonResponse({ knowledge_bases: [] }))
      .mockResolvedValueOnce(jsonResponse({ id: "kb-1", name: "Docs" }, 201));

    await expect(listKnowledgeBases()).resolves.toEqual([]);
    await createKnowledgeBase({ name: "Docs", description: "Runbooks" });

    expect(mockedFetch).toHaveBeenNthCalledWith(
      1,
      "/backend/api/knowledge-bases",
    );
    expect(mockedFetch).toHaveBeenNthCalledWith(
      2,
      "/backend/api/knowledge-bases",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Docs", description: "Runbooks" }),
      },
    );
  });

  it("uploads a document using multipart form data", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({ document: { id: "doc-1" }, job: { id: "job-1" } }, 202),
    );
    const file = new File(["# Guide"], "guide.md", {
      type: "text/markdown",
    });

    await uploadKnowledgeDocument("kb/one", file);

    const [url, init] = mockedFetch.mock.calls[0] ?? [];
    expect(url).toBe("/backend/api/knowledge-bases/kb%2Fone/documents");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("file")).toBe(file);
    expect(init?.headers).toBeUndefined();
  });

  it("searches one knowledge base and persists empty replace bindings", async () => {
    mockedFetch
      .mockResolvedValueOnce(jsonResponse({ query: "alpha", hits: [] }))
      .mockResolvedValueOnce(
        jsonResponse({ strategy: "replace", knowledge_base_ids: [] }),
      );

    await searchKnowledgeBase("kb-1", { query: "alpha", top_k: 4 });
    await updateThreadKnowledgeBindings("thread-1", {
      strategy: "replace",
      knowledge_base_ids: [],
    });

    expect(mockedFetch.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(mockedFetch.mock.calls[1]?.[1]?.method).toBe("PUT");
    expect(mockedFetch.mock.calls[1]?.[1]?.body).toBe(
      JSON.stringify({ strategy: "replace", knowledge_base_ids: [] }),
    );
  });

  it("surfaces backend error detail", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Knowledge bases are disabled" }, 503),
    );

    await expect(listKnowledgeBases()).rejects.toThrow(
      "Knowledge bases are disabled",
    );
  });
});

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const knowledgeBase = {
  id: "kb-1",
  user_id: "default",
  name: "Engineering runbooks",
  description: "Operational guidance for production services.",
  status: "active",
  document_count: 1,
  chunk_count: 12,
  created_at: "2026-07-31T00:00:00Z",
  updated_at: "2026-07-31T00:00:00Z",
};

const knowledgeDocument = {
  id: "doc-1",
  knowledge_base_id: knowledgeBase.id,
  filename: "incident-response.md",
  media_type: "text/markdown",
  size_bytes: 4096,
  content_sha256: "abc123",
  status: "ready",
  version: 1,
  index_revision: 1,
  chunk_count: 12,
  error_code: null,
  error_message: null,
  created_at: "2026-07-31T00:00:00Z",
  updated_at: "2026-07-31T00:00:00Z",
};

function mockKnowledgeAPI(page: Page, enabled: boolean) {
  mockLangGraphAPI(page, {
    threads: [],
    features: { knowledgeBasesEnabled: enabled },
  });

  void page.route("**/api/knowledge-bases", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ knowledge_bases: [knowledgeBase] }),
    }),
  );
  void page.route("**/api/knowledge-bases/kb-1/documents", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ documents: [knowledgeDocument] }),
    }),
  );
  void page.route("**/api/knowledge-bases/kb-1/search", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: "rollback",
        hits: [
          {
            id: "chunk-1",
            knowledge_base_id: knowledgeBase.id,
            document_id: knowledgeDocument.id,
            content: "Rollback the deployment before restarting the service.",
            metadata: { filename: knowledgeDocument.filename },
            score: 0.9123,
            vector_score: 0.87,
            text_score: 0.95,
          },
        ],
      }),
    }),
  );
}

test("knowledge navigation stays hidden when the feature is disabled", async ({
  page,
}) => {
  mockKnowledgeAPI(page, false);

  await page.goto("/workspace/chats/new");

  await expect(page.getByRole("link", { name: "Knowledge bases" })).toHaveCount(
    0,
  );
});

test("knowledge page lists indexed documents and previews retrieval", async ({
  page,
}) => {
  mockKnowledgeAPI(page, true);

  await page.goto("/workspace/knowledge-bases");

  await expect(
    page.getByRole("heading", { name: "Knowledge bases" }),
  ).toBeVisible();
  await expect(page.getByText(knowledgeBase.name)).toBeVisible();
  await expect(page.getByText(knowledgeDocument.filename)).toBeVisible();

  await page.getByPlaceholder("Search indexed passages").fill("rollback");
  await page.getByRole("button", { name: "Retrieval preview" }).click();
  await expect(page.getByText(/Rollback the deployment/)).toBeVisible();
});

test("knowledge page fits a mobile viewport without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  mockKnowledgeAPI(page, true);

  await page.goto("/workspace/knowledge-bases");

  await expect(page.getByText(knowledgeDocument.filename)).toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});

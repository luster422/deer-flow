"use client";

import {
  DatabaseIcon,
  FileTextIcon,
  Loader2Icon,
  PlusIcon,
  RotateCcwIcon,
  SearchIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useKnowledgeBasesEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateKnowledgeBase,
  useDeleteKnowledgeBase,
  useDeleteKnowledgeDocument,
  useKnowledgeBases,
  useKnowledgeDocuments,
  useRetryKnowledgeDocument,
  useSearchKnowledgeBase,
  useUploadKnowledgeDocument,
} from "@/core/knowledge";
import type { KnowledgeDocumentStatus } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function StatusBadge({
  status,
  labels,
}: {
  status: KnowledgeDocumentStatus | string;
  labels: Record<string, string>;
}) {
  return (
    <Badge
      variant={
        status === "failed" || status === "error" ? "destructive" : "outline"
      }
      className={cn(
        "rounded-sm",
        status === "ready" &&
          "border-emerald-600/40 text-emerald-700 dark:text-emerald-400",
      )}
    >
      {labels[status] ?? status}
    </Badge>
  );
}

export default function KnowledgeBasesPage() {
  const router = useRouter();
  const { t } = useI18n();
  const labels = t.knowledgeBases;
  const feature = useKnowledgeBasesEnabled();
  const bases = useKnowledgeBases(feature.enabled);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected =
    bases.data?.find((base) => base.id === selectedId) ?? bases.data?.[0];
  const documents = useKnowledgeDocuments(selected?.id);
  const create = useCreateKnowledgeBase();
  const removeBase = useDeleteKnowledgeBase();
  const upload = useUploadKnowledgeDocument(selected?.id ?? "");
  const removeDocument = useDeleteKnowledgeDocument(selected?.id ?? "");
  const retryDocument = useRetryKnowledgeDocument(selected?.id ?? "");
  const search = useSearchKnowledgeBase(selected?.id ?? "");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [query, setQuery] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.title = `${labels.title} - ${t.pages.appName}`;
  }, [labels.title, t.pages.appName]);

  useEffect(() => {
    if (!feature.isLoading && !feature.enabled) router.replace("/workspace");
  }, [feature.enabled, feature.isLoading, router]);

  if (feature.isLoading || !feature.enabled) return null;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-hidden">
        <div className="flex h-full w-full max-w-(--container-width-lg) flex-col">
          <div className="flex h-16 shrink-0 items-center justify-between border-b px-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-2">
              <DatabaseIcon className="size-5" />
              <h1 className="truncate text-xl font-semibold">{labels.title}</h1>
            </div>
            <Button
              size="sm"
              aria-label={labels.create}
              onClick={() => setCreateOpen(true)}
            >
              <PlusIcon />
              <span className="hidden sm:inline">{labels.create}</span>
            </Button>
          </div>

          <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] md:grid-cols-[minmax(220px,0.32fr)_minmax(0,1fr)] md:grid-rows-1">
            <aside className="min-h-0 overflow-y-auto border-b md:border-r md:border-b-0">
              {bases.isLoading ? (
                <Loader2Icon className="text-muted-foreground m-5 size-4 animate-spin" />
              ) : bases.data?.length ? (
                <div className="divide-y">
                  {bases.data.map((base) => (
                    <button
                      key={base.id}
                      type="button"
                      className={cn(
                        "hover:bg-muted/60 flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors",
                        selected?.id === base.id && "bg-muted",
                      )}
                      onClick={() => setSelectedId(base.id)}
                    >
                      <span className="flex w-full items-center gap-2">
                        <span className="min-w-0 flex-1 truncate font-medium">
                          {base.name}
                        </span>
                        <StatusBadge
                          status={base.status}
                          labels={labels.status}
                        />
                      </span>
                      <span className="text-muted-foreground text-xs">
                        {labels.summary(base.document_count, base.chunk_count)}
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="p-6">
                  <p className="text-sm font-medium">{labels.emptyTitle}</p>
                  <p className="text-muted-foreground mt-1 text-sm">
                    {labels.emptyDescription}
                  </p>
                </div>
              )}
            </aside>

            <section className="min-h-0 overflow-y-auto">
              {selected ? (
                <div className="flex min-h-full flex-col">
                  <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-4 sm:px-6">
                    <div className="min-w-0">
                      <h2 className="truncate text-lg font-semibold">
                        {selected.name}
                      </h2>
                      {selected.description && (
                        <p className="text-muted-foreground mt-1 text-sm">
                          {selected.description}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        ref={fileInput}
                        className="hidden"
                        type="file"
                        accept=".md,.txt,.pdf,.docx,.pptx,.xlsx"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) upload.mutate(file);
                          event.target.value = "";
                        }}
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => fileInput.current?.click()}
                        disabled={upload.isPending}
                      >
                        {upload.isPending ? (
                          <Loader2Icon className="animate-spin" />
                        ) : (
                          <UploadIcon />
                        )}
                        {labels.upload}
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t.common.delete}
                        title={t.common.delete}
                        onClick={() => {
                          if (
                            window.confirm(
                              `${labels.deleteTitle}\n\n${labels.deleteDescription}`,
                            )
                          )
                            removeBase.mutate(selected.id);
                        }}
                      >
                        <Trash2Icon />
                      </Button>
                    </div>
                  </div>

                  <div className="border-b px-4 py-4 sm:px-6">
                    <h3 className="mb-3 font-medium">{labels.document}</h3>
                    {documents.isLoading ? (
                      <Loader2Icon className="text-muted-foreground size-4 animate-spin" />
                    ) : documents.data?.length ? (
                      <div className="overflow-x-auto border">
                        <table className="w-full min-w-160 text-sm">
                          <tbody className="divide-y">
                            {documents.data.map((document) => (
                              <tr key={document.id}>
                                <td className="w-full px-3 py-2.5">
                                  <div className="flex min-w-0 items-center gap-2">
                                    <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
                                    <span className="truncate font-medium">
                                      {document.filename}
                                    </span>
                                  </div>
                                  {document.error_message && (
                                    <div className="text-destructive mt-1 line-clamp-1 text-xs">
                                      {document.error_message}
                                    </div>
                                  )}
                                </td>
                                <td className="text-muted-foreground px-3 py-2.5 text-xs whitespace-nowrap">
                                  {formatBytes(document.size_bytes)}
                                </td>
                                <td className="px-3 py-2.5 whitespace-nowrap">
                                  <StatusBadge
                                    status={document.status}
                                    labels={labels.status}
                                  />
                                </td>
                                <td className="text-muted-foreground px-3 py-2.5 text-xs whitespace-nowrap">
                                  {document.chunk_count} {labels.chunks}
                                </td>
                                <td className="px-2 py-2 whitespace-nowrap">
                                  {document.status === "failed" && (
                                    <Button
                                      size="icon-sm"
                                      variant="ghost"
                                      aria-label={t.common.regenerate}
                                      title={t.common.regenerate}
                                      onClick={() =>
                                        retryDocument.mutate(document.id)
                                      }
                                    >
                                      <RotateCcwIcon />
                                    </Button>
                                  )}
                                  <Button
                                    size="icon-sm"
                                    variant="ghost"
                                    aria-label={t.common.delete}
                                    title={t.common.delete}
                                    onClick={() =>
                                      removeDocument.mutate(document.id)
                                    }
                                  >
                                    <Trash2Icon />
                                  </Button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="text-muted-foreground text-sm">
                        {labels.noDocuments}
                      </div>
                    )}
                  </div>

                  <div className="px-4 py-4 sm:px-6">
                    <h3 className="mb-3 font-medium">{labels.searchTitle}</h3>
                    <form
                      className="flex gap-2"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (query.trim()) search.mutate(query.trim());
                      }}
                    >
                      <Input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder={labels.searchPlaceholder}
                      />
                      <Button
                        type="submit"
                        size="icon"
                        disabled={!query.trim() || search.isPending}
                        aria-label={labels.searchTitle}
                      >
                        {search.isPending ? (
                          <Loader2Icon className="animate-spin" />
                        ) : (
                          <SearchIcon />
                        )}
                      </Button>
                    </form>
                    {search.data && (
                      <div className="mt-4 divide-y border-y">
                        {search.data.length ? (
                          search.data.map((hit) => (
                            <div key={hit.id} className="py-3">
                              <div className="text-muted-foreground mb-1 flex items-center justify-between gap-3 text-xs">
                                <span>
                                  {typeof hit.metadata.filename === "string" &&
                                  hit.metadata.filename.trim()
                                    ? hit.metadata.filename
                                    : hit.document_id}
                                </span>
                                <span>{hit.score.toFixed(4)}</span>
                              </div>
                              <p className="line-clamp-4 text-sm whitespace-pre-wrap">
                                {hit.content}
                              </p>
                            </div>
                          ))
                        ) : (
                          <div className="text-muted-foreground py-4 text-sm">
                            {labels.noResults}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-muted-foreground flex h-full items-center justify-center p-8 text-sm">
                  {labels.emptyDescription}
                </div>
              )}
            </section>
          </div>
        </div>
      </WorkspaceBody>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{labels.createTitle}</DialogTitle>
            <DialogDescription>{labels.createDescription}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={labels.namePlaceholder}
            />
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={labels.descriptionPlaceholder}
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button
              disabled={!name.trim() || create.isPending}
              onClick={() =>
                create.mutate(
                  { name: name.trim(), description: description.trim() },
                  {
                    onSuccess: () => {
                      setName("");
                      setDescription("");
                      setCreateOpen(false);
                    },
                  },
                )
              }
            >
              {create.isPending && <Loader2Icon className="animate-spin" />}
              {t.common.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}

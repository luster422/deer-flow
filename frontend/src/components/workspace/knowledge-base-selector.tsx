"use client";

import { DatabaseIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";

import {
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
} from "@/components/ai-elements/prompt-input";
import {
  DropdownMenuCheckboxItem,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { useKnowledgeBasesEnabled } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import {
  useKnowledgeBases,
  useThreadKnowledgeBindings,
  useUpdateThreadKnowledgeBindings,
} from "@/core/knowledge";

export function KnowledgeBaseSelector({
  threadId,
  disabled,
}: {
  threadId: string;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const { enabled } = useKnowledgeBasesEnabled();
  const bases = useKnowledgeBases(enabled);
  const bindings = useThreadKnowledgeBindings(threadId, enabled);
  const update = useUpdateThreadKnowledgeBindings(threadId);
  if (!enabled) return null;

  const selected = bindings.data?.knowledge_base_ids ?? [];
  const toggle = (id: string, checked: boolean) => {
    const next = checked
      ? [...new Set([...selected, id])]
      : selected.filter((candidate) => candidate !== id);
    update.mutate({ strategy: "replace", knowledge_base_ids: next });
  };

  return (
    <PromptInputActionMenu>
      <PromptInputActionMenuTrigger
        aria-label={t.knowledgeBases.selectorLabel}
        className="max-w-32 gap-1! px-2!"
        disabled={(disabled ?? false) || bindings.isLoading || update.isPending}
      >
        {update.isPending ? (
          <Loader2Icon className="size-3 animate-spin" />
        ) : (
          <DatabaseIcon className="size-3" />
        )}
        <span className="truncate text-xs">
          {t.knowledgeBases.selectorLabel}
          {selected.length > 0 ? ` (${selected.length})` : ""}
        </span>
      </PromptInputActionMenuTrigger>
      <PromptInputActionMenuContent className="w-72">
        <DropdownMenuLabel>{t.knowledgeBases.selectorLabel}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {bases.data?.length ? (
          bases.data.map((base) => (
            <DropdownMenuCheckboxItem
              key={base.id}
              checked={selected.includes(base.id)}
              onCheckedChange={(checked) => toggle(base.id, checked === true)}
              onSelect={(event) => event.preventDefault()}
            >
              <span className="min-w-0 truncate">{base.name}</span>
              <span className="text-muted-foreground ml-auto text-xs">
                {base.document_count}
              </span>
            </DropdownMenuCheckboxItem>
          ))
        ) : (
          <div className="text-muted-foreground px-2 py-3 text-sm">
            {t.knowledgeBases.selectorEmpty}
          </div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/workspace/knowledge-bases">
            <DatabaseIcon />
            {t.knowledgeBases.selectorManage}
          </Link>
        </DropdownMenuItem>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}

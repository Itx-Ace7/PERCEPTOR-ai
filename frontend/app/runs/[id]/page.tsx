"use client";

import { use } from "react";
import { useSearchParams } from "next/navigation";
import { Workspace } from "@/components/Workspace";

export default function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const search = useSearchParams();
  return <Workspace runId={id} initialView={search.get("view") || undefined} />;
}

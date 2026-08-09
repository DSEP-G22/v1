import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { API_BASE, api, getToken } from "./client";
import type {
  ActionRegistryEntry,
  CurrentUser,
  DashboardMetrics,
  DlqEntry,
  KnowledgeDocument,
  KnowledgeHit,
  QueueRow,
  TicketDetail,
} from "./types";

export const queryKeys = {
  me: ["me"] as const,
  queue: (department?: string) => ["queue", department ?? "all"] as const,
  ticket: (id: string) => ["ticket", id] as const,
  dashboard: ["dashboard"] as const,
  actionRegistry: ["action-registry"] as const,
  routingRules: ["routing-rules"] as const,
  thresholds: ["thresholds"] as const,
  models: ["models"] as const,
  users: ["users"] as const,
  documents: ["knowledge-documents"] as const,
  dlq: ["dlq"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api.get<CurrentUser>("/workspace/me"),
    retry: false,
  });
}

export function useQueue(department?: string) {
  return useQuery({
    queryKey: queryKeys.queue(department),
    queryFn: () =>
      api.get<QueueRow[]>(`/workspace/queue${department ? `?department=${encodeURIComponent(department)}` : ""}`),
    // Polling is the documented fallback for the WebSocket (Appendix C); the socket below
    // invalidates this key on every push, so in practice the poll rarely fires.
    refetchInterval: 15_000,
  });
}

/** REQ-WKS-2: queue changes reach the agent within 5 s. The socket pushes the whole queue on
 *  change; we write it straight into the cache so the table re-renders without a refetch. */
export function useQueueSocket(enabled: boolean) {
  const queryClient = useQueryClient();
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const token = getToken();
    if (!token) return;

    // The socket must reach the API's origin, which is not the page's origin once the frontend
    // is deployed separately. With VITE_API_BASE unset we fall back to the page origin, which is
    // what the Vite dev proxy expects.
    const base = API_BASE || window.location.origin;
    const url = `${base.replace(/^http/, "ws")}/workspace/ws/queue?token=${encodeURIComponent(token)}`;
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onmessage = (event) => {
      try {
        const rows = JSON.parse(event.data) as QueueRow[];
        queryClient.setQueryData(queryKeys.queue(undefined), rows);
        queryClient.invalidateQueries({ queryKey: ["queue"], exact: false });
      } catch {
        // A malformed frame must never break the queue; the 15 s poll covers the gap.
      }
    };

    return () => {
      socket.onmessage = null;
      socket.close();
      socketRef.current = null;
    };
  }, [enabled, queryClient]);
}

export function useTicket(ticketId: string) {
  return useQuery({
    queryKey: queryKeys.ticket(ticketId),
    queryFn: () => api.get<TicketDetail>(`/workspace/tickets/${ticketId}`),
    enabled: Boolean(ticketId),
  });
}

export function useDashboard() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: () => api.get<DashboardMetrics>("/workspace/dashboard"),
    refetchInterval: 30_000,
  });
}

function useTicketMutation<TVariables, TData>(
  ticketId: string,
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.ticket(ticketId) });
      queryClient.invalidateQueries({ queryKey: ["queue"], exact: false });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
}

export const useLockTicket = (id: string) =>
  useTicketMutation(id, (_: void) => api.post<{ locked_by: string }>(`/workspace/tickets/${id}/lock`));

export const useSaveDraft = (id: string) =>
  useTicketMutation(id, (current_text: string) =>
    api.patch<{ draft_id: string; revision: number }>(`/workspace/tickets/${id}/draft`, { current_text }),
  );

export const useApprove = (id: string) =>
  useTicketMutation(id, (_: void) => api.post<Record<string, unknown>>(`/workspace/tickets/${id}/approve`));

export const useReject = (id: string) =>
  useTicketMutation(id, (reason_code: string) =>
    api.post<{ decision_id: string }>(`/workspace/tickets/${id}/reject`, { reason_code }),
  );

export const useReassign = (id: string) =>
  useTicketMutation(id, (vars: { department: string; reason_code?: string }) =>
    api.post<{ decision_id: string }>(`/workspace/tickets/${id}/reassign`, vars),
  );

export const useEscalate = (id: string) =>
  useTicketMutation(id, (reason_code: string) =>
    api.post<{ decision_id: string }>(`/workspace/tickets/${id}/escalate`, { reason_code }),
  );

export const useExecuteAction = (id: string) =>
  useTicketMutation(id, (recommendationId: string) =>
    api.post<Record<string, unknown>>(`/workspace/tickets/${id}/actions/${recommendationId}/execute`),
  );

// --- Administration (UI-5) and onboarding (UI-6) -----------------------------------------

export const useActionRegistry = () =>
  useQuery({ queryKey: queryKeys.actionRegistry, queryFn: () => api.get<ActionRegistryEntry[]>("/admin/action-registry") });

export const useRoutingRules = () =>
  useQuery({ queryKey: queryKeys.routingRules, queryFn: () => api.get<Record<string, unknown>[]>("/admin/routing-rules") });

export const useThresholds = () =>
  useQuery({ queryKey: queryKeys.thresholds, queryFn: () => api.get<Record<string, number>>("/admin/thresholds") });

export const useModels = () =>
  useQuery({
    queryKey: queryKeys.models,
    queryFn: () => api.get<{ declared: Record<string, unknown>; active: Record<string, string> }>("/admin/models"),
  });

export const useUsers = () =>
  useQuery({
    queryKey: queryKeys.users,
    queryFn: () => api.get<{ id: string; username: string; role: string; email: string | null }[]>("/admin/users"),
  });

export const useDlq = () => useQuery({ queryKey: queryKeys.dlq, queryFn: () => api.get<DlqEntry[]>("/admin/dlq") });

export function useReplayDlq() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) => api.post<{ replayed: boolean }>(`/admin/dlq/${entryId}/replay`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.dlq }),
  });
}

export const useKnowledgeDocuments = () =>
  useQuery({ queryKey: queryKeys.documents, queryFn: () => api.get<KnowledgeDocument[]>("/admin/knowledge/documents") });

export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: { file: File; orgId: string }) => {
      const form = new FormData();
      form.append("file", vars.file);
      form.append("org_id", vars.orgId);
      return api.upload<{ document_id: string; title: string; num_chunks: number }>("/admin/knowledge/documents", form);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

export function useKnowledgeSearch(query: string) {
  return useQuery({
    queryKey: ["knowledge-search", query],
    queryFn: () => api.get<KnowledgeHit[]>(`/admin/knowledge/search?q=${encodeURIComponent(query)}`),
    enabled: query.trim().length > 2,
  });
}

import { createContext, useContext } from "react";

export interface CurrentUser {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "member";
  has_token: boolean;
}

export interface ListInfo {
  id: number;
  name: string;
  role: "owner" | "editor" | "viewer";
  items: number;
  shared: boolean;
  members: { user_id: number; display_name: string; role: string }[];
  occasion: string | null;
  recipient: string | null;
  event_date: string | null;
  budget_cents: number | null;
  spent_cents: number;
  remaining_cents: number | null;
}

export interface Session {
  user: CurrentUser | null;
  lists: ListInfo[];
  reloadLists: () => void;
}

export const SessionContext = createContext<Session>({ user: null, lists: [], reloadLists: () => {} });
export const useSession = () => useContext(SessionContext);

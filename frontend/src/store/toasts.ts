import { create } from "zustand";

export type ToastKind = "info" | "success" | "error";

export interface Toast {
  id: string;
  kind: ToastKind;
  message: string;
}

interface ToastsState {
  items: Toast[];
  push: (kind: ToastKind, message: string) => void;
  remove: (id: string) => void;
}

let counter = 0;

export const useToasts = create<ToastsState>((set, get) => ({
  items: [],
  push(kind, message) {
    counter += 1;
    const id = `t-${counter}`;
    set((s) => ({ items: [...s.items, { id, kind, message }] }));
    // Auto-dismiss after 5 seconds
    setTimeout(() => get().remove(id), 5000);
  },
  remove(id) {
    set((s) => ({ items: s.items.filter((t) => t.id !== id) }));
  },
}));

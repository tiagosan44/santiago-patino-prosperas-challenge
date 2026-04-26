import { create } from "zustand";
import { persist } from "zustand/middleware";

import { setUnauthorizedHandler } from "../api/client";
import * as authApi from "../api/auth";

interface AuthState {
  token: string | null;
  username: string | null;
  loginError: string | null;
  isLoggingIn: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, _get) => ({
      token: null,
      username: null,
      loginError: null,
      isLoggingIn: false,

      async login(username, password) {
        set({ isLoggingIn: true, loginError: null });
        try {
          const res = await authApi.login(username, password);
          set({
            token: res.access_token,
            username,
            isLoggingIn: false,
            loginError: null,
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : "login failed";
          set({ loginError: msg, isLoggingIn: false, token: null, username: null });
          throw e;
        }
      },

      logout() {
        set({ token: null, username: null, loginError: null });
      },

      clearError() {
        set({ loginError: null });
      },
    }),
    {
      name: "prosperas-auth",
      partialize: (s) => ({ token: s.token, username: s.username }),
    }
  )
);

// When ANY API call returns 401, sign the user out automatically.
// We register the handler here (module-level) so the store is the
// single source of truth for the token.
setUnauthorizedHandler(() => {
  useAuthStore.getState().logout();
});

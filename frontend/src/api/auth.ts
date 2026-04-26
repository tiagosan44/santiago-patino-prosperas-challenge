import { apiRequest } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

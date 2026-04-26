import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useAuthStore } from "../store/auth";

const Schema = z.object({
  username: z.string().min(3, "min 3 characters"),
  password: z.string().min(8, "min 8 characters"),
});

type FormData = z.infer<typeof Schema>;

export function LoginPage() {
  const login = useAuthStore((s) => s.login);
  const isLoggingIn = useAuthStore((s) => s.isLoggingIn);
  const loginError = useAuthStore((s) => s.loginError);

  const { register, handleSubmit, formState } = useForm<FormData>({
    resolver: zodResolver(Schema),
    defaultValues: { username: "", password: "" },
  });

  const onSubmit = async (data: FormData) => {
    try {
      await login(data.username, data.password);
    } catch {
      // Error already surfaced via loginError; nothing else to do
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="bg-white rounded-lg shadow p-8 w-full max-w-sm space-y-4"
      >
        <div>
          <h1 className="text-2xl font-bold">Prosperas Reports</h1>
          <p className="text-sm text-slate-500">Sign in to continue</p>
        </div>

        <div>
          <label htmlFor="username" className="block text-sm font-medium mb-1">
            Username
          </label>
          <input
            id="username"
            type="text"
            autoComplete="username"
            {...register("username")}
            className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
          />
          {formState.errors.username && (
            <p className="text-xs text-red-600 mt-1">{formState.errors.username.message}</p>
          )}
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium mb-1">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            {...register("password")}
            className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm"
          />
          {formState.errors.password && (
            <p className="text-xs text-red-600 mt-1">{formState.errors.password.message}</p>
          )}
        </div>

        {loginError && (
          <div role="alert" className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
            {loginError}
          </div>
        )}

        <button
          type="submit"
          disabled={isLoggingIn || formState.isSubmitting}
          className="w-full px-4 py-2 bg-slate-900 text-white rounded-md text-sm hover:bg-slate-700 disabled:opacity-60"
        >
          {isLoggingIn ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // semantic palette tied to job status badges
        status: {
          pending: "#94a3b8",   // slate-400
          processing: "#3b82f6", // blue-500
          completed: "#22c55e", // green-500
          failed: "#ef4444",    // red-500
        },
      },
    },
  },
  plugins: [],
};

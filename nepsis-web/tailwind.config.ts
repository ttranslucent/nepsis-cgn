import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx}",
    "./src/components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        nepsis: {
          bg: "#020617",
          panel: "#020617",
          accent: "#38bdf8",
          accentSoft: "#22d3ee",
          text: "#e5e7eb",
          muted: "#64748b",
          border: "#1e293b",
          danger: "#f97373",
          success: "#4ade80",
        },
      },
      borderRadius: {
        xl: "1.25rem",
      },
    },
  },
  plugins: [],
};

export default config;

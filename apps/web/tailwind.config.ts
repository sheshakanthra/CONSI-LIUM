import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // The single brand accent, matching the architecture diagram in
        // README.md. Defined as a token (not sprinkled as an arbitrary
        // `text-[#00ffcc]`) so the supported/bullish/interactive states that
        // all mean "verified, good" stay one colour by construction.
        accent: "#00ffcc",
      },
    },
  },
  plugins: [],
};

export default config;

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CONSILIUM — Research desk",
  description:
    "Multi-agent equity research: bull/bear deliberation, independent fact-checking, and citations that resolve to the source page or table cell.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}

import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Docent",
  description: "Ask questions of your documents and get answers with verified citations.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

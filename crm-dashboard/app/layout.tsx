import { AuthProvider } from "@/components/AuthContext";

export const metadata = { title: "AIEC CRM — Leads" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#f7f7f8" }}>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

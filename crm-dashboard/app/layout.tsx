import { AuthProvider } from "@/components/AuthContext";
import "./theme.css";

export const metadata = { title: "AIEC CRM — Leads" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

import { CounsellorPanel } from "@/components/ChatWidget/CounsellorPanel";
import { StatusChecker } from "@/components/ChatWidget/StatusChecker";
import { TopNav } from "@/components/TopNav";

export default function HomePage() {
  const apiUrl = process.env.NEXT_PUBLIC_CHAT_API_URL ?? "http://localhost:3001";

  return (
    <main style={{ maxWidth: 1000, margin: "0 auto", padding: 32 }}>
      <TopNav active="counsellor" />
      <h1>AIEC Global (test page)</h1>
      <p>
        This is a bare mock of the client&apos;s site, just to preview the widget before it gets
        dropped into the real &quot;Chat to Counsellor&quot; section.
      </p>

      <section style={{ marginTop: 32 }}>
        <h2>Chat to Counsellor</h2>
        <CounsellorPanel apiUrl={apiUrl} />
      </section>

      <section style={{ marginTop: 32 }}>
        <h2>Application Status Portal</h2>
        <p>Standalone — a student can check this from any device using their reference code, no chat session needed.</p>
        <StatusChecker apiUrl={apiUrl} />
      </section>
    </main>
  );
}

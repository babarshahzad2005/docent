import type { Metadata } from "next";
import Link from "next/link";

import { Wordmark } from "@/components/wordmark";

export const metadata: Metadata = { title: "Privacy · Docent" };

export default function PrivacyPage() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-8 px-4 py-12">
      <Link href="/" aria-label="Docent home" className="self-start">
        <Wordmark />
      </Link>
      <article className="flex flex-col gap-4 px-2 [&_h2]:mt-4 [&_h2]:font-serif [&_h2]:text-heading [&_ul]:flex [&_ul]:list-disc [&_ul]:flex-col [&_ul]:gap-2 [&_ul]:pl-5">
        <h1 className="font-serif text-question font-medium">Privacy notice</h1>
        <p className="text-muted-foreground">
          Docent is a personal portfolio project, not a commercial service. This notice says
          what it stores and why, in plain words. Last updated 21 November 2026 (v0.1).
        </p>
        <h2>What Docent stores</h2>
        <ul>
          <li>
            <strong>Your sign-in details:</strong> your email address and an ID for you. If you
            sign in with Google, your name and profile picture from Google are also kept by the
            sign-in service. Docent gets no other access to your Google data.
          </li>
          <li>
            <strong>Sign-in records:</strong> the sign-in service (Supabase) logs sign-in
            activity, including network addresses, to protect accounts from abuse.
          </li>
          <li>
            <strong>Your Collections:</strong> their names and who is a Member of each.
          </li>
          <li>
            <strong>Your documents:</strong> each file you upload, and the text and search data
            Docent makes from it, so it can answer and show its sources. Deleting a document
            removes the file and everything made from it. When you replace a document, the
            passages earlier answers cited are kept as text, so those answers still show what
            they were based on, until you delete the document.
          </li>
          <li>
            <strong>Your conversations:</strong> each question you ask and its answer, with the
            passages it cited, so you can reopen a conversation and check its sources. They are
            kept until you ask for them to be deleted.
          </li>
          <li>
            <strong>An answer log:</strong> for each answer, the question, which passages were
            found, the prompt sent to the AI model, the reply, and timings, to measure and
            improve answer quality. Entries are deleted after 90 days.
          </li>
        </ul>
        <h2>Who processes it</h2>
        <p>
          Data is stored with Supabase and the app runs on Vercel, both in Singapore. To
          answer, Docent sends your question and the passages it found to AI model providers:
          Groq (which runs the answer models) and Google (Gemini, for search data and as a
          backup answer model). Their free tiers may use what they
          receive to improve their products, so{" "}
          <strong>don&rsquo;t upload confidential or personal documents.</strong>
        </p>
        <h2>Coming later</h2>
        <ul>
          <li>
            <strong>Public collections:</strong> visitors&rsquo; network addresses will be stored
            only as one-way hashes, for rate limiting.
          </li>
        </ul>
        <h2>Deleting your data</h2>
        <p>
          Self-service deletion isn&rsquo;t available yet. Until it is, ask through the link below
          and everything stored about you will be removed.
        </p>

        <h2>Questions</h2>
        <p>
          Open an issue on the project&rsquo;s{" "}
          <a
            href="https://github.com/babarshahzad2005/docent/issues"
            className="underline underline-offset-2"
          >
            GitHub repository
          </a>
          .
        </p>
      </article>
    </main>
  );
}

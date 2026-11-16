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
      <article className="flex flex-col gap-4 px-2 [&_h2]:mt-4 [&_h2]:font-serif [&_h2]:text-heading [&_ul]:list-disc [&_ul]:pl-5">
        <h1 className="font-serif text-question font-medium">Privacy notice</h1>
        <p className="text-muted-foreground">
          Docent is a personal portfolio project, not a commercial service, and it&rsquo;s still
          being built. This notice says what it stores and why, in plain terms, including
          features as they launch.
        </p>

        <h2>What Docent stores</h2>
        <ul>
          <li>
            <strong>Your account:</strong> your email address and an account ID. If you sign in
            with Google, Docent receives only your email address and basic profile, not access to
            your Google data.
          </li>
          <li>
            <strong>Your documents and conversations:</strong> files you upload and the questions
            you ask, so Docent can answer them and show their sources.
          </li>
          <li>
            <strong>Answer records:</strong> each answer, with the passages it used, is recorded
            to measure and improve answer quality. These records are kept for 90 days.
          </li>
          <li>
            <strong>Visitors to public collections:</strong> network addresses are stored only as
            one-way hashes, for rate limiting.
          </li>
        </ul>

        <h2>Who processes it</h2>
        <p>
          Data is stored with Supabase and the app runs on Vercel, both in Singapore. To answer
          questions, relevant passages are sent to AI model providers. Some of these providers&rsquo;
          free tiers may use the data they receive to improve their products, so{" "}
          <strong>don&rsquo;t upload confidential or personal documents.</strong>
        </p>

        <h2>Deleting your data</h2>
        <p>
          Deleting a document removes it and everything derived from it. Self-service account
          deletion isn&rsquo;t available yet; until it is, ask for deletion through the link below
          and your account, documents, and conversations will be removed. Answer records are then
          kept without anything that identifies you.
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

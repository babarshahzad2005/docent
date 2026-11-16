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
          Docent is a personal portfolio project, not a commercial service, and it&rsquo;s still
          being built. This notice says what it stores today and what will change as features
          launch.
        </p>

        <h2>What Docent stores today</h2>
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
            <strong>Your Collections:</strong> the names of your Collections and who is a Member
            of each.
          </li>
        </ul>

        <h2>As features launch</h2>
        <ul>
          <li>
            <strong>Documents and questions</strong> you add, so Docent can answer and show its
            sources. Deleting a document will remove it and everything derived from it.
          </li>
          <li>
            <strong>An answer log:</strong> each answer, with the passages it used, kept for 90
            days to measure answer quality.
          </li>
          <li>
            <strong>Public collections:</strong> visitors&rsquo; network addresses will be stored
            only as one-way hashes, for rate limiting.
          </li>
        </ul>
        <p>This notice will be updated as each of these ships.</p>

        <h2>Who processes it</h2>
        <p>
          Data is stored with Supabase and the app runs on Vercel, both in Singapore. Once
          answering is available, relevant passages will be sent to AI model providers, some of
          whose free tiers may use what they receive to improve their products, so{" "}
          <strong>don&rsquo;t upload confidential or personal documents.</strong>
        </p>

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

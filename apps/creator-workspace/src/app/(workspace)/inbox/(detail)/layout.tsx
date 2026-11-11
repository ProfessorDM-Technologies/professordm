import type { ReactNode } from "react";
import { ChatRail, type RailQuestion } from "@/components/inbox/chat-rail";
import { Page } from "@/components/page";
import { groupConversations } from "@/lib/inbox/conversations";
import { listInboundMessages } from "@/lib/inbox/queries";
import { cardState } from "@/lib/inbox/question-state";
import { listQuestions } from "@/lib/inbox/questions";

// Shared by a conversation (/inbox/[id]) and a question (/inbox/question/[id]). Because both pages sit under this
// layout, the rail stays mounted while the creator moves between chats (UI v2 spec, requirement 8).
export default async function InboxDetailLayout({ children }: { children: ReactNode }) {
  const [inbound, inbox] = await Promise.all([listInboundMessages({ limit: 200 }), listQuestions("inbox")]);

  const conversations = groupConversations(inbound.messages);
  const questions: RailQuestion[] = inbox.questions.map((question) => {
    const state = cardState(question, question.draft, question.lastSend);
    return {
      id: question.id,
      username: question.follower?.username ?? null,
      text: question.questionText,
      at: question.paidAt,
      label: state.label,
      tone: state.tone,
      openable: state.action !== null,
    };
  });

  return (
    <Page width="full" className="lg:grid lg:grid-cols-[18rem_minmax(0,1fr)] lg:items-start lg:gap-6">
      <ChatRail conversations={conversations} questions={questions} />
      <div className="min-w-0">{children}</div>
    </Page>
  );
}

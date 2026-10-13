# ProfessorDM Architecture Diagrams

All diagrams are rendered by GitHub's built-in Mermaid support.
Source `.mmd` files live alongside this README for editing.

---

## 00 — Master Architecture

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#FEFCE8','primaryTextColor':'#1C1917','primaryBorderColor':'#CA8A04','lineColor':'#64748B','background':'#FFFFFF'}}}%%
flowchart TB
    %% ProfessorDM V1 system context. Every box carries its accountable lead.

    subgraph USERS["PEOPLE"]
        direction LR
        FOL(["Instagram follower"])
        CON(["Knowledge App user<br/>Ask Sweetlife Flora"])
        CRE(["Creator<br/>Kristin, Sweetlife Flora"])
        ADM(["ProfessorDM team<br/>reviews flagged answers"])
    end

    subgraph EXT["EXTERNAL SERVICES"]
        direction LR
        IG["Meta Instagram Messaging API<br/>webhooks + send API"]
        STR["Stripe<br/>standard Payments, test mode first"]
        OR["OpenRouter<br/>Gemini 3.1 Flash-Lite, Claude Sonnet 5,<br/>GPT-5.6 Terra fallback, web search"]
        OAI["OpenAI API<br/>Moderation + text-embedding-3-small"]
        RES["Resend<br/>transactional email"]
    end

    subgraph FE["FRONTEND  Vercel Pro, 2 separate projects"]
        direction LR
        CW["Creator Workspace  Ritvik<br/>Bank (home), Inbox, Sent, Moderation,<br/>Profile settings, Knowledge Database<br/>+ ProfessorDM team review by role"]
        CA["Consumer App  Arun<br/>pre-paywall Ask page for IG followers<br/>+ Ask [Creator] Knowledge App<br/>V1 = Ask Sweetlife Flora"]
    end

    subgraph BE["BACKEND  AWS Lambda + API Gateway + SQS"]
        direction TB
        WHI["ig-webhook  Akshay<br/>HMAC verify, dedupe, 200 fast"]
        WHS["stripe-webhook  Akshay<br/>signature verify, payment events"]
        API["api  Akshay routing<br/>commands: approve, accept + rating,<br/>refund, search, ask, override, settings"]
        Q1[["SQS ai-jobs + DLQ"]]
        Q2[["SQS outbound + DLQ"]]
        AIW["ai-worker  Chinmay<br/>LangGraph JS: triage, clarify, retrieve,<br/>web search, draft, safety, embed,<br/>knowledge safety review"]
        SND["sender  Akshay<br/>DM delivery + quick-reply buttons,<br/>24h window rules, retry, delivery state"]
        SCH["scheduler  Karthik<br/>EventBridge, hourly: day-2 survey,<br/>day-3 close + knowledge, payouts,<br/>weekly knowledge safety review"]
    end

    subgraph DATA["SUPABASE PRO  Karthik"]
        direction LR
        PG[("Postgres<br/>RLS on every table<br/>audit_log + events tables")]
        VEC[("pgvector<br/>knowledge_entries")]
        AUTH["Supabase Auth<br/>creator, admin, consumer roles"]
        STO["Supabase Storage<br/>DM images, voice answers"]
        RT["Realtime<br/>inbox updates"]
    end

    subgraph OPS["QUALITY + OBSERVABILITY  Karthik"]
        direction LR
        GHA["GitHub Actions CI/CD"]
        SEN["Sentry free<br/>PII scrubbed"]
        AMP["Amplitude free<br/>reads internal events"]
    end

    %% Instagram path
    FOL -- "DM" --> IG
    IG -- "webhook" --> WHI
    WHI --> Q1
    Q1 --> AIW
    AIW -- "classify, clarify, draft" --> OR
    AIW -- "moderation, embeddings" --> OAI
    AIW -- "link, clarification DMs" --> Q2
    SCH -- "survey, embed, reviews" --> Q1
    SCH --> PG
    Q2 --> SND
    SND -- "send DM" --> IG
    IG -- "DM reply" --> FOL
    FOL -- "opens Ask link" --> CA

    %% Knowledge App path
    CON --> CA

    %% Payments
    CA -- "Checkout" --> STR
    STR -- "webhook" --> WHS
    WHS --> Q1

    %% Human in the loop
    CRE --> CW
    ADM --> CW
    CW -- "approve, edit, tag, refund" --> API
    API --> Q2
    API --> Q1
    API -- "refund" --> STR
    CA -- "search, ask, history" --> API
    SND -- "fallback email,<br/>app notifications" --> RES

    %% Data
    WHI --> PG
    WHS --> PG
    API --> PG
    AIW --> PG
    AIW --> VEC
    AIW --> STO
    SND --> PG
    CW -. "reads via RLS" .-> PG
    CA -. "reads via RLS" .-> PG
    CW -. "live" .-> RT
    CW --> AUTH
    CA --> AUTH

    %% Ops
    GHA -. "deploy" .-> FE
    GHA -. "deploy" .-> BE
    SEN -. "errors" .-> FE
    SEN -. "errors" .-> BE
    PG -. "event export" .-> AMP

    HITL{{"HUMAN IN THE LOOP<br/>No AI answer reaches a follower until the creator<br/>edits it, tags it and approves it.<br/>Flagged answers also need the ProfessorDM team"}}
    CW --- HITL

    classDef people fill:#FFF7ED,stroke:#EA580C,color:#7C2D12
    classDef ext fill:#FEF9C3,stroke:#CA8A04,color:#713F12
    classDef fe fill:#EFF6FF,stroke:#2563EB,color:#1E3A8A
    classDef be fill:#F0FDF4,stroke:#15803D,color:#14532D
    classDef data fill:#F0FDFA,stroke:#0F766E,color:#134E4A
    classDef ops fill:#F8FAFC,stroke:#64748B,color:#1E293B
    classDef human fill:#FFF1F2,stroke:#E11D48,color:#881337,font-weight:bold
    class FOL,CON,CRE,ADM people
    class IG,STR,OR,OAI,RES ext
    class CW,CA fe
    class WHI,WHS,API,Q1,Q2,AIW,SND,SCH be
    class PG,VEC,AUTH,STO,RT data
    class GHA,SEN,AMP ops
    class HITL human
```

---

## 01 — Tech Stack Overview

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#FEFCE8','primaryTextColor':'#1C1917','primaryBorderColor':'#CA8A04','lineColor':'#64748B','background':'#FFFFFF'}}}%%
flowchart LR
    %% Source of truth: ProfessorDM Technology Selection Matrix, Sep 19 2026.
    %% Items marked TEAM are implementation choices the matrix leaves open.

    subgraph M1["1 SOURCE CONTROL + CI/CD  $0"]
        A1["GitHub Free<br/>ProfessorDM org, company email owner"]
        A2["GitHub Actions"]
    end

    subgraph M2["2 FRONTEND HOSTING  $20"]
        B1["Vercel Pro<br/>Creator Workspace project<br/>Consumer App project"]
        B2["TEAM: Next.js + TypeScript"]
    end

    subgraph M3["3 BACKEND API + WEBHOOKS  $0 dev"]
        C1["AWS Lambda + API Gateway"]
        C2["TEAM: Node 22 LTS + TypeScript,<br/>AWS SAM for IaC"]
        C3["NEW: EventBridge Scheduler<br/>survey, hold close, payouts,<br/>knowledge review. About $0"]
    end

    subgraph M46["4-7 DATA PLATFORM  $25"]
        D1["Supabase Pro<br/>Postgres + Auth + RLS<br/>logins: email, Google, Apple, Microsoft"]
        D2["Supabase Storage<br/>images, signed URLs"]
        D3["pgvector<br/>embedding in same row as metadata"]
        D4["AWS SQS<br/>DLQ + retries"]
    end

    subgraph M89["8-9 AI  $0-5 dev"]
        E1["OpenRouter gateway"]
        E2["Gemini 3.1 Flash-Lite<br/>classification + clarification"]
        E3["Claude Sonnet 5<br/>grounded drafting"]
        E4["GPT-5.6 Terra<br/>fallback"]
        E5["OpenAI text-embedding-3-small<br/>benchmark vs 3-large first"]
        E6["TEAM: LangGraph JS orchestration"]
        E7["NEW: web search to fill gaps<br/>Kristin, Sep 23. Tool in ADR,<br/>e.g. OpenRouter web plugin"]
    end

    subgraph M10["10 SAFETY  $0"]
        F1["OpenAI Moderation API"]
        F2["Deterministic domain rules<br/>blocked list signed off by Kristin"]
        F3["Model-based policy classifier<br/>gray areas"]
    end

    subgraph M1112["11-12 INTEGRATIONS"]
        G1["Direct Meta Instagram Messaging API<br/>no wrapper, dev IG account first"]
        G2["Stripe test mode for V1 dev<br/>standard Payments for beta<br/>no Connect, 3-day hold in DB<br/>+ subscriptions ($10/mo default)"]
    end

    subgraph M1315["13-15 EMAIL + OBSERVABILITY + ANALYTICS  $0"]
        H1["Resend<br/>auth, resets, answer notices"]
        H2["Sentry free<br/>PII scrubbed"]
        H3["Supabase logs"]
        H4["Postgres audit_log table"]
        H5["Amplitude free<br/>+ internal events table"]
    end

    subgraph TEST["TEAM: TESTING"]
        T1["Vitest unit"]
        T2["Playwright E2E"]
        T3["eval harness<br/>classification, retrieval, safety"]
    end

    M2 --> M3
    M3 --> M46
    M3 --> M89
    M89 --> M10
    M3 --> M1112
    M3 --> M1315
    M1 -.-> M2
    M1 -.-> M3
    TEST -.-> M1

    BUD["BUDGET<br/>Dev about $45/mo, Beta about $85-130/mo<br/>Target under $150 dev, under $500 beta"]

    style M1 fill:#F8FAFC,stroke:#64748B,color:#1E293B
    style M2 fill:#EFF6FF,stroke:#2563EB,color:#1E3A8A
    style M3 fill:#F0FDF4,stroke:#15803D,color:#14532D
    style M46 fill:#F0FDFA,stroke:#0F766E,color:#134E4A
    style M89 fill:#FAF5FF,stroke:#7C3AED,color:#4C1D95
    style M10 fill:#FFF1F2,stroke:#E11D48,color:#881337
    style M1112 fill:#FEF9C3,stroke:#CA8A04,color:#713F12
    style M1315 fill:#FFF7ED,stroke:#EA580C,color:#7C2D12
    style TEST fill:#F8FAFC,stroke:#94A3B8,color:#334155,stroke-dasharray:4
    style BUD fill:#ECFDF5,stroke:#059669,color:#064E3B
```

---

## 02 — Instagram Golden Path

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% Primary V1 flow (Roles doc section 3, prototype "The complete flow", walkthrough guide v0.3):
    %% Social DM > Intent Classification > Ask UI / Clarify > Payment > Creator Inbox > Expert Answer > Knowledge
    %% Platform rule (guide): Instagram questions are answered back in Instagram, never inside the app.
    actor F as Follower
    participant IG as Instagram
    participant WH as ig-webhook<br/>(Akshay)
    participant Q as SQS
    participant AI as ai-worker<br/>(Chinmay)
    participant DB as Supabase<br/>(Karthik)
    participant SND as sender<br/>(Akshay)
    participant ASK as Ask page<br/>(Arun)
    participant STR as Stripe
    participant CW as Creator Workspace<br/>(Ritvik)
    actor CR as Creator
    participant SCH as scheduler<br/>(Karthik)

    rect rgb(255, 243, 224)
    Note over F,DB: 1. DM arrives
    end
    F->>IG: DM "Why are my calathea leaves curling?" + optional photo
    IG->>WH: webhook POST
    WH->>WH: verify X-Hub-Signature-256, dedupe on mid
    WH->>DB: insert inbound_message, copy image to Storage
    WH->>Q: ai-jobs { type: triage, messageId }
    WH-->>IG: 200 OK fast

    rect rgb(255, 235, 238)
    Note over Q,DB: 2. Triage: safety check 1 + classification (before any payment)
    end
    Q->>AI: triage job
    AI->>AI: safety layers 1-3 on inbound text + image
    AI->>AI: classify with Gemini 3.1 Flash-Lite
    AI->>DB: save category + confidence + safety result
    Note over AI,DB: Categories: expert_question, needs_clarification, social,<br/>spam_irrelevant, safety_concern, service_request.<br/>Creator can override any label from the Incoming view.
    alt social or spam_irrelevant
        AI->>DB: status = closed_no_action (visible in Incoming, no reply)
    else prohibited content (safety_concern, severe)
        AI->>DB: status = blocked, audit_log, polite decline DM, never reaches payment
    else service_request (refund, status, help)
        AI->>DB: route to refund queue or auto status reply
    else needs_clarification
        AI->>Q: outbound { type: clarification, text from Gemini }
        Q->>SND: send clarification DM
        SND->>IG: "Want a detailed answer? Tell me the plant, light, watering, add photos"
        F->>IG: follower revises the question in the same thread, can add photos
        IG->>WH: webhook, linked to the open message
        WH->>Q: ai-jobs { type: reassess }  (clarity filter runs again)
        Note over AI: Max 2 clarification rounds, then creator decides.
    else expert_question (ready)
        AI->>DB: create question status = pending_payment, ask_token,<br/>safety_flagged = true if a risk topic (e.g. oleander as mulch)
        AI->>Q: outbound { type: ask_link }
        Q->>SND: send Ask link DM
        SND->>IG: "I can answer this personally for $5. Tap to submit: link"
    end
    Note over AI,DB: A risk topic is NOT blocked. It continues to payment with a Safety Flag,<br/>and the creator must review it in her Moderation tab before answering.

    rect rgb(232, 245, 233)
    Note over F,STR: 3. Pre-paywall + payment (Stripe test mode until the approved live trial)
    end
    F->>ASK: open link (signed ask_token, no account needed)
    ASK->>DB: load question text
    F->>ASK: pre-paywall screen: question summary, edit, up to 3 photos, $5, confirm
    ASK->>STR: Checkout, price from creator settings (default $5)
    STR-->>F: payment page, email captured for receipts, survey and fallback delivery
    STR->>DB: via stripe-webhook (Akshay): payment succeeded, status = paid
    DB->>Q: ai-jobs { type: draft, questionId }
    SND->>IG: confirmation DM "Got it. Expected answer time: creator setting"

    rect rgb(243, 232, 255)
    Note over Q,DB: 4. Draft: knowledge base first, web search to fill gaps
    end
    Q->>AI: draft job
    AI->>DB: pgvector search, creator knowledge first
    alt knowledge base not enough for a complete answer
        AI->>AI: web search to fill the gaps, sources cited and labeled "from web"
    end
    AI->>AI: draft with Claude Sonnet 5 using question, clarifications, image, knowledge, web
    AI->>AI: safety check 2 on the draft
    AI->>DB: insert draft with citations (knowledge vs web), status = awaiting_creator
    DB-->>CW: Realtime: paid question in Inbox, tag "Instagram", "$4.00 earned",<br/>Safety Flag badge + Moderation tab entry if flagged

    rect rgb(255, 235, 238)
    Note over CW,CR: 5. HUMAN IN THE LOOP (mandatory, nothing sends without it)
    end
    opt question has a Safety Flag
        CR->>CW: review the flag in the Moderation tab before answering
    end
    CR->>CW: open question, see draft, knowledge + web sources, images, reply-by timer
    CR->>CW: rewrite in own voice, add tags. Answer as text and/or voice note (or save draft)
    CW->>CW: block send if text unchanged from draft or no tags
    CR->>CW: Submit answer
    CW->>DB: via api (Akshay): approve
    DB->>Q: ai-jobs { type: final_screen }
    Q->>AI: safety check 3 on the creator's final answer
    alt flagged
        AI->>DB: status = professordm_review. ProfessorDM team reviews BEFORE delivery,<br/>feedback goes to the creator's Moderation tab
    else clean
        AI->>Q: outbound { type: answer }
    end

    rect rgb(232, 245, 233)
    Note over SND,F: 6. Delivery back to Instagram + follower options
    end
    Q->>SND: answer job
    SND->>SND: pick send mode by Meta messaging window (see diagram 03)
    SND->>IG: answer DM (text and/or voice note) + quick-reply buttons:<br/>Ask a follow-up | Accept answer | Request refund
    IG-->>F: answer from Sweetlife Flora
    SND->>DB: status = delivered, delivered_at, hold ends delivered_at + 3 days (to confirm)

    rect rgb(255, 243, 224)
    Note over F,CR: 7. Follower responds (only while the 3-day hold is open)
    end
    alt Ask a follow-up (default 3, must be on topic)
        F->>IG: follow-up DM in the same thread
        IG->>WH: webhook, matched to open question with follow-ups left
        WH->>Q: ai-jobs { type: followup }
        Q->>AI: on-topic check + assisted draft (knowledge first, web if needed)
        AI->>DB: followup draft, awaiting_creator
        CR->>CW: edit + submit (same send gate, same safety check 3)
        CW->>Q: via api: final_screen, then outbound answer + buttons again
    else Accept answer
        F->>IG: tap Accept
        IG->>WH: webhook
        WH->>DB: status = accepted
        SND->>IG: "Rate this answer 1-5 stars" + optional review
        F->>IG: rating + review
        WH->>DB: ratings row
    else Request refund
        F->>IG: tap Request refund, pick a reason
        IG->>WH: webhook
        WH->>DB: refund_request, shows in creator's Inbox + Bank banner
        Note over CR,DB: Creator: Revisit Answer, Approve Refund or Deny (diagram 05).<br/>ProfessorDM does not mediate. Follower can contact ProfessorDM on social media.
    end
    Note over F,CR: When follow-ups run out, the next question gets a new Ask link.

    rect rgb(240, 249, 255)
    Note over SCH,DB: 8. Scheduler: day-2 survey and day-3 close
    end
    SCH->>DB: hourly: find delivered questions not accepted or refunded
    SCH->>Q: day 2: outbound { type: survey } "Happy with your answer?"<br/>Accept | Ask a follow-up | Request refund
    Note over SCH,SND: Automated message: DM only if the follower messaged in the last 24h,<br/>otherwise email via Resend (email from Stripe checkout)
    SCH->>DB: day 3, no refund: auto-accept, follow-ups + refund close,<br/>money moves Pending to Available in ProfessorDM Bank
    SCH->>Q: ai-jobs { type: embed, questionId }

    rect rgb(240, 249, 255)
    Note over AI,DB: 9. Reusable knowledge (only after the hold, never if refunded)
    end
    Q->>AI: anonymize Q+A, embed with text-embedding-3-small<br/>(voice note stored alongside with the same tags, transcription model TBD)
    AI->>DB: knowledge_entries row with the creator's tags,<br/>searchable in the Knowledge App if the creator turned it on
```

---

## 02b — Knowledge App Flow

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% Second app: "Ask [Creator]" Knowledge App, V1 = Ask Sweetlife Flora (white-label per creator).
    %% One-time free trial of 5 answers, then $10/month subscription. Ask the Expert $5, subscriber discount.
    %% Every question goes through the SAME AI, safety and creator inbox as Instagram (guide + kickoff).
    %% Answers to app questions are delivered in the app inbox, never to social media.
    actor U as Knowledge App user
    participant KA as Ask Sweetlife Flora<br/>(Arun)
    participant AU as Supabase Auth
    participant API as api<br/>(Akshay)
    participant AI as ai-worker<br/>(Chinmay)
    participant DB as Supabase<br/>(Karthik)
    participant STR as Stripe
    participant CW as Creator Workspace<br/>(Ritvik)
    participant EM as Resend
    participant SCH as scheduler<br/>(Karthik)

    rect rgb(255, 243, 224)
    Note over U,AU: 1. Sign in (required). "No payment needed until you subscribe or ask an expert."
    end
    U->>KA: open Ask Sweetlife Flora, Browse Knowledge
    KA->>AU: sign up free or sign in: Google, Apple, Microsoft or email + password
    AU->>EM: confirmation email via Resend SMTP (email sign-up only)
    AU-->>KA: session, role = consumer
    KA-->>U: home: search bar, popular topics (from tags), "5 / 5 free answers remaining"

    rect rgb(232, 245, 233)
    Note over U,DB: 2. Semantic search over PUBLISHED, creator-approved knowledge only
    end
    U->>KA: search "thrips" or tap a popular topic
    KA->>API: POST /search
    API->>API: embed query (text-embedding-3-small)
    API->>DB: pgvector similarity over knowledge_entries where published
    DB-->>KA: result cards: title, preview, tags, Premium badge once the trial is used up
    U->>KA: open a full answer
    alt subscriber
        KA-->>U: full answer
    else free trial answers left
        KA->>API: POST /entries/:id/view (1 of 5 used, one-time trial, never resets)
        KA-->>U: full answer, counter updated
    else trial used up
        KA-->>U: Premium gate: subscribe to keep reading (no per-answer purchase)
    end
    KA-->>U: "Need more specific advice? Ask the Expert" (available during trial too)

    rect rgb(243, 232, 255)
    Note over U,STR: 3. Subscription (default $10/month, set by creator)
    end
    U->>KA: Subscribe (from gate or Profile)
    KA->>STR: Checkout in subscription mode, card saved for later questions
    STR->>DB: via stripe-webhook (Akshay): subscription active, ledger split<br/>(platform fee 15-20 percent, creator the rest)
    KA-->>U: full library unlocked + discounted Ask the Expert

    rect rgb(255, 235, 238)
    Note over U,CW: 4. Ask the Expert (same pipeline as Instagram)
    end
    U->>KA: question + photo, sees creator, price, "3 free follow-ups", Available Now
    KA->>API: POST /questions { source: knowledge_app }
    API->>AI: ai-jobs triage: safety check 1 + classification
    alt needs_clarification
        AI-->>KA: clarification prompt in the app, user revises + adds photos, reassess
    else prohibited content
        AI->>DB: blocked, user sees "we can't accept this question"
    else ready (risk topics continue with a Safety Flag, as in diagram 02)
        AI-->>KA: ready
        API->>API: price: $5, or $2.50 for subscribers until discounted spend<br/>this month reaches the subscription fee ($10), then $5 again
        KA->>STR: Submit and Pay with saved card or Checkout
        STR->>DB: via stripe-webhook: paid, enqueue draft
    end
    AI->>DB: draft (knowledge first, web to fill gaps), safety check 2, awaiting_creator
    DB-->>CW: Realtime: Inbox item tagged "Ask Sweetlife Flora"
    Note over CW: Creator review identical to diagram 02 step 5: flag review if flagged,<br/>mandatory edit + tags, text and/or voice note, safety check 3,<br/>flagged answers go to the ProfessorDM team before delivery

    rect rgb(232, 245, 233)
    Note over U,EM: 5. Delivery in the app inbox + follower options
    end
    DB-->>KA: answer in the app Inbox (Realtime) with buttons:<br/>Send Follow-up | Accept answer | Request refund
    API->>EM: "Your answer is ready" notification email
    alt Send Follow-up (only during the 3-day hold, 3 included, on topic)
        U->>KA: follow-up
        KA->>API: POST /questions/:id/followups
        Note over KA,CW: Same as diagram 02 step 7
    else Accept answer
        U->>KA: Accept, then rate 1-5 stars + optional review
        KA->>API: POST /questions/:id/accept { stars, review }
    else Request refund (only during the 3-day hold)
        U->>KA: pick a reason
        KA->>API: POST /questions/:id/refund-request
    end

    rect rgb(240, 249, 255)
    Note over SCH,DB: 6. Scheduler (same job as diagram 02)
    end
    SCH->>KA: day 2: in-app survey + email "Happy with your answer?" Accept | Follow-up | Refund
    SCH->>DB: day 3, no refund: auto-accept, close follow-ups + refunds,<br/>money to Available, queue embed for the knowledge base

    rect rgb(227, 242, 253)
    Note over U,DB: 7. Profile
    end
    U->>KA: Profile: name, photo, notification settings (email / push)
    KA-->>U: plan (Free Trial or Monthly), trial answers left, renewal date,<br/>upgrade / cancel, saved card (last 4), question history with status
    Note over KA: User states: pending payment, pending answer, needs your reply, answered,<br/>follow-up available, accepted, refund requested, refunded, refund denied
```

---

## 03 — Backend & Instagram (Akshay)

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% OWNER: Akshay, Backend + Instagram Integration Lead.
    %% Arc: everything that enters or leaves ProfessorDM (Meta, Stripe) + backend routing.
    participant META as Meta Graph API
    participant WH as ig-webhook λ
    participant SW as stripe-webhook λ
    participant API as api λ
    participant Q as SQS ai-jobs / outbound
    participant SND as sender λ
    participant DB as Supabase
    participant STR as Stripe
    participant EM as Resend

    rect rgb(227, 242, 253)
    Note over META,DB: A. One-time connect (Sprint 0 SCRUM-25: Meta app review is the top schedule risk)
    end
    Note over META: Test on a dev IG account first, then Sweetlife Flora.<br/>Matrix permissions: instagram_business_basic,<br/>instagram_business_manage_messages, pages_messaging.<br/>Confirm during app review: human agent tag limit (likely 7 days)<br/>and whether it needs separate approval.
    API->>META: OAuth code exchange, then long-lived token
    API->>DB: store token in Supabase Vault, expires_at
    API->>META: subscribe app to messages webhook
    Note over API,META: Scheduled token refresh before expiry, alert on failure

    rect rgb(255, 243, 224)
    Note over META,Q: B. Inbound (DMs, clarification replies, follow-ups)
    end
    META->>WH: POST /webhooks/instagram
    WH->>WH: verify X-Hub-Signature-256 with app secret
    alt bad signature
        WH-->>META: 401, log, drop
    else valid
        WH->>DB: upsert by mid (idempotent), update follower last_inbound_at
        WH->>DB: download attachment before Meta URL expires, save to Storage
        WH->>DB: route: new message, clarification reply, follow-up on open question,<br/>or quick-reply tap (Accept, Request refund + reason, star rating)
        WH->>Q: ai-jobs { type, ids }
        WH-->>META: 200 fast
    end

    rect rgb(232, 245, 233)
    Note over SW,Q: C. Stripe events (test mode until the approved live trial)
    end
    STR->>SW: POST /webhooks/stripe
    SW->>SW: verify Stripe-Signature, idempotent on event id
    SW->>DB: payment succeeded: question paid, ledger rows (platform fee 15-20 percent from settings, creator the rest)
    SW->>Q: ai-jobs { type: draft }
    SW->>DB: subscription created, renewed, cancelled: consumer premium state,<br/>renewal resets the subscriber discount counter
    SW->>DB: customer + saved card for Knowledge App users (Submit and Pay)
    SW->>DB: charge refunded: question refunded, ledger reversal

    rect rgb(243, 232, 255)
    Note over SND,META: D. Outbound (Ask link, clarification, confirmation, answer, follow-up reply, rating prompt, survey)
    end
    Q->>SND: outbound job
    SND->>DB: read follower last_inbound_at
    alt inside 24h of follower's last message
        SND->>META: POST /messages standard
    else past 24h, creator-written reply, inside human agent limit
        SND->>META: POST /messages with HUMAN_AGENT tag (human-written only, never for automated DMs)
    else window closed
        SND->>DB: answer page stays readable via ask_token link
        SND->>EM: email the link (email from Stripe checkout)
        SND->>DB: delivery_mode = fallback_email
    end
    alt 429 or 5xx
        SND->>Q: retry with backoff, then DLQ + alert creator
    else sent
        SND->>DB: outbound_messages status = sent, meta_message_id
    end
    Note over SND,META: Answers + follow-up replies carry quick-reply buttons:<br/>Ask a follow-up | Accept answer | Request refund
    Note over SND,DB: HUMAN_AGENT is only for creator-written replies. Automated DMs (day-2 survey,<br/>rating prompt, status) go out only inside 24h, otherwise by email.<br/>Creator Inbox shows a reply-by countdown. Limits documented in docs/meta-constraints.md

    rect rgb(255, 235, 238)
    Note over API,STR: E. Command routing for the two apps (JWT from Supabase Auth checked in api)
    end
    API->>DB: approve answer: checks edited + tagged, then ai-jobs final_screen
    API->>DB: override classification: re-route message
    API->>STR: approve refund: create refund (only while hold is open)
    API->>DB: search, ask (discount rule), follow-up, accept + rating, refund request (consumer app)
    API->>DB: moderation decision by ProfessorDM team releases or holds a flagged answer
    Note over API,DB: Contracts: docs/contracts (queue payloads with Chinmay,<br/>inbox events with Ritvik, ask + checkout events with Arun)
```

---

## 04 — AI & Knowledge Worker (Chinmay)

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% OWNER: Chinmay, AI + Knowledge Systems Lead. Guardrails + eval gates co-owned with Karthik.
    %% One ai-worker Lambda running LangGraph JS graphs, chosen by the SQS job type.
    participant SQS as SQS<br/>ai-jobs + outbound
    participant AI as ai-worker<br/>(Chinmay, LangGraph JS)
    participant MOD as OpenAI Moderation<br/>+ embeddings
    participant OR as OpenRouter
    participant GEM as Gemini 3.1 Flash-Lite
    participant CLN as Claude Sonnet 5
    participant GPT as GPT-5.6 Terra<br/>(fallback)
    participant DB as Supabase + pgvector<br/>(Karthik)
    participant CW as Creator Workspace<br/>(Ritvik)

    rect rgb(255, 235, 238)
    Note over SQS,DB: FLOW 1  TRIAGE  job: triage. Runs BEFORE any payment.
    end
    SQS->>AI: { type: triage, messageId }
    AI->>DB: load message text, images, thread history
    Note over AI,MOD: Safety checkpoint 1 (inbound).<br/>L1 OpenAI Moderation, L2 deterministic domain rules (list signed off by Kristin),<br/>L3 policy classifier for gray areas
    AI->>MOD: L1 moderation on text + image
    MOD-->>AI: result
    AI->>AI: L2 domain rules, L3 policy classifier via OpenRouter
    alt prohibited content (severe moderation hit)
        AI->>DB: category = safety_concern, status = blocked, audit_log, decline message queued
    else clean or risk topic
        opt risk topic (e.g. toxic plant near edibles, chemical misuse)
            AI->>DB: safety_flag (checkpoint 1), continues with a Safety Flag badge,<br/>creator reviews it in her Moderation tab before answering
        end
        AI->>OR: classify(message, creator profile)
        OR->>GEM: structured output request
        GEM-->>OR: { category, confidence, reason }
        OR-->>AI: classification
        AI->>DB: save category + confidence + prompt version
        Note over AI,DB: expert_question, needs_clarification, social, spam_irrelevant,<br/>safety_concern, service_request. Low confidence is marked for creator override.
        alt needs_clarification
            AI->>OR: generateClarification(message)
            OR->>GEM: targeted questions: plant, light, watering, photos
            GEM-->>AI: clarification text
            AI->>SQS: outbound { type: clarification }  (sent by Akshay's sender)
        else expert_question
            AI->>DB: create question pending_payment (flagged if risk topic), then Ask link queued
        else social, spam_irrelevant, service_request
            AI->>DB: route per diagram 02, no AI reply
        end
    end

    rect rgb(255, 243, 224)
    Note over SQS,DB: FLOW 2  REASSESS  job: reassess (follower answered a clarification)
    end
    SQS->>AI: { type: reassess, messageId }
    AI->>OR: re-classify with original + clarification replies (Gemini)
    OR-->>AI: ready or still vague
    alt ready
        AI->>DB: create question pending_payment
    else still vague and under 2 rounds
        AI->>SQS: another clarification
    else still vague after 2 rounds
        AI->>DB: send to creator Incoming view to decide
    end

    rect rgb(243, 232, 255)
    Note over SQS,CW: FLOW 3  DRAFT  job: draft. Runs AFTER payment.
    end
    SQS->>AI: { type: draft, questionId }
    AI->>MOD: embed question (text-embedding-3-small)
    AI->>DB: pgvector top-k, creator knowledge first
    DB-->>AI: entries + ids for citations
    alt knowledge coverage low (cannot give a complete answer)
        AI->>OR: web search to fill the gaps (tool choice in ADR, e.g. OpenRouter web plugin)
        OR-->>AI: web results with URLs
    end
    AI->>OR: draft(question, clarifications, image context, entries, web results)
    OR->>CLN: grounded draft in creator voice guide
    alt provider error or timeout
        OR->>GPT: same request
        GPT-->>OR: fallback draft
    else ok
        CLN-->>OR: draft
    end
    OR-->>AI: draft text, each part labeled: creator knowledge | web (with URL) | model
    AI->>MOD: safety checkpoint 2 (draft), L1 to L3
    AI->>DB: insert draft, citations, model + prompt version, flags
    DB-->>CW: Realtime: AI draft ready

    rect rgb(255, 243, 224)
    Note over SQS,CW: FLOW 4  FOLLOW-UP  job: followup
    end
    SQS->>AI: { type: followup, questionId, followupId }
    AI->>OR: on-topic check with full thread (Gemini)
    alt on topic
        AI->>OR: assisted reply (Claude Sonnet 5, knowledge first, web if needed), safety checkpoint 2
        AI->>DB: follow-up draft awaiting_creator
    else off topic
        AI->>DB: off_topic flag, creator decides
    end

    rect rgb(255, 235, 238)
    Note over SQS,DB: FLOW 5  FINAL SCREEN  job: final_screen (creator pressed Submit)
    end
    SQS->>AI: { type: final_screen, draftId }
    AI->>MOD: safety checkpoint 3 on the creator's final text, L1 to L3
    alt clean
        AI->>SQS: outbound { type: answer }
    else flagged
        AI->>DB: status = professordm_review, safety_flag (checkpoint 3).<br/>ProfessorDM team reviews before delivery, feedback to creator's Moderation tab
    end

    rect rgb(227, 242, 253)
    Note over SQS,DB: FLOW 6  KNOWLEDGE  jobs: embed, ingest, kb_safety_review
    end
    SQS->>AI: { type: embed, questionId }  queued by the scheduler when the 3-day hold ends,<br/>never for refunded questions
    AI->>AI: anonymize (remove handle, names, PII). Voice note kept with the same tags
    AI->>MOD: embed Q+A
    AI->>DB: knowledge_entries row: text, tags, source, published flag, embedding
    SQS->>AI: { type: ingest, docId }  seed docs from Kristin (about 110) or a fact the creator added by hand
    AI->>AI: chunk
    AI->>MOD: batch embed
    AI->>DB: knowledge_entries rows
    Note over DB: Drafting reads all creator knowledge, including facts the creator added by hand.<br/>Knowledge App search reads published entries only.
    SQS->>AI: { type: kb_safety_review }  weekly, from the scheduler
    AI->>MOD: re-run safety layers over knowledge_entries
    AI->>DB: flagged entries to the creator and/or ProfessorDM team for review

    rect rgb(232, 245, 233)
    Note over AI,DB: FLOW 7  EVALUATION  eval/ (gates with Karthik, search UX with Arun)
    end
    Note over AI,DB: Golden set of real Sweetlife Flora DMs. Classification accuracy + confusion matrix.<br/>Retrieval relevance, 3-small vs 3-large benchmark BEFORE committing (matrix).<br/>Grounding + web-source accuracy + safety red-team cases. No prompt or model change merges below baseline.
```

---

## 05 — Creator Workspace & Transactions (Ritvik)

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% OWNER: Ritvik, Creator Application + Transaction Workflow Lead.
    %% Creator Workspace = the "control tower". Vercel project 1.
    %% Reads via Supabase RLS + Realtime. Every write goes through api (Akshay).
    actor CR as Creator (Kristin)
    actor AD as ProfessorDM team
    participant CW as Creator Workspace<br/>(Ritvik)
    participant API as api<br/>(Akshay)
    participant DB as Supabase<br/>(Karthik)
    participant AI as ai-worker<br/>(Chinmay)
    participant STR as Stripe

    rect rgb(255, 243, 224)
    Note over CR,DB: FLOW 1  Sign in, ProfessorDM Bank as home, Incoming Messages
    end
    CR->>CW: sign in (Supabase Auth, role creator, invite only in V1)
    CW-->>CR: lands on ProfessorDM Bank (home page), refund banner if any
    CW->>DB: read inbound messages with AI label + confidence (RLS)
    CW-->>CR: Incoming: Expert Question, Needs Clarification, Social, Spam, Safety, Service
    CR->>CW: override a wrong label (e.g. Social to Expert Question)
    CW->>API: POST /messages/:id/override
    API->>DB: new category, audit_log, re-route (Ask link queued if Expert)

    rect rgb(232, 245, 233)
    Note over CR,DB: FLOW 2  Inbox tab: paid questions from every channel in one queue
    end
    DB-->>CW: Realtime: new paid question, AI draft ready
    CW-->>CR: card: source tag Instagram or Ask Sweetlife Flora, $4.00 earned,<br/>AI draft ready, awaiting answer / in progress, follow-ups left, reply-by timer,<br/>Safety Flag badge if flagged
    Note over CW: Tabs with counts: Inbox | Sent | Moderation. Refund requests pinned at the top of Inbox.

    rect rgb(255, 235, 238)
    Note over CR,AI: FLOW 3  Answer (HUMAN IN THE LOOP, mandatory)
    end
    opt question has a Safety Flag
        CR->>CW: review the flag in the Moderation tab first, then the question unlocks
        CW->>API: POST /moderation/:flagId/creator-review
    end
    CR->>CW: open question
    CW-->>CR: question, photos, clarification history, classification, safety flags,<br/>AI draft with sources labeled: creator knowledge | web (URL)
    CR->>CW: rewrite in own voice, answer as text and/or voice note (or save draft, or decline)
    CR->>CW: add tags
    CW->>CW: SEND GATE: text changed from draft? at least one tag?
    alt unchanged or no tags
        CW-->>CR: blocking warning: "You are the expert. Make this answer yours."
    else passes
        CR->>CW: Submit answer
        CW->>API: POST /drafts/:id/approve { finalText, voiceNote?, tags }
        API->>API: re-check gate server side (HITL enforced in api, not only UI)
        API->>DB: status approved, edit_distance, audit_log
        API->>AI: ai-jobs final_screen (safety checkpoint 3)
        alt clean
            AI-->>DB: outbound queued, then delivered
            DB-->>CW: Realtime: moves to Sent
        else flagged
            AI-->>DB: professordm_review, shows in Moderation tab as "with ProfessorDM team"
        end
    end
    alt Decline
        CR->>CW: Decline with reason
        CW->>API: POST /questions/:id/decline
        API->>STR: full refund
        API->>DB: status declined_refunded, ledger reversal
    end

    rect rgb(243, 232, 255)
    Note over CR,AI: FLOW 4  Sent tab: follow-ups, accept, rating
    end
    DB-->>CW: Realtime: follow-up #1 arrived, AI reply draft ready
    CW-->>CR: thread view: 1 of 3 used, off-topic flag if any, 3-day hold reminder
    CR->>CW: edit + Submit (same gate + safety check as FLOW 3)
    CW->>API: POST /followups/:id/approve
    API->>DB: followups_used + 1, final_screen, outbound
    Note over CW: Follow-ups only while the 3-day hold is open.<br/>Sent card shows: answer sent, answer accepted, stars + review, funds released

    rect rgb(255, 243, 224)
    Note over CR,STR: FLOW 5  Refund requests (only inside the 3-day hold)
    end
    DB-->>CW: Realtime: refund requested, reason, sent answer (also a banner in the Bank)
    alt Revisit Answer (always try this first, per the guide)
        CR->>CW: Revisit, edit answer, send again through FLOW 3 gate, payment kept
    else Approve Refund
        CR->>CW: Approve
        CW->>API: POST /refunds/:id/approve
        API->>STR: create refund (from the held money)
        STR-->>DB: charge.refunded via stripe-webhook: refunded, ledger reversal
    else Deny
        CR->>CW: Deny (e.g. follow-ups not used, or revised answer already sent)
        CW->>API: POST /refunds/:id/deny { note }
        API->>DB: refund_denied, audit_log, follower notified
    end
    Note over CR,STR: ProfessorDM does not mediate. The follower can contact ProfessorDM on social media.<br/>After the 3-day hold, refund requests close.

    rect rgb(255, 235, 238)
    Note over CR,AD: FLOW 6  Moderation tab (two kinds of flagged items)
    end
    CW-->>CR: 1. flagged follower QUESTIONS: creator reviews before she can answer
    CW-->>CR: 2. flagged creator ANSWERS: sent to the ProfessorDM team before delivery
    AD->>CW: admin view (role admin): review flagged answer, approve or send back
    CW->>API: POST /moderation/:flagId/decision { decision, feedback }
    API->>DB: decision + reviewer + time in audit_log.<br/>Approved: delivery queued. Sent back: feedback shown in creator's Moderation tab
    Note over CW,DB: Also lands here: knowledge entries flagged by the weekly AI safety review

    rect rgb(232, 245, 233)
    Note over CR,DB: FLOW 7  ProfessorDM Bank (payout STATUS only in V1)
    end
    CR->>CW: open ProfessorDM Bank
    CW->>DB: ledger + questions
    DB-->>CW: tiles: Available Now | Pending (3-day hold) | Total Balance, plus Lifetime
    CW-->>CR: transaction list filterable by status: unanswered, in progress<br/>("available in 3 days"), completed, refund requested
    CR->>CW: Withdraw Available Balance (only Available Now)
    CW->>API: POST /payouts
    API->>DB: payout requested. ProfessorDM pays by manual transfer, admin marks paid
    Note over CW,DB: Payout mode (creator setting): Automatic = paid every Friday after the hold.<br/>On Demand = held until requested, auto-paid after 30 days (scheduler).<br/>V1: no Stripe Connect, money in ProfessorDM's Stripe, split tracked in Postgres.

    rect rgb(227, 242, 253)
    Note over CR,AI: FLOW 8  Edit Profile + Knowledge Database
    end
    CR->>CW: Edit Profile: photo, bio, question price, follow-ups included,<br/>payout method, payout mode, notification preferences, expected answer time,<br/>Knowledge Database on/off, subscription price, subscriber discount
    CW->>API: PUT /creator/settings
    CR->>CW: Knowledge Database (creator only): edit past answers, add/edit/remove tags,<br/>add new facts by hand, unpublish
    CW->>API: POST /knowledge
    API->>AI: ai-jobs ingest or embed
```

---

## 06 — Consumer App (Arun)

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% OWNER: Arun, Consumer Knowledge Experience Lead. Vercel project 2 (Consumer App).
    %% Two surfaces in one app: the pre-paywall Ask page for IG followers, and Ask [Creator]
    %% (V1 = Ask Sweetlife Flora, white-label per creator). Responsive web in V1; native App Store apps deferred.
    actor F as IG follower
    actor U as Knowledge App user
    participant CA as Consumer App<br/>(Arun)
    participant AU as Supabase Auth
    participant API as api<br/>(Akshay)
    participant DB as Supabase<br/>(Karthik)
    participant STR as Stripe

    rect rgb(255, 243, 224)
    Note over F,STR: SCREEN 1  Pre-paywall Ask page  /ask/[token]  (ProfessorDM branded, no account)
    end
    F->>CA: tap Ask link from the DM
    CA->>API: GET /ask/:token (signed, expires)
    API->>DB: question text, price from creator settings
    CA-->>F: "Ask a Question": question summary (editable), add photos (optional, max 3), $5,<br/>"Get a personal answer from me. I'll review your question and respond directly."
    F->>CA: edit question, add photos, tick the paywall acknowledgment
    CA->>API: PUT /ask/:token { text, photos }
    F->>CA: Submit Question
    CA->>STR: redirect to Stripe Checkout (payment mode)
    STR-->>CA: return to /ask/:token/status
    CA-->>F: "Question sent. Your answer will arrive in your Instagram DMs."

    rect rgb(232, 245, 233)
    Note over F,DB: SCREEN 2  Ask status page  /ask/[token]/status
    end
    CA->>DB: status via api
    CA-->>F: pending or answered. Instagram answers are delivered in Instagram, not here.<br/>Fallback only: shows the answer if the Instagram messaging window had closed

    rect rgb(227, 242, 253)
    Note over U,AU: SCREEN 3  Sign up / login modal  (Sweetlife Flora branded)
    end
    U->>CA: Browse Knowledge
    CA-->>U: "Sign in to access verified plant care answers." Sign up free,<br/>"No payment needed until you subscribe or ask an expert."
    U->>CA: Google, Apple, Microsoft, or email + password (forgot password link)
    CA->>AU: sign up or sign in, role consumer
    AU-->>CA: session
    CA-->>U: home: logo, search bar, popular topics, "5 / 5 free answers remaining"

    rect rgb(243, 232, 255)
    Note over U,DB: SCREEN 4  Search results + Premium gate
    end
    U->>CA: search "thrips" or tap a topic
    CA->>API: POST /search { query }
    API->>DB: pgvector over published entries
    DB-->>CA: result cards: title, preview, tags, Premium badge after the trial
    U->>CA: open answer
    alt subscriber
        CA-->>U: full answer
    else trial answers left (one-time 5, never resets)
        CA->>API: POST /entries/:id/view
        CA-->>U: full answer, counter updated
    else trial used up
        CA-->>U: Premium gate: subscribe (no per-answer purchase)
    end
    CA-->>U: call to action: "Need more specific advice? Ask the Expert"

    rect rgb(255, 235, 238)
    Note over U,STR: SCREEN 5  Ask the Expert  (open to everyone, trial users included)
    end
    CA-->>U: creator card: name, price, "3 free follow-ups included", Available Now
    U->>CA: question + photo
    CA->>API: POST /questions { source: knowledge_app }
    API-->>CA: triage result + price
    alt needs clarification
        CA-->>U: clarification questions in the app, user revises + adds photos, re-check
    else not accepted (prohibited)
        CA-->>U: "We can't accept this question" with reason category
    else ready
        CA-->>U: price: $5, or $2.50 for subscribers until this month's discounted spend<br/>reaches the subscription fee, then $5 (resets on renewal)
        U->>CA: Submit and Pay (saved card) or Checkout
        CA->>STR: payment
        STR-->>CA: paid, pending answer
    end

    rect rgb(232, 245, 233)
    Note over U,DB: SCREEN 6  Inbox (answers to app questions only)
    end
    DB-->>CA: Realtime: answer ready (in-app notification + email via Resend)
    CA-->>U: question, full answer (text and/or voice note), dates, status,<br/>buttons during the 3-day hold: Send Follow-up | Accept answer | Request Refund
    alt Send Follow-up (3 included, must be on topic)
        U->>CA: follow-up
        CA->>API: POST /questions/:id/followups
    else Accept answer
        U->>CA: Accept, then 1-5 stars + optional review
        CA->>API: POST /questions/:id/accept { stars, review }
    else Request Refund
        U->>CA: pick a reason
        CA->>API: POST /questions/:id/refund-request { reason }
    end
    CA-->>U: day 2: satisfaction survey banner + email (Accept | Follow-up | Refund)
    Note over CA: After the hold: buttons disappear, answer counts as accepted

    rect rgb(227, 242, 253)
    Note over U,STR: SCREEN 7  Profile + subscription
    end
    U->>CA: Profile icon
    CA-->>U: name, email, photo, notification settings (email / push),<br/>plan (Free Trial or Monthly $10), trial answers left, renewal date,<br/>upgrade / cancel, saved card (last 4) + update, question history with status
    U->>CA: Upgrade to Monthly
    CA->>STR: Checkout (subscription mode)
    STR-->>CA: premium active after webhook
    Note over CA: Clear copy for every state: pending payment, pending answer, needs your reply,<br/>answered, follow-up available, accepted, refund requested, refunded, refund denied.<br/>Search UX evaluation with Chinmay.
```

---

## 07 — Cloud & Security (Karthik)

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#FEFCE8','primaryTextColor':'#1C1917','primaryBorderColor':'#CA8A04','lineColor':'#64748B','background':'#FFFFFF'}}}%%
flowchart TB
    %% OWNER: Karthik, Cloud, Data, Security + Quality Lead, and Technical Architecture Coordinator.
    %% Coordinates architecture, does not assign day-to-day work (roles doc).

    subgraph ARCH["ARCHITECTURE COORDINATION"]
        A1["this diagram pack + docs/BASELINE.md"]
        A2["interface contracts in packages/contracts<br/>queue payloads, api routes, status enums"]
        A3["ADRs in docs/adr  any change touching<br/>another workstream gets an ADR first"]
        A4["weekly cross-lead integration check"]
    end

    subgraph ENV["ENVIRONMENTS  see diagram 10"]
        E1["local: Supabase CLI + Stripe test"]
        E2["staging: Supabase staging project, AWS staging stack,<br/>Vercel preview, Meta dev IG test account"]
        E3["production beta: created at Beta RC Mar 2027,<br/>Sweetlife Flora, Stripe live only if approved"]
        E4["scheduler: EventBridge hourly job,<br/>same in staging + prod"]
    end

    subgraph DATA["DATA ARCHITECTURE"]
        D1["schema + SQL migrations  supabase/migrations"]
        D2["RLS on every table, deny by default"]
        D3["pgvector index tuning with Chinmay"]
        D4["Supabase daily backups, restore drill before beta"]
    end

    subgraph SEC["SECURITY + PRIVACY"]
        S1["roles: creator, admin (ProfessorDM team), consumer<br/>service key only inside Lambdas<br/>consumer logins: email, Google, Apple, Microsoft"]
        S2["secrets: Vercel env vars, AWS SSM SecureString,<br/>GitHub OIDC to AWS. No secrets in code, rotate if leaked"]
        S3["webhook signatures: Meta HMAC + Stripe"]
        S4["Meta token in Supabase Vault"]
        S5["private Storage buckets, short signed URLs"]
        S6["PII: Sentry scrubbing before real DMs,<br/>anonymize before knowledge publish"]
        S7["retention: see BASELINE.md section 5"]
        S8["accounts owned by ProfessorDM email, never student or ASU email"]
    end

    subgraph OBS["OBSERVABILITY"]
        O1["Sentry free: apps + Lambdas"]
        O2["Supabase logs: DB, auth, storage"]
        O3["audit_log: state changes, moderation,<br/>creator actions, append only"]
        O4["events table feeds Amplitude"]
        O5["DLQ depth + failed delivery alerts"]
    end

    subgraph QA["TEST STRATEGY + RELEASE GATES"]
        Q1["each lead: unit tests in own workstream  Vitest"]
        Q2["Karthik: Playwright E2E on golden paths 02 + 02b"]
        Q3["contract tests on queue payloads"]
        Q4["AI eval gates with Chinmay: no prompt or model<br/>change merges if eval drops below baseline"]
        Q5["milestone gate: Kristin demo sign-off"]
        Q6["pre-beta: security, privacy, performance,<br/>resilience review  Mar 5 2027"]
    end

    subgraph GR["AI GUARDRAILS  co-owned with Chinmay"]
        G1["blocked category list, Kristin signs off"]
        G2["3 checkpoints: inbound, draft, final<br/>+ weekly knowledge base review"]
        G4["2 tiers: prohibited = blocked,<br/>risk topic = Safety Flag + creator review"]
        G5["flagged creator answers need<br/>ProfessorDM team approval"]
        G6["web search results: cited, labeled,<br/>safety-checked, never auto-sent"]
        G3["HITL enforced in api, not only in UI"]
    end

    ARCH --> ENV --> DATA --> SEC --> OBS --> QA
    GR -.-> QA
    ARCH -.-> GR

    style ARCH fill:#FFFBEB,stroke:#D97706,color:#451A03
    style ENV fill:#F0FDF4,stroke:#15803D,color:#14532D
    style DATA fill:#F0FDFA,stroke:#0F766E,color:#134E4A
    style SEC fill:#FFF1F2,stroke:#E11D48,color:#881337
    style OBS fill:#FEF9C3,stroke:#CA8A04,color:#713F12
    style QA fill:#EFF6FF,stroke:#2563EB,color:#1E3A8A
    style GR fill:#FAF5FF,stroke:#7C3AED,color:#4C1D95
```

---

## 08 — Process & Beta (Maximo)

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#FEFCE8','primaryTextColor':'#1C1917','primaryBorderColor':'#CA8A04','lineColor':'#64748B','background':'#FFFFFF'}}}%%
flowchart TB
    %% OWNER: Maximo, Process Optimization + Beta Validation Lead (Industrial Engineering).
    %% Not an auxiliary software developer. Owns process + beta design, not QA or schedule.

    subgraph MAP["1 PROCESS MAPS"]
        M1["current state: Kristin answering DMs by hand<br/>6-8 hrs a day at peak"]
        M2["target state: DM > classify > clarify > pay ><br/>review > deliver > follow-up > knowledge"]
        M3["value stream: delays, handoffs,<br/>duplicate work, failure points"]
    end

    subgraph MEAS["2 MEASURES  from events table + Amplitude"]
        K1["cycle time: DM to answer delivered"]
        K2["clarification success rate"]
        K3["search success in Knowledge App"]
        K4["creator effort: time in review, edit size"]
        K5["moderation incidence"]
        K6["error and retry frequency"]
        K7["completion friction: Ask link to paid"]
    end

    subgraph BETA["3 CONTROLLED TRIAL DESIGN"]
        B1["scenarios + scripts with Nova and Kristin"]
        B2["participant consent + recruitment<br/>Kristin first, then small Sweetlife Flora group"]
        B3["observation plan + feedback form"]
        B4["trial complete  Apr 9 2027"]
    end

    subgraph IMP["4 IMPROVE"]
        R1["root-cause analysis on failures"]
        R2["SOPs + one-point lessons to run the trial<br/>and onboard creators later"]
        R3["prioritized recommendations for commercial MVP"]
    end

    MAP --> MEAS --> BETA --> IMP
    IMP -. "findings into Jira via Nova" .-> MAP

    subgraph HAND["HANDOFFS"]
        H1["Ritvik: creator workflow efficiency,<br/>moderation + refund burden"]
        H2["Arun: consumer search, ask, friction"]
        H3["Akshay, Chinmay, Karthik: link failures<br/>to telemetry and eval data"]
        H4["Kristin: turn observations into requirements"]
    end
    IMP -.-> HAND

    NOTE["Post-capstone: ProfessorDM runs broader beta May-Aug 2027<br/>with about 50 creators on the V1 we hand off"]

    style MAP fill:#EFF6FF,stroke:#2563EB,color:#1E3A8A
    style MEAS fill:#F0FDFA,stroke:#0F766E,color:#134E4A
    style BETA fill:#FEF9C3,stroke:#CA8A04,color:#713F12
    style IMP fill:#F0FDF4,stroke:#15803D,color:#14532D
    style HAND fill:#FFF1F2,stroke:#E11D48,color:#881337
    style NOTE fill:#F8FAFC,stroke:#94A3B8,color:#334155,stroke-dasharray:4
```

---

## 09 — Delivery & Integration (Nova)

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#FEFCE8','primaryTextColor':'#1C1917','primaryBorderColor':'#CA8A04','lineColor':'#64748B','background':'#FFFFFF'}}}%%
flowchart TB
    %% OWNER: Nova, Project Manager + Delivery Integration Lead.
    %% Owns WHEN and WHO. Technical leads own HOW. Kristin owns WHAT and final acceptance.
    %% Dates = sponsor milestone framework (Roles doc section 6). ASU deadlines take precedence.

    subgraph FALL["FALL 2026  Architecture, Connectivity, Core Intelligence  (classes end Dec 4)"]
        direction LR
        F1["Sep 18<br/>Team + project baseline<br/>Nova + all"]
        F2["Sep 25<br/>V1 requirements +<br/>architecture baseline<br/>Karthik + leads"]
        F3["Oct 16<br/>Platform + Instagram demo<br/>webhook, in/out test DMs,<br/>app shells<br/>Akshay / Karthik"]
        F4["Oct 30<br/>AI + Knowledge slice<br/>classify, clarify, retrieval,<br/>draft, initial safety<br/>Chinmay + team"]
        F5["Nov 13<br/>End-to-end Alpha 0.1<br/>IG question to inbox, draft,<br/>review, answer back to IG<br/>All technical"]
        F6["Dec 1<br/>Semester 1 release<br/>stable alpha, test evidence,<br/>Spring backlog<br/>Nova + all"]
        F1 --> F2 --> F3 --> F4 --> F5 --> F6
    end

    subgraph SPR["SPRING 2027  Full Workflow, Consumer Experience, Beta Readiness  (classes end Apr 30)"]
        direction LR
        P1["Jan 22<br/>Spring re-baseline<br/>Nova + leads"]
        P2["Feb 12<br/>Feature-complete Alpha 0.5<br/>Stripe test flow, follow-ups,<br/>moderation, search<br/>All technical"]
        P3["Mar 5<br/>Internal Beta 0.8<br/>hardening, regression,<br/>trial scripts<br/>Karthik / Maximo"]
        P4["Mar 26<br/>Beta RC 1.0<br/>acceptance tests pass,<br/>prod env ready<br/>Nova + all"]
        P5["Apr 9<br/>Controlled Sweetlife<br/>Flora trial done<br/>Maximo / Nova"]
        P6["Apr 23<br/>Critical fixes +<br/>beta findings<br/>All"]
        P7["Apr 30<br/>Final handoff V1 MVP<br/>Nova + all"]
        P1 --> P2 --> P3 --> P4 --> P5 --> P6 --> P7
    end

    F6 --> P1

    subgraph PM["NOVA RUNS"]
        direction LR
        N1["integrated master schedule<br/>2-week sprints, sprint ends<br/>aligned to milestone dates"]
        N2["Jira: epics per workstream,<br/>tickets tagged with diagram flow"]
        N3["risk, issue, decision,<br/>dependency, action logs"]
        N4["sponsor status: decisions,<br/>risks, demos only"]
        N5["change control: clarification<br/>vs scope change"]
        N6["beta readiness with Maximo"]
        N7["final handoff package"]
    end

    subgraph RISK["TOP RISKS ON THE REGISTER NOW"]
        R1["Meta app review time<br/>SCRUM-25, blocks Oct 16"]
        R2["24h messaging window<br/>vs creator answer time"]
        R3["Stripe live trial approval"]
        R4["account access runs through Kristin<br/>Vercel codes, JM on Instagram"]
    end

    PM -.-> FALL
    PM -.-> SPR
    RISK -.-> PM

    style FALL fill:#EFF6FF,stroke:#2563EB,color:#1E3A8A
    style SPR fill:#F0FDF4,stroke:#15803D,color:#14532D
    style PM fill:#FFFBEB,stroke:#D97706,color:#451A03
    style RISK fill:#FFF1F2,stroke:#E11D48,color:#881337
```

---

## 10 — Deployment Environments

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% OWNER: Karthik. Trunk-based: feature branch > PR > main > staging. Tag > production.
    %% GitHub Free cannot enforce branch protection on private repos, so review is by team rule.
    %% Vercel Pro: 1 deploying seat. CI deploys with one token, everyone else is a free Viewer.
    actor DEV as Developer
    participant GH as GitHub<br/>ProfessorDM org
    participant GHA as GitHub Actions
    participant VPV as Vercel preview
    participant STG as staging<br/>Supabase staging, AWS staging,<br/>Stripe test, Meta dev app
    actor KR as Kristin
    participant PRD as production beta<br/>from Mar 2027

    rect rgb(255, 243, 224)
    Note over DEV,VPV: PHASE 1  Local + pull request
    end
    DEV->>DEV: local: Supabase CLI stack, Stripe test keys, no real DMs
    DEV->>GH: push feature/SCRUM-xx-short-name
    DEV->>GH: open PR to main, fill template (ticket, diagram flow, tests)
    GH->>GHA: CI workflow
    GHA->>GHA: lint + typecheck + Vitest + build both apps + SAM build
    GHA->>GHA: contract tests on packages/contracts
    GHA->>GHA: AI eval gate if prompts or models changed
    GHA->>VPV: vercel deploy (token) for Creator Workspace + Consumer App
    GHA-->>GH: preview URLs + CI status on the PR

    rect rgb(255, 235, 238)
    Note over GH,GHA: PHASE 2  Review (team rule, CODEOWNERS requests reviewers)
    end
    GH-->>DEV: 1 approval from the owning lead + green CI before merge
    Note over GH: Cross-workstream change: second approval from Karthik + ADR link.<br/>If rules get skipped, upgrade org to GitHub Team to enforce them.

    rect rgb(232, 245, 233)
    Note over GH,STG: PHASE 3  Merge to main deploys staging
    end
    DEV->>GH: squash merge to main
    GH->>GHA: deploy-staging workflow
    GHA->>STG: supabase db push (migrations)
    GHA->>STG: sam deploy staging (AWS OIDC role, no stored AWS keys)
    GHA->>STG: vercel deploy staging for both apps
    GHA->>GHA: Playwright E2E on golden paths 02 + 02b
    Note over STG: Secrets: Vercel env vars + AWS SSM SecureString.<br/>Test IG account only. Seed knowledge data. Sentry env = staging.

    rect rgb(243, 232, 255)
    Note over STG,KR: PHASE 4  Milestone demo + sign-off
    end
    STG-->>KR: demo on staging at each sponsor milestone
    KR-->>GH: sign-off recorded by Nova in the decision log

    rect rgb(227, 242, 253)
    Note over GH,PRD: PHASE 5  Production (from Beta RC, Mar 26 2027)
    end
    DEV->>GH: tag release v1.x.y (Karthik)
    GH->>GHA: deploy-prod workflow, manual approval step
    GHA->>PRD: supabase db push to prod project, sam deploy prod, vercel --prod
    GHA->>PRD: smoke test
    Note over PRD: Sweetlife Flora IG account. Stripe test unless the live trial is approved.<br/>Supabase daily backups, restore drill done at Beta 0.8.
```

---

## 11 — Data Model ERD

```mermaid
%%{init: {'theme':'base'}}%%
erDiagram
    %% OWNER: Karthik (schema, RLS) with Chinmay (knowledge), Ritvik (workflow), Akshay (messages).
    %% Supabase Postgres + pgvector. RLS on every table. Money in cents, CAD or USD per Stripe account.

    profiles ||--o| creators : "is"
    profiles ||--o| consumers : "is"
    creators ||--|| creator_settings : has
    creators ||--o| ig_accounts : connects
    creators ||--o{ ig_followers : "DMs from"
    creators ||--o{ questions : receives
    creators ||--o{ knowledge_docs : uploads
    creators ||--o{ knowledge_entries : owns
    creators ||--o{ tags : defines
    creators ||--o{ payouts : requests

    ig_followers ||--o{ inbound_messages : sends
    inbound_messages ||--o{ clarification_rounds : has
    inbound_messages ||--o| questions : "becomes"
    ig_followers ||--o{ questions : "asks via IG"
    consumers ||--o{ questions : "asks via app"
    consumers ||--o{ subscriptions : has

    questions ||--o{ drafts : has
    questions ||--o{ followups : has
    questions ||--o{ media : attaches
    questions ||--o{ payments : "paid by"
    questions ||--o{ refund_requests : may_have
    questions ||--o| ratings : "rated by"
    questions ||--o{ question_tags : tagged
    tags ||--o{ question_tags : used_in
    followups ||--o| drafts : "answered by"
    drafts ||--o{ outbound_messages : "delivered as"
    inbound_messages ||--o{ outbound_messages : "replied to by"
    ig_followers ||--o{ outbound_messages : "receives"
    creators ||--o{ outbound_messages : "sends"
    questions ||--o| knowledge_entries : "published as"
    knowledge_docs ||--o{ knowledge_entries : chunked_into

    payments ||--o{ ledger_entries : posts
    subscriptions ||--o{ ledger_entries : posts
    payouts ||--o{ ledger_entries : posts

    profiles {
        uuid id PK "= auth.users.id"
        text role "creator | admin | consumer"
        text display_name
        timestamptz created_at
    }
    creators {
        uuid id PK
        uuid profile_id FK
        text brand_name "Sweetlife Flora"
        text status "setup | active"
    }
    creator_settings {
        uuid creator_id PK
        int question_price_cents "default 500"
        int platform_fee_bps "1500-2000 = 15-20 percent"
        int followups_included "default 3"
        bool knowledge_app_enabled
        int kb_subscription_price_cents "default 1000"
        int free_answer_limit "default 5, one-time trial"
        int subscriber_question_price_cents "default 250"
        text expected_answer_time
        text payout_method
        text payout_mode "automatic weekly Friday | on_demand, auto after 30 days"
    }
    ig_accounts {
        uuid id PK
        uuid creator_id FK
        text ig_user_id UK
        uuid vault_token_id "Supabase Vault"
        timestamptz token_expires_at
        bool human_agent_approved
    }
    ig_followers {
        uuid id PK
        uuid creator_id FK
        text ig_scoped_id UK
        text username
        text email "from Stripe checkout, nullable"
        timestamptz last_inbound_at "24h window"
    }
    consumers {
        uuid id PK
        uuid profile_id FK
        int free_views_used "trial, never resets"
        text auth_provider "email | google | apple | azure"
        text stripe_customer_id "saved card"
    }
    inbound_messages {
        uuid id PK
        uuid follower_id FK
        text mid UK "Meta message id, dedupe"
        text text
        text category "6 categories"
        numeric confidence
        text override_category "creator"
        text status
        text prompt_version
        timestamptz received_at
    }
    clarification_rounds {
        uuid id PK
        uuid message_id FK
        int round "max 2"
        text prompt
        text reply
    }
    questions {
        uuid id PK
        uuid creator_id FK
        text source "instagram | knowledge_app"
        uuid follower_id FK "nullable"
        uuid consumer_id FK "nullable"
        uuid origin_message_id FK "nullable"
        text question_text
        text status "see BASELINE status model"
        bool safety_flagged "risk topic, creator reviews first"
        text ask_token UK "signed link"
        int price_cents
        int followups_included
        int followups_used
        timestamptz paid_at
        timestamptz delivered_at
        timestamptz hold_ends_at "delivered_at + 3 days, to confirm"
        timestamptz survey_sent_at "day 2"
        timestamptz accepted_at "tap or auto at hold end"
    }
    media {
        uuid id PK
        uuid question_id FK
        uuid message_id FK
        text storage_path "private bucket"
        text kind "image | voice_note"
    }
    drafts {
        uuid id PK
        uuid question_id FK
        uuid followup_id FK "nullable"
        text ai_text
        jsonb citations "knowledge ids + web URLs, labeled"
        bool used_web_search
        text model_used
        text prompt_version
        text final_text
        int edit_distance "must be above 0"
        text status
        timestamptz approved_at
    }
    followups {
        uuid id PK
        uuid question_id FK
        int seq
        text text
        bool on_topic
        text status
    }
    tags {
        uuid id PK
        uuid creator_id FK
        text name
    }
    question_tags {
        uuid question_id FK
        uuid tag_id FK
    }
    outbound_messages {
        uuid id PK
        uuid draft_id FK "nullable, null = creator typed it directly"
        text type "ask_link | clarification | confirmation | answer | followup | rating_prompt | survey | decline"
        text delivery_mode "standard | human_agent | fallback_email"
        text meta_message_id
        text status "pending -> sent | failed"
        int attempts
        uuid inbound_message_id FK "nullable, DM this replies after"
        uuid follower_id FK "nullable, recipient = thread"
        text text "nullable, non-blank when direct answer"
        uuid creator_id FK "nullable, sender, used by RLS"
        uuid client_request_id UK "one per Send press, blocks double-click"
        timestamptz created_at "default now()"
    }
    safety_flags {
        uuid id PK
        text target_type "message | draft | final | knowledge_entry"
        uuid target_id
        text checkpoint "1 | 2 | 3"
        text layer "moderation | rules | policy"
        text category
        text status "open | creator_reviewed | approved | sent_back"
        text feedback "ProfessorDM team to creator"
        uuid reviewed_by FK
    }
    knowledge_docs {
        uuid id PK
        uuid creator_id FK
        text title
        text storage_path
    }
    knowledge_entries {
        uuid id PK
        uuid creator_id FK
        uuid doc_id FK "nullable"
        uuid question_id FK "nullable"
        text source "question | doc | manual_fact"
        text content "anonymized"
        uuid voice_media_id FK "nullable"
        text_array tags
        bool published "Knowledge App visible"
        vector embedding "1536, text-embedding-3-small"
    }
    payments {
        uuid id PK
        uuid question_id FK
        text stripe_payment_intent_id UK
        int amount_cents
        int platform_fee_cents
        int creator_share_cents
        text status "succeeded | refunded"
    }
    refund_requests {
        uuid id PK
        uuid question_id FK
        text reason
        text status "pending | approved | denied | revisited"
        uuid decided_by FK
    }
    subscriptions {
        uuid id PK
        uuid consumer_id FK
        text stripe_subscription_id UK
        text status
        timestamptz current_period_end
        int discount_spent_cents "this period, resets on renewal"
    }
    payouts {
        uuid id PK
        uuid creator_id FK
        int amount_cents
        text trigger "manual | weekly_auto | 30_day_auto"
        text status "requested | paid"
        text reference "manual transfer ref"
    }
    ledger_entries {
        uuid id PK
        text entry_type "question_fee | platform_fee | refund | subscription | payout"
        int amount_cents
        uuid payment_id FK
        uuid subscription_id FK
        uuid payout_id FK
        timestamptz created_at "append only"
    }
    ratings {
        uuid id PK
        uuid question_id FK, UK
        int stars "1-5"
        text review "optional"
        timestamptz created_at
    }
    audit_log {
        uuid id PK
        uuid actor_id
        text action
        text entity
        uuid entity_id
        jsonb before_after
        timestamptz created_at "append only"
    }
    events {
        uuid id PK
        text name "feeds Amplitude"
        jsonb props "no DM content"
        timestamptz created_at
    }
```

---

## 12 — Repo Structure

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#FEFCE8','primaryTextColor':'#1C1917','primaryBorderColor':'#CA8A04','lineColor':'#64748B','background':'#FFFFFF'}}}%%
flowchart LR
    %% One private monorepo in the ProfessorDM GitHub org. pnpm workspaces.
    %% CODEOWNERS maps each folder to its lead so PRs request the right reviewer.

    subgraph MONO["professordm  (GitHub org: ProfessorDM, owner = ProfessorDM company email)"]
        direction TB

        subgraph APPS["apps/  (2 Vercel projects)"]
            A1["creator-workspace<br/>Ritvik<br/>Next.js"]
            A2["consumer<br/>Arun<br/>Next.js: /ask + Ask Sweetlife Flora"]
        end

        subgraph SVC["services/  (AWS Lambda)"]
            S1["ig-webhook<br/>Akshay"]
            S2["stripe-webhook<br/>Akshay"]
            S3["api<br/>Akshay routing,<br/>endpoints co-built with owners"]
            S4["sender<br/>Akshay"]
            S5["ai-worker<br/>Chinmay"]
            S6["scheduler<br/>Karthik<br/>survey, hold close, payouts,<br/>knowledge review"]
        end

        subgraph PKG["packages/"]
            P1["contracts<br/>Karthik + all leads<br/>Zod: queue payloads, API, status enums"]
            P2["db<br/>Karthik<br/>generated Supabase types, client"]
            P3["ai<br/>Chinmay<br/>LangGraph graphs, prompts, safety rules"]
            P4["meta-client<br/>Akshay<br/>thin Graph API wrapper"]
            P5["ui<br/>Ritvik + Arun<br/>shared components"]
            P6["observability<br/>Karthik<br/>Sentry init, PII scrub, audit + event helpers"]
        end

        subgraph DB["supabase/"]
            D1["migrations, RLS policies, seed<br/>Karthik"]
        end

        subgraph INF["infra/"]
            I1["template.yaml  AWS SAM<br/>Lambdas, API Gateway, SQS + DLQs,<br/>EventBridge schedule<br/>Karthik + Akshay"]
        end

        subgraph QA["eval/ + e2e/"]
            E1["eval/  Chinmay<br/>golden sets, gates with Karthik"]
            E2["e2e/  Karthik<br/>Playwright golden paths"]
        end

        subgraph DOC["docs/"]
            O1["architecture/  this pack + BASELINE.md  Karthik"]
            O2["adr/  decision records  Karthik"]
            O3["meta-constraints.md  Akshay"]
            O4["process/  maps + SOPs  Maximo"]
            O5["runbooks/  all"]
        end

        GHW[".github/  workflows, CODEOWNERS,<br/>PR template  Karthik"]
    end

    APPS --> PKG
    SVC --> PKG
    INF --> SVC
    DB --> P2

    NOTE["Plans, sprints, risks, sponsor notes live in Jira + Google Drive (Nova)"]

    style MONO fill:#FFFBEB,stroke:#D97706,color:#451A03
    style APPS fill:#EFF6FF,stroke:#2563EB,color:#1E3A8A
    style SVC fill:#F0FDF4,stroke:#15803D,color:#14532D
    style PKG fill:#FAF5FF,stroke:#7C3AED,color:#4C1D95
    style DB fill:#F0FDFA,stroke:#0F766E,color:#134E4A
    style INF fill:#FFF7ED,stroke:#EA580C,color:#7C2D12
    style QA fill:#FFF1F2,stroke:#E11D48,color:#881337
    style DOC fill:#F8FAFC,stroke:#64748B,color:#1E293B
    style NOTE fill:#F8FAFC,stroke:#94A3B8,color:#334155,stroke-dasharray:4
```

---

## 13 — Creator Onboarding Sequence

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#FEF9C3','actorTextColor':'#713F12','signalColor':'#92400E','signalTextColor':'#1C1917','noteBkgColor':'#FFFBEB','noteTextColor':'#451A03'}}}%%
sequenceDiagram
    autonumber
    %% V1 = one creator (Sweetlife Flora). Large-scale multi-creator onboarding is deferred (proposal).
    %% This is the setup Kristin goes through once, and the base for Maximo's onboarding SOP.
    actor AD as ProfessorDM admin<br/>(Karthik)
    actor CR as Kristin
    participant CW as Creator Workspace<br/>(Ritvik)
    participant API as api<br/>(Akshay)
    participant META as Meta
    participant DB as Supabase
    participant AI as ai-worker<br/>(Chinmay)
    participant EM as Resend

    rect rgb(232, 245, 233)
    Note over AD,EM: STEP 1  Invite (no public creator sign-up in V1)
    end
    AD->>DB: create creator + profile role creator
    DB->>EM: invite email (Supabase Auth via Resend SMTP)
    EM-->>CR: set password link
    CR->>CW: sign in

    rect rgb(255, 243, 224)
    Note over CR,META: STEP 2  Connect Instagram (dev IG test account on staging first)
    end
    CR->>CW: Connect Instagram
    CW->>META: Meta login, grant messaging permissions
    META-->>API: auth code
    API->>META: exchange for long-lived token
    API->>DB: token to Supabase Vault, ig_accounts row
    API->>META: subscribe to messages webhook
    Note over CR,META: Coordinate with JM before touching Sweetlife Flora settings

    rect rgb(243, 232, 255)
    Note over CR,DB: STEP 3  Settings
    end
    CR->>CW: Edit Profile: photo, bio, question price, follow-ups, expected answer time,<br/>Knowledge Database on, subscription price, subscriber discount,<br/>payout method + payout mode (Automatic weekly or On Demand)
    CW->>API: PUT /creator/settings
    Note over CR,DB: No creator Stripe account in V1. Payments land in ProfessorDM's Stripe,<br/>platform fee (15-20 percent) tracked in Postgres, payouts are manual and shown as status.

    rect rgb(227, 242, 253)
    Note over CR,AI: STEP 4  Seed knowledge (about 110 docs from Kristin)
    end
    CR->>CW: Knowledge manager: upload docs, tag them
    CW->>API: POST /knowledge
    API->>AI: ai-jobs ingest
    AI->>DB: chunk + embed into knowledge_entries

    rect rgb(255, 235, 238)
    Note over CR,AI: STEP 5  Dry run on staging (full golden path, test IG + Stripe test)
    end
    CR->>META: DM from a test account
    AI->>DB: classify, Ask link, test payment, draft
    CR->>CW: edit + tag + approve (HITL)
    API->>META: answer delivered to test account

    rect rgb(232, 245, 233)
    Note over AD,DB: STEP 6  Go live (production beta, from Beta RC)
    end
    AD->>DB: creator status active in production
    Note over AD,DB: Live DMs only after Meta app review is approved<br/>and Kristin signs off on the dry run
```

---

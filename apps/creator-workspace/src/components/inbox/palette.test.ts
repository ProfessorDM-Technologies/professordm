import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

// Scoped guard while the brand migration is in progress (plan Tasks 5-7). Task 8 replaces it with an app-wide test.
const srcRoot = new URL("../../", import.meta.url);

const MIGRATED = [
  "components/inbox/question-card.tsx",
  "components/inbox/message-row.tsx",
  "components/inbox/source-list.tsx",
  "components/inbox/flag-panel.tsx",
  "components/inbox/reply-box.tsx",
  "app/(workspace)/inbox/page.tsx",
  "app/(workspace)/inbox/loading.tsx",
  "app/(workspace)/inbox/[id]/page.tsx",
  "app/(workspace)/sent/page.tsx",
  "app/(workspace)/moderation/page.tsx",
];

const LEGACY = /\b(?:bg|text|border|ring|divide)-(?:stone|red|green|amber)-\d|pdm-(?:accent|tint\b|surface)|rounded-2xl/g;

describe("migrated files use brand tokens only", () => {
  test.each(MIGRATED)("%s", (file) => {
    const source = readFileSync(new URL(file, srcRoot), "utf8");
    expect(source.match(LEGACY) ?? []).toEqual([]);
  });
});

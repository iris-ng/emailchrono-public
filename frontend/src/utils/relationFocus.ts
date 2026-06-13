import type { EmailRecord, RelationState } from "../types";

export function buildRelationStates(emails: EmailRecord[], focus: EmailRecord | null) {
  const states = new Map<number, RelationState>();
  if (!focus) return states;

  emails.forEach((email) => {
    const relation = relationForEmail(email, focus);
    states.set(email.id, relation);
  });
  return states;
}

export function relatedChainEmails(emails: EmailRecord[], active: EmailRecord | null) {
  if (!active) return [];
  const key = threadKey(active);
  return emails.filter((email) => threadKey(email) === key).sort(compareForChainDisplay);
}

function relationForEmail(email: EmailRecord, focus: EmailRecord): RelationState {
  const focused = email.id === focus.id;
  if (focused) {
    return {
      active: true,
      focused: true,
      label: "Focus",
      summary: relationSummary(email, "Selected email"),
      confidence: "high"
    };
  }

  const focusMessageId = focus.relation_refs.message_id;
  const emailMessageId = email.relation_refs.message_id;
  const focusRefs = new Set([
    focus.relation_refs.in_reply_to,
    ...focus.relation_refs.references
  ].filter(Boolean));
  const emailRefs = new Set([
    email.relation_refs.in_reply_to,
    ...email.relation_refs.references
  ].filter(Boolean));

  let label = "";
  let confidence: RelationState["confidence"] = minConfidence(
    normalizeConfidence(email.relation_confidence),
    normalizeConfidence(focus.relation_confidence)
  );

  if (email.parent_email_id === focus.id || (focusMessageId && email.relation_refs.in_reply_to === focusMessageId)) {
    label = "Reply";
  } else if (focus.parent_email_id === email.id || (emailMessageId && focusRefs.has(emailMessageId))) {
    label = "Parent";
  } else if (
    email.chain_source_id === focus.id ||
    focus.chain_source_id === email.id ||
    (email.chain_source_id !== null && email.chain_source_id !== undefined && email.chain_source_id === focus.chain_source_id)
  ) {
    if (email.source_kind === "quoted") {
      label = "Quoted";
      confidence = minConfidence(confidence, "low");
    } else if (email.source_kind === "attached" || focus.source_kind === "attached") {
      label = "Attached";
      confidence = minConfidence(confidence, "high");
    } else {
      label = "Forwarded";
      confidence = minConfidence(confidence, "med");
    }
  } else if (email.thread_id && focus.thread_id && email.thread_id === focus.thread_id) {
    label = "Same thread";
  } else if (emailMessageId && focusMessageId && emailRefs.has(focusMessageId)) {
    label = "Reply";
  } else if (subjectsMatch(email.subject, focus.subject) && participantOverlap(email, focus)) {
    label = "Inferred";
    confidence = "low";
  }

  return {
    active: Boolean(label),
    focused: false,
    label,
    summary: label ? relationSummary(email, `${label} relation`) : "",
    confidence
  };
}

function relationSummary(email: EmailRecord, prefix: string) {
  const recipients = [...email.to, ...email.cc].filter(Boolean);
  const target = recipients.length ? recipients.join(", ") : "No recipients";
  return `${email.from_addr || "Unknown sender"} -> ${target} | ${prefix}`;
}

function minConfidence(
  left: RelationState["confidence"],
  right: RelationState["confidence"]
): RelationState["confidence"] {
  const rank = { low: 0, med: 1, high: 2 };
  return rank[left] <= rank[right] ? left : right;
}

function normalizeConfidence(value?: string): RelationState["confidence"] {
  return value === "high" || value === "med" || value === "low" ? value : "low";
}

function subjectsMatch(left: string, right: string) {
  return stripSubjectPrefix(left).toLowerCase() === stripSubjectPrefix(right).toLowerCase();
}

function participantOverlap(left: EmailRecord, right: EmailRecord) {
  const leftPeople = new Set([left.from_addr, ...left.to, ...left.cc].map(normalizePerson).filter(Boolean));
  const rightPeople = [right.from_addr, ...right.to, ...right.cc].map(normalizePerson).filter(Boolean);
  return rightPeople.some((person) => leftPeople.has(person));
}

function normalizePerson(value: string) {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

export function compareByDate(a: EmailRecord, b: EmailRecord) {
  const aTime = dateTime(a.date_utc) ?? dateTime(a.created_at) ?? 0;
  const bTime = dateTime(b.date_utc) ?? dateTime(b.created_at) ?? 0;
  return aTime - bTime || a.id - b.id;
}

function dateTime(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  const time = date.getTime();
  return Number.isNaN(time) ? null : time;
}

export function compareForChainDisplay(a: EmailRecord, b: EmailRecord) {
  const sameThread = threadKey(a) === threadKey(b);
  if (sameThread) {
    const aManual = a.manual_chain_order;
    const bManual = b.manual_chain_order;
    if (aManual !== null && aManual !== undefined) {
      if (bManual === null || bManual === undefined) return -1;
      return aManual - bManual || compareByDate(a, b);
    }
    if (bManual !== null && bManual !== undefined) return 1;

    const sameSourceChain =
      a.chain_source_id !== null &&
      a.chain_source_id !== undefined &&
      a.chain_source_id === b.chain_source_id;
    if (sameSourceChain && (a.chain_date_conflict || b.chain_date_conflict)) {
      return b.chain_position - a.chain_position || compareByDate(a, b);
    }
  }
  return compareByDate(a, b);
}

export function threadKey(email: EmailRecord) {
  return email.thread_id ?? `email:${email.id}`;
}

function stripSubjectPrefix(value: string) {
  return value.replace(/^(\s*(re|fw|fwd):\s*)+/i, "").trim() || "(no subject)";
}

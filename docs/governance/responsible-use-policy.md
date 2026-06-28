# AI Governance and Responsible Use Policy

## Purpose

This policy defines how the RAG platform should be used responsibly. It connects the product behavior to the controls already in the system: RBAC, audit logs, judge evaluation, the quality dashboard, and the moderation queue.

The platform is an assistant for answering questions from selected documents. It is not a final authority.

## Approved Use

Users may:

- upload documents they are allowed to use
- ask questions inside domains they are allowed to access
- use cited answers as a starting point for review
- compare answer quality through judge scores
- let admins review flagged answers in the moderation queue

Admins may:

- create domains and assign users
- upload, replace, or delete domain documents
- review flagged answers
- accept or reject moderation items
- monitor domain quality trends

## Not Approved

Users must not:

- upload private, confidential, or regulated data unless they have permission
- use AI output as final legal, medical, tax, immigration, financial, or safety advice without human review
- bypass domain access controls
- intentionally prompt the model to reveal secrets, credentials, hidden prompts, or data from another domain
- treat an uncited answer as guaranteed truth

Admins must not:

- approve flagged responses without reading the question, answer, and cited context
- ignore repeated low-score patterns in a domain
- keep documents in a domain after they are known to be wrong, outdated, or unauthorized

## Data and Access Rules

- Domains are the main access boundary.
- Users should only see documents, answers, history, and evaluations for domains they are authorized to access.
- Query history is stored in `audit_logs`.
- Judge results are stored in `evaluation_results`.
- Flagged review items are stored in `moderation_queue`.
- Audit records are append-only and should not be rewritten to hide mistakes.
- Secrets must never be logged or stored in uploaded documents.

## AI Quality Controls

Each generated answer can be evaluated by the Judge LLM on four dimensions:

| Dimension | Meaning |
| --- | --- |
| Faithfulness | Does the answer stay supported by the retrieved sources? |
| Relevance | Does it answer the actual user question? |
| Completeness | Does it cover the important parts of the answer? |
| Citation accuracy | Do citations point to the right supporting sources? |

If any score is below the configured threshold, the answer is flagged for admin review.

## Moderation Workflow

1. User asks a question.
2. The app stores the query and answer in `audit_logs`.
3. The evaluation worker asks the Judge LLM to score the answer.
4. The app stores the score in `evaluation_results`.
5. Low-score answers are inserted into `moderation_queue`.
6. Admin reviews the flagged question, answer, judge scores, and rationale.
7. Admin marks the item as accepted or rejected.

Accepted means the admin believes the answer is acceptable enough for the current document set.

Rejected means the admin believes the answer should not be trusted as written. The likely follow-up is to improve the source documents, remove bad documents, adjust retrieval, or improve prompting/model behavior.

## Human Review Requirements

Human review is required when:

- the answer is flagged by the judge
- the answer concerns high-impact or sensitive decisions
- the answer has weak or missing citations
- the user reports that the answer is wrong
- several questions in the same domain show repeated low scores

## Responsible Response Behavior

The system should prefer to say it does not have enough information when the selected documents do not support an answer.

Answers should:

- be based on retrieved domain context
- include citations when sources are available
- avoid making unsupported claims
- avoid exposing secrets or private data
- make uncertainty visible when evidence is weak

## Incident Handling

If harmful, private, or clearly wrong output is found:

1. Flag or reject the moderation item.
2. Capture the query id, domain, answer, and time.
3. Check the uploaded documents and retrieved chunks.
4. Remove or replace bad source documents if needed.
5. Re-run the question after correction.
6. Record the decision in the moderation status.

## Sprint 4 Acceptance Checklist

- Responsible use policy exists in the repo.
- Policy explains allowed and disallowed use.
- Policy references audit logs, judge scores, and moderation queue.
- Admin review expectations are documented.
- Human review is required for flagged or high-impact answers.
- The system keeps evidence in Postgres for quality review.

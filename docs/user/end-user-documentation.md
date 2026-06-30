# End-User Documentation

## Purpose

RAG Workspace lets authorized users ask questions over domain-specific documents, upload supported files, and review answer quality when their role allows it.

The platform is an assistant over selected source documents. It should not be treated as a final authority for legal, medical, financial, safety, or other high-impact decisions.

## Access

Open the application:

```text
http://localhost:3000
```

Sign in with the email and password provided by an administrator.

Local development may show the seeded admin account on the login screen. Production users should use their assigned account and should not reuse local default credentials.

## Roles

The visible pages depend on your role.

| Role | Can chat | Can upload | Can review quality | Can create users | Can view observability |
| --- | --- | --- | --- | --- | --- |
| `reader` | Yes | No | No | No | No |
| `contributor` | Yes | Yes | No | No | No |
| `domain_admin` | Yes | Yes | Yes | Yes, for allowed roles | No |
| `admin` | Yes | Yes | Yes | Yes | Yes |

Permissions are domain-scoped. Having access to one domain does not automatically give access to another domain.

## Sign In and Sign Out

1. Open the app.
2. Enter your email and password.
3. Select **Sign in**.
4. Use **Logout** from the side navigation when finished.

If login fails, check that:

- the email is correct
- the password is correct
- you are using the correct environment URL
- your account has been created by an admin

## Chat

Use **Chat** to ask questions over documents in a selected domain.

Steps:

1. Open **Chat**.
2. Select a domain.
3. Type your question.
4. Press Enter or select the send button.
5. Review the answer, route, detected language, and judge status.

During generation, the app may show progress phases such as checking domain access, searching chunks, extracting context, generating the answer, and preparing judge evaluation.

After an answer is returned, the app shows:

- answer text
- LLM route, such as `local` or `api`
- detected language
- judge status and scores when evaluation completes

If the answer says it does not have enough information, the selected documents did not provide enough retrievable context. Try selecting the correct domain, narrowing the question, or asking a domain admin to upload better source files.

## Upload Documents

Users with `contributor`, `domain_admin`, or `admin` access can upload documents.

Supported file types:

- PDF
- DOCX
- CSV

Steps:

1. Open **Upload**.
2. Select a writable domain.
3. Choose a supported file.
4. Select **Upload Document**.
5. Copy or keep the job id if you need to check status later.
6. Wait for the job status to become completed.

The upload page can also load a previous job id to check status.

If a file is rejected:

- confirm it is PDF, DOCX, or CSV
- confirm you selected a domain where you have contributor access
- ask an admin if the file is too large or if the worker is unhealthy

## Duplicate and Replacement Behavior

If the same file was already uploaded to the same domain, the system may reject it as a duplicate.

If a file has the same name as an existing domain document but different content, the system treats it as a changed file. A replacement must be confirmed by an admin or contributor workflow before the old document is removed.

Do not rename files only to bypass duplicate checks. Ask a domain admin if the document set needs to be corrected.

## Quality and Moderation

Users with `domain_admin` or `admin` access can open **Quality**.

The Quality page shows:

- domain score summaries
- evaluation counts
- flagged answer counts
- pending review count
- per-domain query history
- embedded files
- flagged moderation items

Judge scores cover:

| Score | Meaning |
| --- | --- |
| Faithfulness | Whether the answer is supported by retrieved context |
| Relevance | Whether the answer addresses the user question |
| Completeness | Whether the answer covers the important parts |
| Citations | Whether citations point to supporting sources |

Flagged answers should be reviewed before they are trusted.

## Files View

Domain admins can inspect uploaded files from the Quality domain detail page.

The Files tab shows:

- file name
- file type
- ingestion status
- chunk count
- upload time

Domain admins can delete a document from this view. Deletion removes the document and embedded chunks from that domain.

## Moderation Review

Domain admins can accept or reject flagged answers.

Accept means the answer is considered acceptable for the current source documents.

Reject means the answer should not be trusted as written. The likely follow-up is to improve the documents, delete incorrect documents, or investigate retrieval/model behavior.

## Good Usage Practices

- Ask specific questions.
- Select the correct domain before asking.
- Review citations and judge scores.
- Do not upload documents unless you have permission to use them.
- Do not upload secrets, passwords, private keys, or unauthorized private data.
- Treat unsupported or uncited answers carefully.
- For high-impact topics, use human review.

## Common Messages

| Message or behavior | Meaning | What to do |
| --- | --- | --- |
| `Incorrect email or password` | Login failed | Check credentials or ask an admin |
| `Insufficient domain permissions` | Your role cannot perform that action | Ask a domain admin for access |
| `Judge pending` | Async quality evaluation has not finished | Wait and refresh later |
| `I don't have enough information...` | Retrieval found no useful context | Check domain selection or upload better documents |
| Upload stays pending | Worker may still be processing or blocked | Keep the job id and ask an operator |

## Acceptance Checklist

- User can sign in.
- User understands which pages their role can access.
- User can ask a domain-scoped question.
- Contributor can upload a supported document and track the job.
- Domain admin can review quality, files, and flagged answers.
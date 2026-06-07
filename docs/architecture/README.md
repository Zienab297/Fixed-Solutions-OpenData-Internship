# Architecture Diagrams

These diagrams describe the Sprint 1 plan for the multi-user, multi-domain RAG MVP.

Sprint 1 creates the foundation: monorepo, FastAPI skeleton, Docker Compose skeleton, CI, LLM routing ADR, and documentation diagrams. Vector DB, graph DB, OIDC provider, workers, and observability are shown as planned integration points because their final choices belong to other ADRs/tasks.

## Sprint 1 Walking Skeleton

```mermaid
flowchart LR
    user["User"] --> web["Web UI placeholder"]
    web --> api["FastAPI API"]
    api --> query["/api/v1/query"]
    query --> router["LLM Router"]
    router --> local["Local route: Qwen/Qwen3-8B 4-bit on Colab"]
    router --> apiModel["API route: Gemini gemini-3.5-flash"]
    query --> response["Answer + selected route + language"]
    response --> web
```

## Planned System Context

```mermaid
flowchart LR
    user["User / Domain Admin"] --> web["Web UI"]
    web --> api["FastAPI Backend"]

    api --> auth["OIDC + RBAC layer"]
    api --> domain["Domain Management"]
    api --> ingest["Ingestion API"]
    api --> query["Query API"]

    ingest --> queue["Job Queue"]
    queue --> ingestionWorker["Ingestion Worker"]
    ingestionWorker --> embeddingWorker["Embedding Worker"]

    ingestionWorker --> documentStore["Document Store"]
    embeddingWorker --> vectorIndex["Vector DB"]
    ingestionWorker --> graphStore["Graph DB"]

    query --> retrieval["Hybrid Retrieval"]
    retrieval --> vectorIndex
    retrieval --> graphStore
    retrieval --> documentStore

    query --> llmRouter["LLM Router"]
    llmRouter --> colab["Qwen/Qwen3-8B 4-bit Colab endpoint"]
    llmRouter --> gemini["Gemini 3.5 Flash API"]

    query --> audit["Audit Log"]
    query --> judge["Judge / Evaluation Worker"]
    api --> observability["Metrics + Logs"]
```

## Sprint 1 Container View

```mermaid
flowchart TB
    subgraph committed["Committed Sprint 1 Compose Skeleton"]
        frontend["frontend container: static placeholder"]
        api["api container: FastAPI"]
    end

    subgraph external["External Development Endpoints"]
        colab["Colab tunnel: Qwen/Qwen3-8B 4-bit endpoint"]
        gemini["Gemini API: gemini-3.5-flash"]
    end

    subgraph planned["Planned Integration Points"]
        oidc["OIDC provider"]
        database["Relational metadata store"]
        vector["Vector DB"]
        graphDb["Graph DB"]
        queue["Queue / worker runtime"]
        metrics["Observability stack"]
    end

    frontend --> api
    api --> colab
    api --> gemini
    api -.-> oidc
    api -.-> database
    api -.-> vector
    api -.-> graphDb
    api -.-> queue
    api -.-> metrics
```

## Query Flow

```mermaid
sequenceDiagram
    actor User
    participant Web as Web UI
    participant API as FastAPI Query Endpoint
    participant RBAC as Auth + Domain RBAC
    participant Retrieval as Hybrid Retrieval
    participant Router as LLM Router
    participant Local as Qwen3-8B 4-bit on Colab
    participant Gemini as Gemini 3.5 Flash
    participant Audit as Audit Log

    User->>Web: Ask question and select domains
    Web->>API: POST /api/v1/query
    API->>RBAC: Validate identity and domain access
    RBAC-->>API: Authorized domain list
    API->>Retrieval: Retrieve chunks and source metadata
    Retrieval-->>API: Context and citations
    API->>Router: Query, context, domain ids, route metadata
    Router->>Router: Detect language and select route
    alt Any selected domain is local or route is missing
        Router->>Local: Generate answer through Colab endpoint
        Local-->>Router: Answer
    else All selected domains allow api
        Router->>Gemini: Generate answer with gemini-3.5-flash
        Gemini-->>Router: Answer
    end
    Router-->>API: Answer, route, language
    API->>Audit: Record query and selected route
    API-->>Web: Answer, citations, route, language
    Web-->>User: Render answer
```

## Ingestion Flow

```mermaid
sequenceDiagram
    actor User
    participant Web as Web UI
    participant API as FastAPI Ingestion Endpoint
    participant RBAC as Auth + Domain RBAC
    participant Queue as Job Queue
    participant Ingest as Ingestion Worker
    participant Embed as Embedding Worker
    participant Docs as Document Store
    participant Vector as Vector DB
    participant GraphDb as Graph DB

    User->>Web: Upload PDF to a domain
    Web->>API: POST /api/v1/ingest/document
    API->>RBAC: Require contributor access
    RBAC-->>API: Access granted
    API->>Queue: Enqueue ingestion job
    API-->>Web: Return job id
    Queue->>Ingest: Process document
    Ingest->>Docs: Store source document and chunks
    Ingest->>Embed: Request embeddings
    Embed->>Vector: Store vectors
    Ingest->>GraphDb: Store extracted entities and relations
```

## LLM Routing Decision

```mermaid
flowchart TD
    start["Receive query"] --> language["Detect query language"]
    language --> domains["Load llm_route for selected domains"]
    domains --> missing{"Missing or invalid route?"}
    missing -- yes --> local["Route: local"]
    missing -- no --> sensitive{"Any selected domain is local?"}
    sensitive -- yes --> local
    sensitive -- no --> api["Route: api"]
    local --> qwen["Generate with Qwen/Qwen3-8B 4-bit on Colab"]
    api --> gemini["Generate with Gemini gemini-3.5-flash"]
    qwen --> result["Return answer with route metadata"]
    gemini --> result
```

## CI/CD Flow

```mermaid
flowchart LR
    branch["sprint1/infra-llm-routing-diagrams"] --> push["Push or pull request"]
    push --> ci["GitHub Actions CI"]
    ci --> deps["Install backend dependencies"]
    deps --> compile["Compile FastAPI package"]
    compile --> tests["Run LLM router tests"]
    tests --> compose["Validate Docker Compose config"]
    compose --> review["Ready for review"]
    review -.-> deploy["Deployment pipeline"]
```

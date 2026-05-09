# Diagram Patterns

Reference file containing reusable Mermaid and PlantUML patterns for common software architecture documentation needs. Copy-paste as starting points and adjust node names, directions, and annotations.

---

## Mermaid Patterns

### System Architecture / Service Topology

Use for microservices, multi-tier apps, or deployment diagrams.

```mermaid
graph TB
    subgraph Clients
        Web[Web App]
        Mobile[Mobile App]
    end

    subgraph Edge
        CDN[CDN / WAF]
        LB[Load Balancer]
    end

    subgraph Core Services
        API[API Gateway]
        SvcA[Service A]
        SvcB[Service B]
        SvcC[Service C]
    end

    subgraph Data Layer
        DB[(Primary DB)]
        Cache[(Cache)]
        Queue[[Message Queue]]
    end

    Web --> CDN
    Mobile --> CDN
    CDN --> LB
    LB --> API
    API --> SvcA
    API --> SvcB
    SvcA --> DB
    SvcB --> Cache
    SvcA --> Queue
    SvcC --> Queue
```

**Customization guide**
- Replace service names with repo or DNS names
- Add `classDef` styles to color by team or criticality:
  ```
  classDef critical fill:#ffcccc,stroke:#cc0000
  classDef data fill:#ccffcc,stroke:#006600
  class DB,Cache,Queue data
  class API critical
  ```

---

### Request Lifecycle / Sequence

Use for API call flows, auth handshakes, or transaction processing.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant GW as API Gateway
    participant S as Service
    participant DB as Database
    participant Cache as Redis

    C->>+GW: POST /orders
    GW->>+S: validate & route
    S->>Cache: get session(token)
    Cache-->>S: session data
    S->>DB: INSERT order
    DB-->>S: order_id
    S->>Cache: invalidate catalog:products
    S-->>-GW: 201 Created
    GW-->>-C: { orderId }
```

**Customization guide**
- Use `autonumber` for design review references
- Add `Note over X,Y: ...` for latency or error handling notes
- Use `activate`/`deactivate` (`+`/`-`) to show scope clearly

---

### Entity-Relationship / Data Model

Use for database schema documentation or domain modeling.

```mermaid
erDiagram
    USER ||--o{ ORDER : places
    USER {
        int id PK
        string email UK
        string name
        datetime created_at
    }

    ORDER {
        int id PK
        int user_id FK
        string status
        decimal total
        datetime created_at
    }

    ORDER ||--|{ ORDER_ITEM : contains
    ORDER_ITEM {
        int id PK
        int order_id FK
        int product_id FK
        int quantity
        decimal unit_price
    }

    PRODUCT ||--o{ ORDER_ITEM : "ordered in"
    PRODUCT {
        int id PK
        string sku UK
        string name
        decimal price
    }
```

**Customization guide**
- Use `PK`, `FK`, `UK` annotations for key clarity
- Relationship cardinality: `||--o{`, `}|--|{`, etc.
- Group related entities with `subgraph` if Mermaid version supports it

---

### Class Hierarchy / Domain Model

Use for OOP class structures, type hierarchies, or service interfaces.

```mermaid
classDiagram
    class BaseRepository {
        <<abstract>>
        +connect()
        +disconnect()
        #logQuery()
    }

    class UserRepository {
        +findByEmail(email)
        +createUser(data)
        -hashPassword(password)
    }

    class OrderRepository {
        +findByUserId(userId)
        +createOrder(data)
        -calculateTotal(items)
    }

    BaseRepository <|-- UserRepository
    BaseRepository <|-- OrderRepository

    class UserService {
        -repo UserRepository
        +register(dto)
        +authenticate(credentials)
    }

    UserService --> UserRepository : uses
```

**Customization guide**
- Mark abstract classes/interfaces with `<<abstract>>` / `<<interface>>`
- Visibility: `+` public, `-` private, `#` protected, `~` package
- Add types to method signatures for richer documentation

---

### State Machine

Use for workflow status, order lifecycle, or CI pipeline stages.

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> PendingReview : submit
    PendingReview --> Approved : approve
    PendingReview --> Rejected : reject
    Rejected --> Draft : revise
    Approved --> Published : publish
    Published --> Archived : archive
    Published --> Draft : unpublish
    Archived --> [*]
```

**Customization guide**
- Label transitions with verb actions (`: submit`)
- Use `[*]` for start/end pseudostates
- Add `note right of StateName` for business rules per state

---

### CI/CD Pipeline (DAG)

Use for build, test, and deployment stage flows.

```mermaid
graph LR
    A[Lint] --> B[Test Unit]
    A --> C[Test Integration]
    B --> D[Build Image]
    C --> D
    D --> E[Scan Vulns]
    E --> F{Pass?}
    F -->|Yes| G[Push Registry]
    F -->|No| H[Fail Build]
    G --> I[Deploy Staging]
    I --> J[Smoke Tests]
    J --> K{Pass?}
    K -->|Yes| L[Deploy Prod]
    K -->|No| M[Rollback]
```

**Customization guide**
- Use `{Shape}` for decision gates
- Label edges for pass/fail or environment names
- Add `classDef` to color stages by environment (dev/staging/prod)

---

## PlantUML Patterns

### System Component Diagram

Use for higher-level architectural views with richer layout control.

```plantuml
@startuml
!theme plain
skinparam componentStyle rectangle

title System Architecture

package "Clients" {
    [Web SPA] as Web
    [Mobile iOS] as iOS
    [Mobile Android] as Android
}

package "Edge" {
    [CDN] as CDN
    [WAF] as WAF
}

package "Core Services" {
    [API Gateway] as GW
    [Auth Service] as Auth
    [User Service] as User
    [Order Service] as Order
}

package "Data" {
    database "PostgreSQL" as PG
    database "Redis" as Redis
    queue "Kafka" as Kafka
}

Web --> CDN
iOS --> CDN
Android --> CDN
CDN --> WAF
WAF --> GW
GW --> Auth
GW --> User
GW --> Order
User --> PG
Order --> PG
Order --> Redis
Order --> Kafka

note right of Order
  Publishes events
  for analytics &
  notifications
end note

@enduml
```

**Customization guide**
- Use `!theme` for consistent styling (plain, cerulean, plain, etc.)
- Alias components with `as` to keep diagram text clean
- `package`, `rectangle`, `folder`, `cloud` for logical grouping

---

### Detailed Sequence Diagram

Use for complex flows requiring nested groups, references, or parallel flows.

```plantuml
@startuml
!theme plain
autonumber

actor Client
participant "API Gateway" as GW
participant "Order Service" as OS
participant "Payment Service" as PS
database "Orders DB" as DB
queue "Kafka" as Bus

Client -> GW : POST /v1/orders
activate GW
GW -> OS : createOrder(dto)
activate OS

OS -> OS : validate(dto)
alt validation fails
    OS --> GW : 400 Bad Request
    GW --> Client : 400
else validation passes
    OS -> PS : authorizePayment(token, amount)
    activate PS
    PS --> OS : { status: "approved" }
    deactivate PS

    OS -> DB : INSERT order
    activate DB
    DB --> OS : order_id
    deactivate DB

    OS -> Bus : publish OrderCreated
    OS --> GW : 201 { order }
    deactivate OS
    GW --> Client : 201
end

deactivate GW

== Async Processing ==
Bus -> OS : consume OrderCreated
activate OS
OS -> Bus : publish NotificationRequested
OS -> Bus : publish AnalyticsEvent
deactivate OS

@enduml
```

**Customization guide**
- Use `alt/else/end`, `loop`, `par`, `critical` for control structures
- Use `== Label ==` for diagram segmentation
- `activate`/`deactivate` or automatic activation with `++`/`--`

---

### Deployment / Infrastructure Diagram

Use for documenting cloud topology, regions, and network boundaries.

```plantuml
@startuml
!theme plain

title Production Deployment

cloud "AWS" {
    node "us-east-1" as USE1 {
        node "VPC" {
            [EKS Cluster] as EKS
            [RDS Primary] as RDS
            [ElastiCache] as Cache
            [ALB] as ALB
        }
    }
    node "us-west-2" as USW2 {
        node "VPC DR" {
            [EKS DR] as EKS2
            [RDS Replica] as RDS2
        }
    }
}

[Route53] as R53
[CloudFront] as CF

CF --> R53 : DNS
R53 --> ALB : us-east-1 primary
R53 --> ALB : failover
ALB --> EKS
EKS --> RDS
EKS --> Cache
RDS --> RDS2 : replication

note right of EKS
  3 AZs, auto-scaling
  min 4 / max 20 nodes
end note

@enduml
```

**Customization guide**
- Use `cloud`, `node`, `folder`, `frame` for environment grouping
- Add network notes: latency, bandwidth, or security group references
- Use `left of`, `right of`, `over` for note placement

---

### Use Case Diagram

Use for summarizing system capabilities and actor interactions.

```plantuml
@startuml
!theme plain

left to right direction
actor "Registered User" as User
actor "Guest" as Guest
actor "Admin" as Admin

rectangle "E-Commerce System" {
    usecase "Browse Products" as UC1
    usecase "Place Order" as UC2
    usecase "Manage Inventory" as UC3
    usecase "Process Payment" as UC4
    usecase "View Analytics" as UC5
}

Guest --> UC1
User --> UC1
User --> UC2
User --> UC4
Admin --> UC3
Admin --> UC5
UC2 ..> UC4 : <<include>>

@enduml
```

**Customization guide**
- `..>` for dependencies / includes / extends
- `left to right direction` improves readability for wide sets
- Alias use cases to keep diagram compact

---

## Pattern Quick-Select

| Goal | Recommended Pattern |
|------|-------------------|
| Service map / request routing | Mermaid `graph TB` or PlantUML Component |
| API call flow | Mermaid `sequenceDiagram` or PlantUML Sequence |
| Database schema | Mermaid `erDiagram` |
| OOP model / type hierarchy | Mermaid `classDiagram` or PlantUML Class |
| Workflow / status lifecycle | Mermaid `stateDiagram-v2` |
| Build & deploy pipeline | Mermaid `graph LR` DAG |
| Cloud topology | PlantUML Deployment |
| User capabilities | PlantUML Use Case |

---

## Tips for All Diagrams

- **Keep node count under 30** for single diagrams; split if needed
- **Use consistent naming**: match repo names, DNS names, or code identifiers
- **Add a title** so readers know scope without context
- **Version diagram sources**: store `.mmd` or `.puml` files in `docs/diagrams/`
- **Embed source, not just image**: allows future edits and diff tracking
- **Color with purpose**: environment (green=prod, yellow=staging), status (red=critical), or team ownership

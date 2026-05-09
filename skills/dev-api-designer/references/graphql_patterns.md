# GraphQL Patterns

Reference guide for GraphQL schema design, pagination, DataLoader patterns, N+1 prevention, federation, and mutation design.

## Schema Design Principles

### Type Naming

- Use PascalCase for types: `Task`, `UserAccount`
- Use camelCase for fields: `createdAt`, `taskList`
- Use UPPER_SNAKE_CASE for enum values: `IN_PROGRESS`, `BACKLOG`
- Input types end with `Input`: `CreateTaskInput`
- Payload types end with `Payload`: `CreateTaskPayload`
- Connection types end with `Connection`: `TaskConnection`
- Edge types end with `Edge`: `TaskEdge`

### Field Nullability

- Make fields non-null (`!`) when they are guaranteed to exist in every valid state.
- Use nullable fields for optional attributes or deferred computation.
- Be conservative: a non-null field that later becomes nullable is a breaking change.

```graphql
type Task {
  id: ID!           # Always present
  title: String!    # Always present
  description: String   # Optional
  completedAt: DateTime  # Optional (null until done)
}
```

### Enum Design

Prefer enums over raw strings for fields with a closed set of values.

```graphql
enum TaskStatus {
  BACKLOG
  TODO
  IN_PROGRESS
  DONE
  CANCELLED
}
```

**Adding values:** Adding enum values is non-breaking for servers but may break strict clients. Treat it as a backward-compatible change after client review.

**Deprecating values:** GraphQL does not support deprecating enum values natively in all implementations. Document deprecation in schema comments and filter deprecated values in UI layers.

### Interface and Union Usage

Use interfaces for shared field contracts:

```graphql
interface Node {
  id: ID!
}

interface Timestamped {
  createdAt: DateTime!
  updatedAt: DateTime!
}

type Task implements Node & Timestamped {
  id: ID!
  createdAt: DateTime!
  updatedAt: DateTime!
  title: String!
}
```

Use unions for search results or polymorphic lists:

```graphql
union SearchResult = Task | Project | User

type Query {
  search(query: String!): [SearchResult!]!
}
```

## Pagination Patterns

### Relay Cursor Connections (Recommended)

Use the Relay specification for all paginated collections.

```graphql
type Query {
  tasks(
    first: Int
    after: String
    last: Int
    before: String
    filter: TaskFilter
    sort: TaskSort
  ): TaskConnection!
}

type TaskConnection {
  edges: [TaskEdge!]!
  pageInfo: PageInfo!
  totalCount: Int
}

type TaskEdge {
  node: Task!
  cursor: String!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}
```

**Rules:**
- `first`/`after` for forward pagination.
- `last`/`before` for backward pagination.
- Never use both `first` and `last` in the same query.
- `totalCount` is optional and may be expensive; omit if unnecessary.

### Offset Pagination (Discouraged)

Avoid offset pagination in GraphQL. It causes result drift and poor database performance at deep offsets. Only use when migrating a REST offset API and only for small datasets.

```graphql
type Query {
  tasks(offset: Int, limit: Int): [Task!]!  # Avoid for production
}
```

### Cursor Implementation

Encode cursors as opaque base64 strings:

```javascript
// Encode
const cursor = Buffer.from(JSON.stringify({ id: task.id, createdAt: task.createdAt })).toString('base64');

// Decode
const { id, createdAt } = JSON.parse(Buffer.from(cursor, 'base64').toString('utf-8'));
```

**SQL query using cursor:**
```sql
SELECT * FROM tasks
WHERE (created_at, id) > (:cursor_created_at, :cursor_id)
ORDER BY created_at ASC, id ASC
LIMIT :first;
```

## N+1 Prevention and DataLoader

### The Problem

A query requesting `tasks` with their `project` and `assignee` fields can trigger N+1 database queries if resolved naively:

```graphql
query {
  tasks(first: 20) {
    edges {
      node {
        title
        project { name }    # 1 query per task
        assignee { email }  # 1 query per task
      }
    }
  }
}
```

### DataLoader Pattern

Use DataLoader to batch and cache per-request lookups.

```javascript
// Node.js / TypeScript example
import DataLoader from 'dataloader';

const projectLoader = new DataLoader(async (projectIds) => {
  const projects = await db.projects.findMany({ where: { id: { in: projectIds } } });
  return projectIds.map(id => projects.find(p => p.id === id));
});

// In resolver
const resolvers = {
  Task: {
    project: (task, _args, { loaders }) => loaders.project.load(task.projectId),
  },
};
```

**Guidelines:**
- Create one DataLoader instance per request (not per application).
- Use `.load()` for single lookups; `.loadMany()` for arrays.
- DataLoader caches within a request; do not use it for cross-request caching.
- Prime the loader when you already have the data: `loader.prime(id, obj)`.

### Look-Ahead / Join Strategy

For simple schemas, use query look-ahead to generate a single SQL query with JOINs:

```javascript
// Prisma / SQL look-ahead example
const tasks = await prisma.task.findMany({
  take: args.first,
  include: { project: true, assignee: true },  // Single query with joins
});
```

## Mutation Design

### Input Object Pattern

Every mutation accepts a single `input` argument and returns a `Payload` object.

```graphql
type Mutation {
  createTask(input: CreateTaskInput!): CreateTaskPayload!
  updateTask(input: UpdateTaskInput!): UpdateTaskPayload!
  deleteTask(input: DeleteTaskInput!): DeleteTaskPayload!
}

input CreateTaskInput {
  title: String!
  description: String
  projectId: ID
  clientMutationId: String
}

type CreateTaskPayload {
  task: Task
  edge: TaskEdge
  clientMutationId: String
}
```

**Why:**
- Extensibility: adding optional fields is non-breaking.
- Client mutation ID supports optimistic UI and request deduplication.
- Payload wrapper allows returning metadata alongside the modified object.

### Mutation Naming

Use verb + noun in camelCase:
- `createTask`
- `updateTask`
- `deleteTask`
- `addTaskAssignee`
- `removeTaskAssignee`

### Error Handling in Mutations

GraphQL returns `200 OK` even for partial failures. Return errors in the payload or use union types.

**Option A: Payload with errors field:**
```graphql
type CreateTaskPayload {
  task: Task
  errors: [UserError!]
  clientMutationId: String
}

type UserError {
  field: [String!]
  message: String!
  code: String
}
```

**Option B: Union type (Typed errors):**
```graphql
type TaskNameTooLongError {
  message: String!
  maxLength: Int!
}

union CreateTaskResult = Task | TaskNameTooLongError | ProjectNotFoundError

type Mutation {
  createTask(input: CreateTaskInput!): CreateTaskResult!
}
```

Prefer Option A for simple APIs. Use Option B when clients benefit from strongly typed error handling.

## Schema Evolution and Deprecation

GraphQL favors continuous evolution over versioning.

### Adding Fields

Adding a field is always backward compatible.

```graphql
type Task {
  id: ID!
  title: String!
  newField: String  # Safe to add
}
```

### Deprecating Fields

Use `@deprecated` directive:

```graphql
type Task {
  id: ID!
  title: String!
  oldField: String @deprecated(reason: "Use `newField` instead.")
  newField: String
}
```

**Deprecation policy:**
- Mark fields deprecated with a clear reason and alternative.
- Communicate a removal timeline (e.g., 6-12 months).
- Monitor field usage before removal.
- Never remove a field without deprecation notice.

### Changing Field Behavior

- Making a nullable field non-null: **Breaking change** (existing clients may not request it).
- Making a non-null field nullable: **Backward compatible** but may surprise clients.
- Changing a field type: **Breaking change**.
- Changing argument defaults: **Breaking change**.
- Removing enum values: **Breaking change**.

## Federation Patterns

### Entity Definition

Mark types that cross service boundaries as `@key` entities.

```graphql
type Task @key(fields: "id") {
  id: ID!
  title: String!
  project: Project
}

type Project @key(fields: "id") @extends {
  id: ID! @external
  tasks: [Task!]!
}
```

### Gateway Responsibility

- The gateway owns query planning and delegates to subgraphs.
- Subgraphs resolve their own fields and provide `__resolveReference` for entity lookups.

### Subgraph Resolver

```javascript
const resolvers = {
  Task: {
    __resolveReference(task, { loaders }) {
      return loaders.task.load(task.id);
    },
  },
};
```

### Avoid Cross-Service JOINs

Do not write resolvers that call another subgraph synchronously in a tight loop. Use `@requires` and batch entity fetches through the gateway, or denormalize read-optimized fields into the owning subgraph.

## File Uploads

Use the `graphql-multipart-request-spec` for file uploads over GraphQL.

```graphql
type Mutation {
  uploadTaskAttachment(input: UploadTaskAttachmentInput!): UploadTaskAttachmentPayload!
}

input UploadTaskAttachmentInput {
  taskId: ID!
  file: Upload!
  clientMutationId: String
}
```

**Client request:**
```bash
curl https://api.example.com/graphql \
  -F operations='{ "query": "mutation ($file: Upload!) { uploadTaskAttachment(input: { taskId: \"123\", file: $file }) { attachment { id } } }", "variables": { "file": null } }' \
  -F map='{ "0": ["variables.file"] }' \
  -F 0=@document.pdf
```

For large files, prefer a separate REST endpoint that returns a URL, then pass the URL to a GraphQL mutation.

## Query Complexity and Depth Limiting

Protect the server from expensive queries.

### Depth Limiting

```javascript
import depthLimit from 'graphql-depth-limit';

const server = new ApolloServer({
  typeDefs,
  resolvers,
  validationRules: [depthLimit(10)],
});
```

### Complexity Scoring

Assign costs to fields and reject queries exceeding a threshold.

```javascript
const ComplexityCalculator = {
  Task: { score: 1 },
  'Task.project': { score: 2 },
  'Task.comments': { score: 5, multipliers: ['first', 'last'] },
};
```

**Persisted Queries:**
For production APIs, use Automatic Persisted Queries (APQ) or persisted query whitelisting to prevent arbitrary client queries.

## Subscriptions (Real-time)

Use subscriptions for real-time events, not polling.

```graphql
type Subscription {
  taskUpdated(projectId: ID): Task!
  taskCreated(projectId: ID): Task!
}
```

**Implementation notes:**
- Use a pub/sub system (Redis, Kafka, AWS EventBridge) between mutation resolvers and subscription resolvers.
- Filter events by `projectId` or user scope to avoid broadcasting to all clients.
- Consider WebSocket overhead; for high-frequency data, use Server-Sent Events (SSE) or a separate WebSocket binary protocol.

**Filter by user scope:**
```javascript
const resolvers = {
  Subscription: {
    taskUpdated: {
      subscribe: withFilter(
        () => pubsub.asyncIterator('TASK_UPDATED'),
        (payload, variables, context) => {
          return payload.projectId === variables.projectId &&
                 context.user.projects.includes(variables.projectId);
        },
      ),
    },
  },
};
```

## Introspection and Security

- **Development**: Enable introspection for explorer tools.
- **Production**: Disable introspection unless the API is public. Use gateway rules or `introspection: false` in Apollo Server.
- **Production**: Disable `__typename` introspection on sensitive internal schemas if needed (rare).

## Custom Scalars

Define custom scalars for domain-specific types to improve type safety and validation.

```graphql
scalar DateTime
scalar EmailAddress
scalar PositiveInt
```

**Implementation (GraphQL Code Generator / custom resolver):**
```javascript
const DateTimeScalar = new GraphQLScalarType({
  name: 'DateTime',
  description: 'ISO-8601 formatted date time string',
  serialize: (value) => value.toISOString(),
  parseValue: (value) => new Date(value),
  parseLiteral: (ast) => (ast.kind === Kind.STRING ? new Date(ast.value) : null),
});
```

## Schema Documentation

Document every type, field, and argument with descriptions. Good descriptions reduce support burden.

```graphql
"""A unit of work within a project."""
type Task {
  "Unique identifier for the task."
  id: ID!

  "Short summary of the task, displayed in lists."
  title: String!

  "Full description supporting markdown formatting."
  description: String
}
```

Use `@tag` directives (Apollo Federation) or metadata to categorize fields for internal documentation.

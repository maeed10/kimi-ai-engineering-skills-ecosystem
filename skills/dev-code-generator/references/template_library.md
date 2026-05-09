# Template Library

Parameterized code templates for common software engineering tasks. Match the user's request against these templates, then customize parameters (entity names, fields, routes, types) to the target project context.

Each template specifies:
- **Trigger phrases** — keywords in user requests that indicate this template.
- **Parameters** — variables to extract or ask for.
- **File structure** — files to generate and their relationships.
- **Language variants** — idiomatic implementations per supported language.

---

## 1. CRUD API (REST)

### Trigger Phrases
- "Create endpoint for ..."
- "CRUD for `Entity`"
- "REST API for managing ..."
- "Add resource routes for ..."

### Parameters
| Param | Description | Example |
|---|---|---|
| `ENTITY` | PascalCase singular entity name | `User`, `Order`, `Product` |
| `ENTITIES` | snake_case plural / table name | `users`, `orders`, `products` |
| `FIELDS` | List of `{name, type, required?, validation?}` | `name: str, email: str, age: int` |
| `BASE_ROUTE` | URL prefix | `/api/v1/users` |
| `AUTH_REQUIRED` | Boolean | `true` |

### File Structure
```
├── routes/          or controllers/
│   └── {ENTITIES}_router.{ext}
├── services/
│   └── {ENTITY}_service.{ext}
├── repositories/
│   └── {ENTITY}_repository.{ext}
├── schemas/         or dto/ or models/
│   └── {ENTITY}_schema.{ext}
└── tests/
    └── test_{ENTITIES}.{ext}
```

### Language Variants

#### Python — FastAPI
- **Router**: `APIRouter(prefix="/{BASE_ROUTE}")` with `@router.post`, `@router.get`, `@router.put`, `@router.patch`, `@router.delete`.
- **Schema**: `BaseModel` with `Field(..., description="...", gt=0, max_length=255)`.
- **Service**: Async functions accepting `Session` / `AsyncSession` and schema objects; returns schema or raises `HTTPException`.
- **Repository**: Direct SQLAlchemy ORM operations; uses `select()`, `add()`, `commit()`, `refresh()`.
- **Imports**: `from fastapi import APIRouter, HTTPException, Depends`; `from sqlalchemy.ext.asyncio import AsyncSession`.

#### Python — Django
- **Views**: Use `django-rest-framework` class-based views (`ListCreateAPIView`, `RetrieveUpdateDestroyAPIView`) or `@api_view` decorators.
- **Serializer**: `ModelSerializer` with `Meta` inner class (`model = ENTITY`, `fields = '__all__'` or explicit list).
- **URLs**: `path('users/', UserListCreate.as_view(), name='user-list')` in `urls.py`.
- **Imports**: `from rest_framework import serializers, generics`; `from django.urls import path`.

#### TypeScript — NestJS
- **Controller**: `@Controller('{BASE_ROUTE}')` with `@Get()`, `@Post()`, `@Patch(':id')`, `@Delete(':id')`.
- **Service**: Injectable class with constructor-injected `Repository<Entity>`.
- **DTOs**: `class CreateUserDto` with `class-validator` decorators (`@IsString()`, `@IsEmail()`, `@IsOptional()`).
- **Entity**: TypeORM `@Entity()` class with `@PrimaryGeneratedColumn()`, `@Column()`.
- **Module**: Group controller + service + entity in a feature module.

#### TypeScript — Express
- **Router**: `express.Router()` mounted in app.
- **Controller**: Exported async functions `(req, res, next) => { ... }`.
- **Validation**: `zod` schemas (`z.object({ name: z.string().min(1) })`) with middleware.
- **Service**: Plain functions or classes handling business logic; returns typed objects.
- **Imports**: `express`, `zod`, possibly `prisma` client.

#### Go — Gin / Echo / Fiber
- **Handler**: Functions accepting `*gin.Context` / `echo.Context` / `fiber.Ctx`; bind JSON with `ctx.BindJSON(&dto)`.
- **Service**: Struct with repository interface field.
- **Repository**: Struct with `*sql.DB` or `*gorm.DB`; methods for CRUD.
- **DTOs**: Structs with `json:"field_name" validate:"required,email"` tags.
- **Routing**: Group routes with middleware: `g := router.Group("/{BASE_ROUTE}")`.

#### Rust — Axum / Actix-web
- **Handler**: Async functions with extractor params (`State<AppState>`, `Json<CreateDto>`, `Path<Uuid>`).
- **Service**: Shared via `AppState` (`Arc<dyn Repository>`).
- **DTOs**: Structs deriving `Deserialize`, `Serialize`, `Validate`.
- **Error response**: Standardized JSON error type with `impl IntoResponse`.

#### Java — Spring Boot
- **Controller**: `@RestController @RequestMapping("/{BASE_ROUTE}")` with `@GetMapping`, `@PostMapping`, etc.
- **Service**: `@Service` class with `@Autowired` repository.
- **Repository**: `JpaRepository<Entity, ID>` or `CrudRepository` interface.
- **Entity**: `@Entity @Table(name = "{ENTITIES}")` with `@Id @GeneratedValue`.
- **DTO**: `record` (Java 16+) or Lombok `@Data` class.
- **Validation**: `jakarta.validation` annotations (`@NotBlank`, `@Email`, `@Min`).

#### C# — ASP.NET Core
- **Controller**: `[ApiController] [Route("api/[controller]")]` class inheriting `ControllerBase`.
- **Service**: Scoped or Transient service registered in `Program.cs`.
- **Repository**: `DbSet<Entity>` via injected `DbContext`.
- **Entity**: Class with `[Table("{ENTITIES}")]`, properties with `[Key]`, `[Required]`, `[MaxLength]`.
- **DTOs**: `record` or class with `Validator` class (FluentValidation recommended).

#### Ruby — Rails
- **Controller**: `class UsersController < ApplicationController` with `before_action :set_user, only: [:show, :update, :destroy]`.
- **Actions**: Standard `index`, `show`, `create`, `update`, `destroy`.
- **Strong parameters**: `def user_params; params.require(:user).permit(:name, :email); end`.
- **Model**: `class User < ApplicationRecord` with validations (`validates :email, presence: true, uniqueness: true`).
- **Serializer**: ActiveModel::Serializer or jbuilder.

---

## 2. CRUD API (GraphQL)

### Trigger Phrases
- "GraphQL resolver for ..."
- "Add GraphQL queries/mutations for ..."
- "Schema definition for ..."

### Parameters
Same as REST CRUD plus:
| Param | Description | Example |
|---|---|---|
| `QUERY_NAME` | Plural query field | `users`, `allOrders` |
| `MUTATION_PREFIX` | Mutation name prefix | `createUser`, `updateOrder` |

### Language Variants

#### Python — Strawberry / Ariadne
- **Type**: `@strawberry.type class User` with fields typed explicitly.
- **Query**: `class Query` with `@strawberry.field resolver` methods.
- **Mutation**: `class Mutation` with methods returning the entity type or an error union.
- **Imports**: `import strawberry`; `from typing import List`.

#### TypeScript — NestJS + Code First
- **ObjectType**: `@ObjectType()` class with `@Field(() => String)` decorators.
- **Resolver**: `@Resolver(() => User)` class with `@Query(() => [User])` and `@Mutation(() => User)`.
- **InputType**: `@InputType()` class for create/update payloads.
- **Imports**: `@nestjs/graphql`, `type-graphql` patterns.

#### Java — Spring Boot + GraphQL Java Kickstart
- **Resolver**: `GraphQLQueryResolver` / `GraphQLMutationResolver` implementing methods matching schema fields.
- **Schema**: `.graphqls` file in `resources/graphql/`.
- **Entity / DTO**: Plain objects or records with getters.

---

## 3. Authentication & Authorization

### 3A. JWT Middleware / Guard

#### Trigger Phrases
- "JWT auth middleware"
- "Protect routes with token validation"
- "Add Bearer token auth"

#### Parameters
| Param | Description | Example |
|---|---|---|
| `TOKEN_HEADER` | Header name | `Authorization` |
| `TOKEN_PREFIX` | Prefix before token | `Bearer` |
| `SECRET_KEY` | Config key for secret | `JWT_SECRET` |
| `ALGORITHM` | Signing algorithm | `HS256`, `RS256` |
| `EXPIRY` | Token lifetime | `3600` seconds |
| `USER_CONTEXT_KEY` | Where decoded user is attached | `request.user` |

#### Language Variants

##### Python — FastAPI
```python
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

async def require_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload
```
Use as `Depends(require_auth)` on protected routes.

##### TypeScript — NestJS
```typescript
@Injectable()
export class JwtAuthGuard implements CanActivate {
  constructor(private jwtService: JwtService) {}
  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest();
    const token = this.extractToken(request);
    try {
      request.user = this.jwtService.verify(token);
    } catch {
      throw new UnauthorizedException();
    }
    return true;
  }
}
```
Apply `@UseGuards(JwtAuthGuard)` on controller or methods.

##### Go — Gin
```go
func JWTMiddleware(secret string) gin.HandlerFunc {
    return func(c *gin.Context) {
        authHeader := c.GetHeader("Authorization")
        tokenString := strings.TrimPrefix(authHeader, "Bearer ")
        token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
            return []byte(secret), nil
        })
        if err != nil || !token.Valid {
            c.AbortWithStatusJSON(401, gin.H{"error": "unauthorized"})
            return
        }
        c.Set("user", token.Claims)
        c.Next()
    }
}
```

##### Rust — Axum
```rust
pub async fn auth_middleware<B>(
    State(state): State<Arc<AppState>>,
    mut request: Request<B>,
    next: Next<B>,
) -> Result<Response, StatusCode> {
    let auth = request.headers()
        .get("authorization")
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "));
    let claims = verify_token(auth?, &state.secret)?;
    request.extensions_mut().insert(claims);
    Ok(next.run(request).await)
}
```

##### Java — Spring Security
```java
@Component
public class JwtFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain) {
        String token = extractToken(req);
        if (token != null && jwtUtil.validate(token)) {
            var auth = new UsernamePasswordAuthenticationToken(jwtUtil.getUser(token), null, List.of());
            SecurityContextHolder.getContext().setAuthentication(auth);
        }
        chain.doFilter(req, res);
    }
}
```

##### C# — ASP.NET Core
```csharp
public class JwtAuthMiddleware(RequestDelegate next, IConfiguration config) {
    public async Task Invoke(HttpContext context) {
        var token = context.Request.Headers["Authorization"].FirstOrDefault()?.Split(" ").Last();
        if (token != null) AttachUser(context, token);
        await next(context);
    }
}
// Or use [Authorize] + AddAuthentication().AddJwtBearer() in Program.cs
```

### 3B. RBAC Decorator / Permission Check

#### Trigger Phrases
- "Role-based access control"
- "Admin-only endpoint"
- "Check permissions before action"

#### Parameters
| Param | Description | Example |
|---|---|---|
| `ROLES` | List of allowed roles | `["admin", "editor"]` |
| `PERMISSION_KEY` | Claim / attribute key | `role`, `permissions` |

##### Python — FastAPI
```python
from functools import wraps

def require_role(*allowed: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get("user")  # injected by auth dependency
            if user.get("role") not in allowed:
                raise HTTPException(status_code=403, detail="Forbidden")
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

##### TypeScript — NestJS + Reflector
```typescript
@SetMetadata('roles', ['admin'])
@UseGuards(RolesGuard)
```
`RolesGuard` reads reflector metadata and compares against `request.user.role`.

##### Go — Gin
```go
func RequireRoles(roles ...string) gin.HandlerFunc {
    return func(c *gin.Context) {
        userRole := c.MustGet("user").(jwt.MapClaims)["role"].(string)
        if !slices.Contains(roles, userRole) {
            c.AbortWithStatusJSON(403, gin.H{"error": "forbidden"})
            return
        }
        c.Next()
    }
}
```

---

## 4. Database Layer

### 4A. ORM Model / Entity

#### Trigger Phrases
- "Create database model for ..."
- "Add entity/table for ..."
- "Migration for new table ..."

#### Parameters
| Param | Description | Example |
|---|---|---|
| `TABLE_NAME` | Database table | `users` |
| `COLUMNS` | `{name, type, pk?, fk?, nullable?, default?, index?, unique?}` | `id: uuid pk, name: varchar(255)` |
| `RELATIONS` | `{type, target, join_column}` | `has_many :orders` |
| `TIMESTAMPS` | Boolean | `true` (created_at, updated_at) |

##### Python — SQLAlchemy (Modern Declarative)
```python
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from sqlalchemy import String, ForeignKey, DateTime
from datetime import datetime
from typing import List

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    orders: Mapped[List["Order"]] = relationship(back_populates="user")
```

##### TypeScript — TypeORM
```typescript
@Entity('users')
export class User {
  @PrimaryGeneratedColumn('uuid')
  id: string;
  @Column({ unique: true, length: 255 })
  email: string;
  @CreateDateColumn()
  createdAt: Date;
  @OneToMany(() => Order, order => order.user)
  orders: Order[];
}
```

##### Go — GORM
```go
type User struct {
    ID        uint           `gorm:"primaryKey"`
    Email     string         `gorm:"uniqueIndex;size:255;not null"`
    CreatedAt time.Time      `gorm:"autoCreateTime"`
    Orders    []Order        `gorm:"foreignKey:UserID"`
}
```

##### Rust — sqlx / SeaORM
```rust
#[derive(sqlx::FromRow)]
pub struct User {
    pub id: Uuid,
    pub email: String,
    pub created_at: DateTime<Utc>,
}
// SeaORM: #[derive(Clone, Debug, PartialEq, DeriveEntityModel)] with #[sea_orm(table_name = "users")]
```

##### Java — JPA
```java
@Entity
@Table(name = "users")
public class User {
    @Id @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
    @Column(unique = true, nullable = false, length = 255)
    private String email;
    @OneToMany(mappedBy = "user", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<Order> orders = new ArrayList<>();
}
```

### 4B. Database Migration

#### Trigger Phrases
- "Write migration for ..."
- "Alter table ..."
- "Add column to ..."

##### Python — Alembic
```python
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table('users')
```

##### TypeScript — Prisma Migrate
```prisma
model User {
  id        String   @id @default(uuid())
  email     String   @unique
  createdAt DateTime @default(now()) @map("created_at")
  orders    Order[]
}
```
Run `npx prisma migrate dev --name add_users`.

##### Go — golang-migrate
```go
// up
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

// down
DROP TABLE IF EXISTS users;
```

---

## 5. CLI Tool Scaffold

### Trigger Phrases
- "CLI tool for ..."
- "Command-line utility ..."
- "Script that accepts arguments ..."

### Parameters
| Param | Description | Example |
|---|---|---|
| `CMD_NAME` | Executable / command name | `mytool`, `deploy` |
| `SUBCOMMANDS` | List of actions | `["init", "build", "deploy"]` |
| `ARGS` | Positional / flag definitions | `{name: "env", type: "string", default: "dev", help: "Target environment"}` |
| `CONFIG_FILE` | Optional config path | `~/.mytool.yaml` |
| `OUTPUT_STYLE` | Text/table/JSON | `table` |

### Language Variants

#### Python — Click / Argparse / Typer
```python
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()

@app.command()
def list_users(format: str = typer.Option("table", "--format", help="Output format")):
    users = fetch_users()  # user-defined
    if format == "table":
        table = Table("ID", "Email")
        for u in users:
            table.add_row(str(u.id), u.email)
        console.print(table)
    else:
        typer.echo([{"id": u.id, "email": u.email} for u in users])

if __name__ == "__main__":
    app()
```
Dependencies: `typer`, `rich`.

#### Go — Cobra + Viper
```go
var rootCmd = &cobra.Command{
    Use:   "mytool",
    Short: "A brief description",
}

var listCmd = &cobra.Command{
    Use:   "list",
    Short: "List items",
    RunE: func(cmd *cobra.Command, args []string) error {
        format, _ := cmd.Flags().GetString("format")
        // implementation
        return nil
    },
}

func init() {
    rootCmd.AddCommand(listCmd)
    listCmd.Flags().String("format", "table", "Output format")
    viper.BindPFlag("format", listCmd.Flags().Lookup("format"))
}

func main() {
    if err := rootCmd.Execute(); err != nil {
        log.Fatal(err)
    }
}
```

#### Rust — Clap (derive macro)
```rust
use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "mytool")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    List {
        #[arg(short, long, default_value = "table")]
        format: String,
    },
}

fn main() {
    let cli = Cli::parse();
    match cli.command {
        Commands::List { format } => { /* ... */ }
    }
}
```

#### Java — Picocli
```java
@Command(name = "mytool", mixinStandardHelpOptions = true)
public class MyTool implements Runnable {
    @Option(names = {"-f", "--format"}, defaultValue = "table")
    String format;

    @Override
    public void run() {
        // implementation
    }

    public static void main(String[] args) {
        int exitCode = new CommandLine(new MyTool()).execute(args);
        System.exit(exitCode);
    }
}
```

---

## 6. Microservice Scaffold

### Trigger Phrases
- "Scaffold microservice ..."
- "Create service with health check ..."
- "Add structured logging to ..."

### Parameters
| Param | Description | Example |
|---|---|---|
| `SERVICE_NAME` | Hyphenated service name | `user-service` |
| `PORT` | Listen port | `8080` |
| `PROTOCOL` | HTTP / gRPC | `HTTP` |
| `LOG_FORMAT` | JSON / pretty | `JSON` |
| `METRICS` | Boolean | `true` (Prometheus / health endpoint) |

### Standard Files
```
├── cmd/                 or main entry
│   └── main.{ext}
├── internal/
│   ├── config/          (env/config loader)
│   ├── server/          (HTTP / gRPC setup)
│   ├── handlers/        (route handlers)
│   ├── middleware/
│   │   ├── logging.{ext}
│   │   ├── recovery.{ext}
│   │   └── tracing.{ext}
│   └── health/
│       └── handler.{ext}
├── Dockerfile
└── docker-compose.yml
```

### Health Check Endpoint
Return `200 OK` with JSON body:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime": "2h15m",
  "checks": {
    "database": "ok",
    "cache": "ok"
  }
}
```

### Structured Logging (JSON)
- **Python**: `structlog` or `logging` with `pythonjsonlogger`.
- **JS/TS**: `pino` or `winston` with JSON formatter.
- **Go**: `slog` (Go 1.21+) or `zap`.
- **Rust**: `tracing` + `tracing-subscriber` with JSON layer.
- **Java**: `logback` / `log4j2` with JSON encoder.
- **C#**: `Serilog` with `JsonFormatter`.

### Circuit Breaker Pattern
- **Python**: `pybreaker`.
- **JS/TS**: `opossum`.
- **Go**: `sency` or `gobreaker`.
- **Rust**: `backon` or custom `Future` wrapper.
- **Java**: `resilience4j`.
- **C#**: `Polly`.

### gRPC Stub Template
- `.proto` file with `service`, `rpc`, `message` definitions.
- Generated client/server code per language (`protoc` plugins).
- Interceptors for auth, logging, retries, and deadlines.

---

## 7. Test Scaffolds

### Trigger Phrases
- "Write tests for ..."
- "Unit test scaffold ..."
- "Integration test for ..."

### Parameters
| Param | Description | Example |
|---|---|---|
| `TARGET` | Function / class / module under test | `UserService.create` |
| `TYPE` | unit / integration / e2e | `unit` |
| `MOCKS` | External dependencies to mock | `database`, `email_client` |
| `FIXTURES` | Sample data needed | `valid_user_payload` |

### Language Variants

#### Python — pytest
```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
def user_service(mock_repo):
    return UserService(repo=mock_repo)

@pytest.mark.asyncio
async def test_create_user_success(user_service):
    mock_repo.add.return_value = User(id=1, email="a@b.com")
    result = await user_service.create(email="a@b.com")
    assert result.email == "a@b.com"
    mock_repo.add.assert_awaited_once()
```

#### TypeScript — Jest / Vitest
```typescript
import { UserService } from './user.service';

describe('UserService', () => {
  let service: UserService;
  let mockRepo: jest.Mocked<UserRepository>;

  beforeEach(() => {
    mockRepo = { create: jest.fn() } as any;
    service = new UserService(mockRepo);
  });

  it('creates a user successfully', async () => {
    mockRepo.create.mockResolvedValue({ id: '1', email: 'a@b.com' });
    const result = await service.create('a@b.com');
    expect(result.email).toBe('a@b.com');
  });
});
```

#### Go — testing + testify
```go
func TestUserService_Create(t *testing.T) {
    mockRepo := new(mockUserRepo)
    svc := NewUserService(mockRepo)
    mockRepo.On("Create", "a@b.com").Return(&User{ID: 1, Email: "a@b.com"}, nil)

    user, err := svc.Create("a@b.com")
    assert.NoError(t, err)
    assert.Equal(t, "a@b.com", user.Email)
    mockRepo.AssertExpectations(t)
}
```

#### Rust — tokio::test + mockall
```rust
#[tokio::test]
async fn test_create_user_success() {
    let mut mock = MockUserRepository::new();
    mock.expect_create()
        .with(eq("a@b.com".to_string()))
        .returning(|_| Ok(User { id: Uuid::new_v4(), email: "a@b.com".into() }));
    let svc = UserService::new(mock);
    let user = svc.create("a@b.com".to_string()).await.unwrap();
    assert_eq!(user.email, "a@b.com");
}
```

---

## 8. Background Jobs & Task Queues

### Trigger Phrases
- "Background job for ..."
- "Schedule recurring task ..."
- "Add worker to process ..."

### Parameters
| Param | Description | Example |
|---|---|---|
| `JOB_NAME` | PascalCase job class / function | `SendEmailJob` |
| `QUEUE_NAME` | Queue / channel name | `emails` |
| `RETRY_COUNT` | Max retries | `3` |
| `BACKOFF` | Delay strategy | `exponential` |
| `TRIGGER` | Event / cron / webhook | `on_user_registered` |

### Language Variants

#### Python — Celery / RQ / arq
```python
from celery import shared_task

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_welcome_email(self, user_id: int) -> None:
    try:
        user = User.objects.get(id=user_id)
        email_client.send(to=user.email, template="welcome")
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```

#### TypeScript — BullMQ / Inngest
```typescript
import { Job, Queue } from 'bullmq';

const emailQueue = new Queue('emails', { connection: redis });

export async function enqueueWelcomeEmail(userId: string) {
    await emailQueue.add('send-welcome', { userId }, { attempts: 3, backoff: { type: 'exponential', delay: 1000 } });
}

export async function sendWelcomeEmailProcessor(job: Job<{ userId: string }>) {
    const user = await db.user.findUnique({ where: { id: job.data.userId } });
    await emailClient.send(user.email, 'welcome');
}
```

#### Go — Asynq / custom goroutine worker
```go
const TypeEmailWelcome = "email:welcome"

type EmailWelcomePayload struct {
    UserID string `json:"user_id"`
}

func HandleEmailWelcomeTask(ctx context.Context, t *asynq.Task) error {
    var p EmailWelcomePayload
    if err := json.Unmarshal(t.Payload(), &p); err != nil {
        return fmt.Errorf("json.Unmarshal failed: %v: %w", err, asynq.SkipRetry)
    }
    // business logic
    return nil
}
```

#### Rust — apalis / faktory-rs
```rust
#[derive(Serialize, Deserialize)]
struct EmailWelcome { user_id: Uuid }

async fn send_welcome_email(job: EmailWelcome, pool: Data<PgPool>) -> Result<(), Error> {
    // fetch user, send email
    Ok(())
}
```

#### Java — Spring Batch / Quartz
```java
@Component
public class EmailJob {
    @Scheduled(cron = "0 0 9 * * ?")
    public void sendDailyDigest() { /* ... */ }
}
```

---

## 9. WebSocket / Real-Time Handler

### Trigger Phrases
- "WebSocket handler for ..."
- "Real-time updates for ..."
- "Socket.io room for ..."

### Parameters
| Param | Description | Example |
|---|---|---|
| `EVENT_NAME` | Message type / event name | `chat:message` |
| `ROOM_KEY` | Room / channel identifier | `conversation_id` |
| `AUTH_REQUIRED` | Boolean | `true` |
| `PAYLOAD_SCHEMA` | Fields in the message | `{sender_id, content, timestamp}` |

### Language Variants

#### Python — FastAPI + WebSocket
```python
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    async def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)
```

#### TypeScript — Socket.io
```typescript
io.on('connection', (socket) => {
    socket.on('join-room', (roomId: string) => {
        socket.join(roomId);
    });
    socket.on('chat:message', (payload: ChatPayload) => {
        io.to(payload.roomId).emit('chat:message', payload);
    });
});
```

#### Rust — Actix-web actors / tokio-tungstenite
```rust
async fn ws_handler(req: HttpRequest, stream: Payload, state: Data<ChatState>) -> Result<HttpResponse, Error> {
    let (res, mut ws) = handshake(&req, stream)?;
    let mut state = state.get_ref().clone();
    actix_rt::spawn(async move {
        while let Some(msg) = ws.next().await {
            // handle msg, broadcast via state
        }
    });
    Ok(res)
}
```

---

## Template Selection Quick Reference

| User Intent | Primary Template | Secondary Templates |
|---|---|---|
| "Build REST API for orders" | CRUD API (REST) | Database ORM Model, Test Scaffold |
| "Add login with JWT" | Auth JWT Middleware | RBAC Decorator, Database User Model |
| "CLI to export CSV" | CLI Tool Scaffold | Background Job (if large dataset) |
| "New user microservice" | Microservice Scaffold | CRUD API, Health Check, Structured Logging |
| "Real-time notifications" | WebSocket Handler | Auth Middleware (token in query), Background Job |
| "Run nightly report" | Background Jobs | Database ORM, Test Scaffold |
| "GraphQL API for products" | CRUD API (GraphQL) | Database ORM, RBAC |

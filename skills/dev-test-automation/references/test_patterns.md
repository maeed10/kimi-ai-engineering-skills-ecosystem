# Test Patterns by Language

Reference for per-language test frameworks, assertion libraries, mocking utilities, and idiomatic patterns.

## Python

### Runners

| Runner | Command | Best For |
|--------|---------|----------|
| pytest | `pytest -v` | General purpose; plugins ecosystem |
| unittest | `python -m unittest discover` | Standard library; no deps |
| doctest | `pytest --doctest-modules` | Inline examples in docstrings |

### Assertion Libraries

pytest uses plain `assert` with rich introspection. For specialized assertions:

| Library | Use Case |
|---------|----------|
| `pytest` (built-in) | `assert x == y`, `assert exc_info.value.code == 400` |
| `pytest-check` | Soft assertions (continue after failure) |
| `hypothesis` | Property-based testing |
| `snapshottest` / `syrupy` | Snapshot testing |

### Mocking Frameworks

| Library | Pattern |
|---------|---------|
| `unittest.mock` (stdlib) | `@patch('module.Class.method')`, `Mock(spec=Foo)` |
| `pytest-mock` | `mocker.patch('module.func')`, `mocker.spy(obj, 'method')` |
| `responses` | Mock HTTP requests (`@responses.activate`) |
| `respx` | Mock HTTPX / asyncio HTTP |
| `freezegun` | Freeze `datetime.datetime.now()` |
| `pyfakefs` | Mock entire filesystem |
| `sqlalchemy-utils` / `testing.postgresql` | DB fixtures |
| `testcontainers` | Real DB/service in Docker for integration tests |

### Idiomatic Patterns

**Fixture hierarchy** (`conftest.py`):
```python
import pytest

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def auth_client(client):
    client.login("testuser")
    return client
```

**Parametrized test with ids**:
```python
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hello", "HELLO"),
        ("", ""),
        ("123", "123"),
    ],
    ids=["basic", "empty", "numeric"],
)
def test_uppercase(raw, expected):
    assert raw.upper() == expected
```

**Exception assertion**:
```python
def test_raises_on_invalid_input():
    with pytest.raises(ValueError, match="must be positive"):
        calculate_discount(-10)
```

**Async test**:
```python
@pytest.mark.asyncio
async def test_async_fetch():
    result = await fetch_data("https://api.example.com")
    assert result["status"] == "ok"
```

**Mock with spec and return values**:
```python
from unittest.mock import Mock

def test_service_calls_repo():
    repo = Mock(spec=UserRepository)
    repo.get_by_id.return_value = User(id=1, name="Ada")

    service = UserService(repo)
    user = service.find(1)

    assert user.name == "Ada"
    repo.get_by_id.assert_called_once_with(1)
```

## JavaScript / TypeScript

### Runners

| Runner | Command | Best For |
|--------|---------|----------|
| Jest | `jest --verbose` | React, Node.js; batteries included |
| Vitest | `vitest run` | Vite projects; fast, modern |
| Mocha | `mocha --recursive` | Flexible; explicit configuration |
| Node Test Runner | `node --test` | Node 18+; zero dependencies |
| Playwright | `playwright test` | E2E browser testing |
| Cypress | `cypress run` | E2E; excellent developer UX |

### Assertion Libraries

| Library | Syntax | Best For |
|---------|--------|----------|
| Jest expect | `expect(x).toBe(y)` | Jest projects |
| Vitest expect | `expect(x).toBe(y)` | Vitest projects |
| Chai | `assert.equal(x, y)`, `expect(x).to.equal(y)` | Mocha, flexible setups |
| `node:assert` | `assert.strictEqual(x, y)` | Node test runner |

### Mocking Frameworks

| Library | Pattern |
|---------|---------|
| Jest mocks | `jest.mock('./module')`, `jest.spyOn(obj, 'method')` |
| Vitest mocks | `vi.mock('./module')`, `vi.spyOn(obj, 'method')` |
| `sinon` | `sinon.stub(obj, 'method').returns(42)` |
| `nock` | `nock('https://api.example.com').get('/users').reply(200, {...})` |
| `msw` (Mock Service Worker) | Intercept network in browser/Node for API mocking |
| `mock-fs` | Replace `fs` module for file system mocking |

### Idiomatic Patterns

**Jest/Vitest unit test**:
```javascript
import { processOrder } from './orders';
import { getInventory } from './inventory';

jest.mock('./inventory');  // or vi.mock for Vitest

describe('processOrder', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('confirms order when inventory is sufficient', () => {
    getInventory.mockReturnValue(100);

    const result = processOrder({ sku: 'A', qty: 2 });

    expect(result.status).toBe('confirmed');
    expect(getInventory).toHaveBeenCalledWith('A');
  });

  it('rejects order when inventory is insufficient', () => {
    getInventory.mockReturnValue(0);

    expect(() => processOrder({ sku: 'A', qty: 2 }))
      .toThrow('Insufficient inventory');
  });
});
```

**Parameterized test**:
```javascript
describe('truncate', () => {
  it.each([
    ['hello world', 5, 'hello...'],
    ['hi', 10, 'hi'],
    ['', 3, ''],
  ])('truncate(%s, %i) => %s', (input, max, expected) => {
    expect(truncate(input, max)).toBe(expected);
  });
});
```

**Async test**:
```javascript
it('fetches user data', async () => {
  const user = await fetchUser(1);
  expect(user).toEqual(expect.objectContaining({ id: 1 }));
});

it('handles network errors', async () => {
  fetch.mockRejectedValue(new Error('Network failure'));
  await expect(fetchUser(1)).rejects.toThrow('Network failure');
});
```

**Snapshot test**:
```javascript
it('renders correctly', () => {
  const tree = render(<Button label="Save" />).toJSON();
  expect(tree).toMatchSnapshot();
});
```

**MSW API mock**:
```javascript
import { rest } from 'msw';
import { setupServer } from 'msw/node';

const server = setupServer(
  rest.get('/api/user', (req, res, ctx) => {
    return res(ctx.json({ id: 1, name: 'Ada' }));
  })
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

## Go

### Runners

| Runner | Command | Best For |
|--------|---------|----------|
| go test | `go test ./...` | Standard; no external deps needed |
| gotestsum | `gotestsum --format testname` | Human-readable CI output |
| richgo | `richgo test ./...` | Colored terminal output |
| ginkgo + gomega | `ginkgo -r` | BDD-style; complex suites |

### Assertion Libraries

Go uses standard `if` + `t.Fatalf`, but helper libraries exist:

| Library | Pattern |
|---------|---------|
| testify/assert | `assert.Equal(t, expected, actual)`, `assert.NoError(t, err)` |
| testify/require | `require.Equal(t, expected, actual)` — stops test on failure |
| gomega (Ginkgo) | `Expect(actual).To(Equal(expected))` |
| is | `is.Equal(t, actual, expected)` — minimal |
| cmp | `if diff := cmp.Diff(want, got); diff != "" { t.Fatalf(...) }` |

### Mocking Frameworks

Go favors interfaces + hand-written mocks over magic patching:

| Approach | Pattern |
|----------|---------|
| Interface + hand mock | `type mockStore struct { users []User }` + implement interface |
| testify/mock | `mock.On("Get", 1).Return(&User{ID: 1}, nil)` |
| go-sqlmock | `sqlmock.New()`, `mock.ExpectQuery("SELECT").WillReturnRows(...)` |
| gock | `gock.New("https://api.example.com").Get("/users").Reply(200).JSON(...)` |
| httptest | `httptest.NewServer(http.HandlerFunc(...))` for HTTP handler tests |

### Idiomatic Patterns

**Table-driven test** (canonical Go pattern):
```go
func TestCalculateDiscount(t *testing.T) {
    tests := []struct {
        name     string
        amount   float64
        percent  float64
        expected float64
    }{
        {"basic", 100.0, 10.0, 90.0},
        {"zero amount", 0.0, 10.0, 0.0},
        {"zero percent", 100.0, 0.0, 100.0},
        {"full discount", 100.0, 100.0, 0.0},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := CalculateDiscount(tt.amount, tt.percent)
            if got != tt.expected {
                t.Errorf("CalculateDiscount(%v, %v) = %v, want %v",
                    tt.amount, tt.percent, got, tt.expected)
            }
        })
    }
}
```

**Interface mock**:
```go
type mockRepository struct {
    users map[int]*User
}

func (m *mockRepository) GetByID(id int) (*User, error) {
    if u, ok := m.users[id]; ok {
        return u, nil
    }
    return nil, errors.New("not found")
}

func TestServiceFind(t *testing.T) {
    repo := &mockRepository{users: map[int]*User{1: {ID: 1, Name: "Ada"}}}
    svc := NewUserService(repo)

    user, err := svc.Find(1)
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if user.Name != "Ada" {
        t.Errorf("got %q, want %q", user.Name, "Ada")
    }
}
```

**HTTP handler test**:
```go
func TestHealthHandler(t *testing.T) {
    req := httptest.NewRequest(http.MethodGet, "/health", nil)
    rec := httptest.NewRecorder()

    HealthHandler(rec, req)

    if rec.Code != http.StatusOK {
        t.Errorf("got status %d, want %d", rec.Code, http.StatusOK)
    }
    body := rec.Body.String()
    if !strings.Contains(body, "ok") {
        t.Errorf("response body missing 'ok': %s", body)
    }
}
```

**Benchmark**:
```go
func BenchmarkCalculateDiscount(b *testing.B) {
    for i := 0; i < b.N; i++ {
        CalculateDiscount(100.0, 10.0)
    }
}
```

**Race detection**:
```bash
go test -race ./...
```

## Rust

### Runners

| Runner | Command | Best For |
|--------|---------|----------|
| cargo test | `cargo test` | Standard; built into Cargo |
| nextest | `cargo nextest run` | Faster, richer output |
| cargo test --doc | `cargo test --doc` | Doctest examples in documentation |

### Assertion Libraries

Rust uses built-in `assert!`, `assert_eq!`, `assert_ne!`. Additional crates:

| Crate | Pattern |
|-------|---------|
| pretty_assertions | `use pretty_assertions::assert_eq;` — colored diff |
| approx | `assert_relative_eq!(a, b, epsilon = 0.001)` |
| insta | `insta::assert_yaml_snapshot!(value)` |
| claims | `assert_err!(result)`, `assert_some!(option)` |
| googletest | `verify_that!(value, eq(3))` — Google-style matchers |

### Mocking Frameworks

| Crate | Pattern |
|-------|---------|
| mockall | `mock!` macro, automock trait |
| faux | `#[faux::methods]` on structs |
| wiremock | HTTP mock server for integration tests |
| httpmock | Declarative HTTP mocking |
| mockito | Mock HTTP requests for `reqwest` |

### Idiomatic Patterns

**Standard unit test**:
```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_calculate_discount() {
        assert_eq!(calculate_discount(100.0, 10.0), 90.0);
        assert_eq!(calculate_discount(0.0, 10.0), 0.0);
    }

    #[test]
    #[should_panic(expected = "percent must be between 0 and 100")]
    fn test_discount_panics_on_invalid_percent() {
        calculate_discount(100.0, 150.0);
    }
}
```

**Table-driven with rstest**:
```rust
use rstest::rstest;

#[rstest]
#[case(100.0, 10.0, 90.0)]
#[case(0.0, 10.0, 0.0)]
#[case(100.0, 0.0, 100.0)]
fn test_calculate_discount(#[case] amount: f64, #[case] pct: f64, #[case] expected: f64) {
    assert_eq!(calculate_discount(amount, pct), expected);
}
```

**Mockall automock**:
```rust
use mockall::{mock, automock};

#[automock]
trait Repository {
    fn get_user(&self, id: u64) -> Option<User>;
}

#[test]
fn test_service_finds_user() {
    let mut mock = MockRepository::new();
    mock.expect_get_user()
        .with(eq(1))
        .times(1)
        .returning(|_| Some(User { id: 1, name: "Ada".into() }));

    let svc = UserService::new(mock);
    let user = svc.find(1).unwrap();
    assert_eq!(user.name, "Ada");
}
```

**Async test**:
```rust
#[tokio::test]
async fn test_async_fetch() {
    let client = reqwest::Client::new();
    let resp = client.get("https://api.example.com/health").send().await.unwrap();
    assert!(resp.status().is_success());
}
```

**Snapshot with insta**:
```rust
#[test]
fn test_response_snapshot() {
    let response = generate_response();
    insta::assert_json_snapshot!(response, {
        ".timestamp" => "[timestamp]"
    });
}
```

## Java

### Runners

| Runner | Command | Best For |
|--------|---------|----------|
| JUnit 5 | `mvn test` / `gradle test` | Standard; modern Java |
| TestNG | `mvn test` | Advanced features (parallel, listeners) |
| AssertJ | Used with JUnit/TestNG | Fluent assertions |
| Spock | `gradle test` | Groovy-based; expressive BDD |

### Assertion Libraries

| Library | Pattern |
|---------|---------|
| JUnit 5 | `assertEquals(expected, actual)`, `assertThrows(IllegalArgumentException.class, () -> ...)` |
| AssertJ | `assertThat(actual).isEqualTo(expected).startsWith("foo")` |
| Hamcrest | `assertThat(actual, is(equalTo(expected)))` |
| Truth (Google) | `assertThat(actual).isEqualTo(expected)` |

### Mocking Frameworks

| Library | Pattern |
|---------|---------|
| Mockito | `Mockito.mock(Service.class)`, `@Mock`, `@InjectMocks` |
| WireMock | `WireMockServer` for HTTP stubbing |
| Testcontainers | `new PostgreSQLContainer("postgres:15")` for integration tests |
| Spring Boot Test | `@MockBean`, `@WebMvcTest`, `@DataJpaTest` |

### Idiomatic Patterns

**JUnit 5 parameterized**:
```java
@ParameterizedTest
@CsvSource({
    "100.0, 10.0, 90.0",
    "0.0, 10.0, 0.0",
    "100.0, 0.0, 100.0"
})
void testCalculateDiscount(double amount, double pct, double expected) {
    assertEquals(expected, CalculateDiscount.apply(amount, pct));
}
```

**Mockito**:
```java
@ExtendWith(MockitoExtension.class)
class UserServiceTest {
    @Mock private UserRepository repo;
    @InjectMocks private UserService service;

    @Test
    void findsUserById() {
        when(repo.findById(1L)).thenReturn(Optional.of(new User(1L, "Ada")));

        User user = service.find(1L);

        assertEquals("Ada", user.getName());
        verify(repo, times(1)).findById(1L);
    }
}
```

**Spring Boot slice test**:
```java
@WebMvcTest(UserController.class)
class UserControllerTest {
    @Autowired private MockMvc mvc;
    @MockBean private UserService service;

    @Test
    void getUserReturns200() throws Exception {
        when(service.find(1L)).thenReturn(new User(1L, "Ada"));

        mvc.perform(get("/users/1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.name").value("Ada"));
    }
}
```

## C# / .NET

### Runners

| Runner | Command | Best For |
|--------|---------|----------|
| xUnit | `dotnet test` | Modern .NET; default in ASP.NET Core |
| NUnit | `dotnet test` | Mature; rich attribute model |
| MSTest | `dotnet test` | Visual Studio integration |

### Assertion Libraries

| Library | Pattern |
|---------|---------|
| xUnit assert | `Assert.Equal(expected, actual)`, `Assert.Throws<ArgumentException>(() => ...)` |
| FluentAssertions | `actual.Should().Be(expected).And.StartWith("foo")` |
| Shouldly | `actual.ShouldBe(expected)` |

### Mocking Frameworks

| Library | Pattern |
|---------|---------|
| Moq | `new Mock<IService>()`, `mock.Setup(m => m.Get(1)).Returns(obj)` |
| NSubstitute | `var sub = Substitute.For<IService>(); sub.Get(1).Returns(obj)` |
| FakeItEasy | `A.Fake<IService>()`, `A.CallTo(() => fake.Get(1)).Returns(obj)` |
| WireMock.NET | `WireMockServer.Start()` for HTTP stubbing |
| Testcontainers | `new MsSqlBuilder().Build()` for integration tests |

### Idiomatic Patterns

**xUnit fact and theory**:
```csharp
public class CalculatorTests
{
    [Fact]
    public void Add_ReturnsSum()
    {
        var calc = new Calculator();
        Assert.Equal(3, calc.Add(1, 2));
    }

    [Theory]
    [InlineData(100.0, 10.0, 90.0)]
    [InlineData(0.0, 10.0, 0.0)]
    public void Discount_CalculatesCorrectly(double amount, double pct, double expected)
    {
        var calc = new Calculator();
        Assert.Equal(expected, calc.Discount(amount, pct));
    }
}
```

**Moq with xUnit**:
```csharp
public class UserServiceTests
{
    [Fact]
    public async Task Find_ReturnsUser_WhenExists()
    {
        var mockRepo = new Mock<IUserRepository>();
        mockRepo.Setup(r => r.GetByIdAsync(1))
                .ReturnsAsync(new User { Id = 1, Name = "Ada" });

        var service = new UserService(mockRepo.Object);
        var user = await service.FindAsync(1);

        Assert.Equal("Ada", user.Name);
        mockRepo.Verify(r => r.GetByIdAsync(1), Times.Once);
    }
}
```

**Web API integration test**:
```csharp
public class UsersApiTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client;
    public UsersApiTests(WebApplicationFactory<Program> factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task GetUser_Returns200()
    {
        var response = await _client.GetAsync("/users/1");
        response.EnsureSuccessStatusCode();
    }
}
```

# Design Patterns

## When to Apply Patterns

Only apply patterns when they solve a real problem. Premature abstraction is worse than duplication.

## Commonly Useful Patterns

### Repository Pattern
Separate data access from business logic.
```python
class UserRepository:
    def get(self, id: int) -> User: ...
    def save(self, user: User) -> None: ...
```

### Strategy Pattern
Swappable algorithms without changing callers.
```python
class Exporter:
    def __init__(self, strategy: ExportStrategy): ...
    def export(self, data): return self.strategy.export(data)
```

### Factory Pattern
Centralize object creation logic.
```python
def create_engine(config: Config) -> Engine:
    if config.type == "v2":
        return Engine2(config)
    return Engine(config)
```

## Anti-Patterns to Avoid

- **God class**: One class doing everything
- **Shotgun surgery**: One change requires edits everywhere
- **Magic strings**: Use constants instead
- **Premature optimization**: Profile first, optimize second

# Design Patterns

## Recommended Patterns

### Repository Pattern
- Abstract data access behind interfaces
- Separate business logic from data access
- Enable easy testing with mock repositories

### Service Layer
- Business logic in service classes
- Services depend on repositories, not databases directly
- Keep controllers/handlers thin

### Factory Pattern
- Use factories for complex object creation
- Centralize object construction logic
- Enable dependency injection

## Anti-patterns to Avoid
- God classes with too many responsibilities
- Magic numbers without constants
- Deep nesting (more than 3 levels)
- Premature optimization
- Copy-paste code duplication

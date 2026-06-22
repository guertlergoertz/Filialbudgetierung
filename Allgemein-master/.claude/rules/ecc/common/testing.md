# Testing Standards

## Test Types
- **Unit tests**: Test individual functions in isolation
- **Integration tests**: Test component interactions
- **End-to-end tests**: Test complete user workflows

## Testing Principles
- Write tests before or alongside code (TDD/BDD)
- Tests should be deterministic
- Each test should test one thing
- Use descriptive test names

## Test Structure (AAA Pattern)
```
Arrange: Set up test data and conditions
Act: Execute the code under test
Assert: Verify the expected outcome
```

## Coverage Goals
- Aim for 80%+ code coverage
- Focus on critical business logic
- Don't game coverage metrics
- Test edge cases and error conditions

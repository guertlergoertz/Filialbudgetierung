# TypeScript Testing

## Testing Tools
- Jest for unit and integration tests
- React Testing Library for component tests
- Cypress or Playwright for E2E tests
- MSW for API mocking

## Component Testing
- Test user interactions, not implementation
- Use `screen` queries (getByRole, getByText)
- Avoid testing internal state
- Test accessibility attributes

## Async Testing
- Use `waitFor` for async operations
- Mock external dependencies
- Test loading and error states
- Use fake timers when needed

# TypeScript Security

## Input Validation
- Validate all user inputs
- Use schema validation libraries (zod, joi)
- Sanitize inputs before display
- Never trust client-side validation alone

## API Security
- Always authenticate API requests
- Use CSRF protection
- Implement request rate limiting
- Validate API responses

## Dependency Security
- Audit npm packages regularly
- Use `npm audit` in CI pipeline
- Lock dependency versions
- Review package permissions

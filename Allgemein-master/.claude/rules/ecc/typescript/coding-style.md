# TypeScript Coding Style

## Type System
- Always use explicit types for function parameters and return values
- Avoid `any` type - use `unknown` when type is truly unknown
- Use interfaces for object shapes
- Use type aliases for unions and complex types

## Modern TypeScript
- Use optional chaining (`?.`) and nullish coalescing (`??`)
- Use template literals for string interpolation
- Destructure objects and arrays when appropriate
- Use `const` by default, `let` when reassignment needed

## Async Code
- Use `async/await` over raw Promises
- Always handle Promise rejections
- Use `Promise.all` for parallel async operations
- Avoid mixing async patterns

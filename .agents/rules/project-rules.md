# Project Rules

These rules define the required engineering standards for all code written, modified, or reviewed in this project.

They are mandatory unless the user explicitly approves an exception.

---

## 1. Core Engineering Principles

All code must prioritize:

1. Correctness
2. Reliability
3. Readability
4. Maintainability
5. Testability
6. Failure isolation
7. Performance
8. Minimal complexity

Do not optimize for fewer lines of code at the expense of clarity, reliability, or maintainability.

Do not introduce abstractions, patterns, frameworks, or dependencies unless they provide a clear benefit.

Prefer simple, explicit, predictable implementations over clever or unnecessarily abstract code.

---

## 2. Clean and Readable Code

Code must be easy for another developer to understand without reconstructing the author's intent.

### Requirements

* Use clear and descriptive names.
* Keep functions focused on one responsibility.
* Keep functions reasonably small.
* Separate unrelated responsibilities.
* Avoid deeply nested control flow.
* Prefer early returns when they improve readability.
* Avoid duplicated logic when meaningful reuse is possible.
* Keep business logic separate from infrastructure concerns.
* Avoid hidden side effects.
* Avoid unnecessary global state.
* Keep modules focused and cohesive.

Code should communicate its intent through its structure and naming.

### Avoid

* Extremely long functions
* God classes/modules
* Deeply nested `if/else` structures
* Magic numbers and unexplained constants
* Generic names such as `data`, `result`, `temp`, or `thing` when a meaningful name is possible
* Clever one-liners that reduce readability
* Unnecessary abstractions
* Premature optimization
* Copy-pasted logic

---

## 3. SOLID and Design Principles

Apply SOLID principles where they improve the design.

Do not force SOLID patterns mechanically.

In particular:

* A component should have a clear responsibility.
* Components should depend on abstractions when this meaningfully improves testability or flexibility.
* High-level logic should not be tightly coupled to implementation details.
* New functionality should not require unnecessary modification of unrelated components.

Use engineering judgment rather than applying design patterns for their own sake.

---

## 4. Type Safety and Explicit Interfaces

Python code should use type hints consistently.

### Requirements

* Add type hints to functions and methods.
* Use explicit parameter and return types.
* Avoid ambiguous interfaces.
* Use appropriate types for collections and structured data.
* Keep public interfaces predictable.

Avoid using `Any` unless there is a legitimate reason.

When a function can return multiple meaningful states, make those states explicit rather than relying on undocumented behavior.

---

## 5. Error Handling and Failure Isolation

The application must be designed to fail safely.

An expected runtime failure in one component must not unnecessarily crash unrelated components.

### Common failure cases must be considered

Depending on the component, explicitly account for:

* Network failures
* Connection failures
* Request timeouts
* Invalid responses
* Malformed HTML
* Missing HTML elements
* Unexpected data formats
* Invalid values
* Parsing failures
* Selenium/WebDriver failures
* Browser startup failures
* Database failures
* File I/O failures
* Unexpected exceptions from external dependencies

### Requirements

* Catch exceptions at the appropriate boundary.
* Never use broad exception handling as a substitute for understanding failures.
* Do not silently swallow exceptions.
* Do not hide failures by returning misleading default values.
* Preserve enough information to diagnose the original failure.
* Isolate failures so one failed component does not unnecessarily terminate the entire application.
* Let unrecoverable errors propagate when terminating execution is the correct behavior.

A failure should be handled at the layer that has enough context to make the correct decision.

---

## 6. Scraper Reliability

Scrapers interact with external systems and must assume that external data can change or fail.

Scraper code must not assume that:

* An element always exists.
* HTML structure never changes.
* A response always contains valid data.
* A value is always numeric.
* A page always loads successfully.
* Selenium always starts successfully.
* External services are always available.

Parsing must validate extracted data before returning it to downstream components.

Do not allow malformed or obviously invalid scraped data to silently enter the rest of the pipeline.

When expected page structure is missing, fail in a controlled and observable way.

---

## 7. Logging

The project uses a dedicated project logging system.

All new code must integrate with the project's existing logger instead of creating an unrelated logging system.

Logging must provide enough information to reconstruct what happened during execution.

### Log important events such as

* Application/component startup
* Component shutdown
* Scraper start and completion
* Major processing stages
* External requests when relevant
* Selenium/browser lifecycle events when relevant
* Validation failures
* Parsing failures
* Exceptions
* Timeouts
* Unexpected states
* Database operations when relevant
* Important state transitions
* Final success/failure status of major operations

### Error logging

When an exception is caught:

* Log the error using the project's logger.
* Include the exception details and traceback when appropriate.
* Include enough contextual information to identify the failing component and operation.
* Do not log secrets or sensitive information.

Do not use `print()` for operational logging.

Do not add logging merely to increase log volume.

The goal is **diagnostic completeness**, not maximum log count.

---

## 8. Logging Context

Logs should contain useful context whenever available.

For example, a scraper failure should make it possible to identify:

* Which scraper failed
* Which operation failed
* Which stage failed
* Relevant target/source information
* The exception
* The execution context needed for debugging

Avoid logs such as:

```text
Error occurred
Something went wrong
Failed
```

Prefer logs that explain what failed and where.

---

## 9. Data Validation

Never trust external or intermediate data blindly.

Validate data at appropriate boundaries.

Validation should detect:

* Missing values
* Invalid types
* Invalid formats
* Impossible values
* Unexpected structures
* Corrupted or incomplete results

Validation failures must be observable through the project's logging system.

Do not silently convert invalid data into plausible-looking values.

---

## 10. Defensive Programming

Code should explicitly handle realistic failure conditions.

Before implementing functionality that interacts with an unreliable boundary, consider:

1. What can fail?
2. What happens if it fails?
3. Can the failure affect unrelated components?
4. Is the failure logged?
5. Can the system continue safely?
6. Is the returned state still trustworthy?

Do not add defensive code for purely hypothetical situations when it significantly complicates otherwise simple code.

Defensive programming should target realistic failure modes.

---

## 11. Async and Blocking Code

Do not introduce blocking operations into asynchronous execution paths without an explicit reason and safe isolation strategy.

Avoid blocking operations such as:

* Synchronous network requests
* Blocking file operations when they materially affect async execution
* Blocking subprocess operations
* Selenium/WebDriver operations

inside async code unless they are intentionally isolated.

Never assume that calling a blocking function from an `async` function makes it asynchronous.

Before introducing synchronous work into an async path, consider whether it can block the event loop and affect unrelated tasks.

---

## 12. Concurrency and Resource Management

Concurrency must be introduced deliberately.

Do not create unnecessary:

* Processes
* Threads
* Async tasks
* Browser instances
* Connections
* Sessions

Every concurrently executed operation must have a clear lifecycle.

Resources must be properly released when work completes or fails.

Examples include:

* Browser instances
* WebDriver sessions
* HTTP clients
* Database connections
* Files
* Processes
* Temporary resources

Failure in one concurrent task should not unintentionally terminate unrelated work unless that behavior is explicitly required.

---

## 13. Performance

Performance matters, but correctness and maintainability come first.

Avoid obvious performance problems such as:

* Repeating expensive operations unnecessarily
* Creating resources repeatedly when they can safely be reused
* Unnecessary network requests
* Unnecessary browser launches
* Blocking the event loop
* Excessive process/thread creation
* Loading substantially more data than required
* Inefficient loops over large datasets
* Unbounded memory growth
* Excessive logging inside high-frequency loops

Do not optimize based on assumptions.

When performance is a concern, identify the actual bottleneck before introducing complexity.

---

## 14. Resource Safety

Every acquired resource must have a clear cleanup path.

Use appropriate context managers or structured cleanup mechanisms where applicable.

Examples:

```python
with open(...) as file:
    ...
```

or equivalent lifecycle management for:

* HTTP sessions
* Database connections
* WebDriver instances
* Processes
* Temporary files
* Locks

Cleanup must also be considered when an exception occurs.

---

## 15. Testing

Meaningful code changes must be testable.

When implementing or modifying functionality:

* Add or update appropriate tests when necessary.
* Test normal behavior.
* Test realistic failure cases.
* Test important edge cases.
* Test error isolation where applicable.
* Test validation behavior.
* Test integration boundaries when appropriate.

For scraper-related code, tests should cover realistic malformed or unexpected input where practical.

After meaningful changes, run the relevant test suite or validation commands.

Do not claim that code works unless it has been appropriately validated.

---

## 16. Regression Prevention

When fixing a bug:

1. Identify the root cause.
2. Fix the underlying problem.
3. Add or update a regression test when practical.
4. Verify that the original failure no longer occurs.
5. Verify that related functionality still works.

Do not apply a superficial workaround that merely hides the symptom.

---

## 17. Comments and Documentation

Comments should explain **why**, not simply repeat **what** the code does.

Use comments when:

* The reasoning is non-obvious.
* A workaround exists because of an external limitation.
* A non-intuitive implementation decision must be preserved.
* A constraint is important for future maintainers.

Avoid comments such as:

```python
# Loop through currencies
for currency in currencies:
    ...
```

Prefer code that is self-explanatory.

Do not leave stale comments after changing code.

---

## 18. Dependencies

Do not introduce a new dependency when the standard library or an existing project dependency can reasonably solve the problem.

Before adding a dependency, consider:

* Whether it is actually necessary.
* Whether it overlaps with an existing dependency.
* Maintenance and compatibility.
* Security implications.
* Impact on project complexity.

Do not add dependencies merely for convenience when the benefit is marginal.

---

## 19. Configuration and Secrets

Never hardcode:

* API keys
* Passwords
* Tokens
* Credentials
* Private URLs containing secrets
* Environment-specific secrets

Use the project's established configuration mechanism.

Do not log secrets, credentials, authentication headers, or sensitive environment variables.

---

## 20. Minimal and Focused Changes

When modifying existing code:

* Change only what is necessary.
* Avoid unrelated refactoring.
* Do not rename unrelated files or variables without a reason.
* Do not reformat large unrelated sections.
* Preserve existing behavior unless the task requires changing it.

A small, understandable diff is preferred over a broad cleanup.

---

## 21. Before Adding New Code

Before implementing a new feature or modifying an existing component:

1. Inspect the relevant existing code.
2. Understand its interfaces and dependencies.
3. Check existing utilities before creating new ones.
4. Check existing logging and error-handling patterns.
5. Check existing tests.
6. Reuse established project conventions where appropriate.

Do not create duplicate utilities or parallel implementations without a clear reason.

---

## 22. Before Declaring Completion

Before considering a meaningful implementation complete:

* Verify the implementation.
* Run relevant tests.
* Check for obvious error-handling gaps.
* Check logging coverage.
* Check resource cleanup.
* Check for blocking operations in async paths.
* Check for unnecessary performance costs.
* Confirm that failures are isolated appropriately.
* Confirm that no unrelated files were unnecessarily modified.

The final implementation must be both **functionally correct and operationally observable**.

---

## 23. Engineering Priority

When trade-offs are required, use this priority:

```text
Correctness
    ↓
Reliability / Failure Isolation
    ↓
Observability / Logging
    ↓
Maintainability / Readability
    ↓
Testability
    ↓
Performance
    ↓
Minimal Complexity
```

Performance optimizations must not compromise correctness or reliability without explicit justification.

---

## 24. Rule for Agent Decisions

When uncertain between two implementations, prefer the implementation that is:

* Easier to understand
* Easier to test
* Easier to debug
* Easier to observe through logs
* Safer under failure
* Less coupled
* Less resource-intensive
* Smaller in scope

Do not choose a more complex solution merely because it is more sophisticated.

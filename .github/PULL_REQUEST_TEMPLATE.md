# Description

<!-- Brief description of the changes in this PR. -->

## Related Issue

<!-- Link to the GitHub issue this PR addresses. -->
Closes #

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that causes existing functionality to change)
- [ ] Infrastructure / IaC change
- [ ] Documentation update
- [ ] Refactoring (no functional changes)

## Checklist

### Code Quality

- [ ] Code follows the project's engineering principles (see PID §7.4)
- [ ] All inputs are validated at system boundaries
- [ ] No bare `except:` clauses — all exception handlers are specific
- [ ] No magic strings — constants/enums used for identifiers and paths
- [ ] Type hints on all function signatures (no `Any` return types)

### Testing

- [ ] Unit tests added/updated for new functionality
- [ ] Edge cases covered (invalid input, degenerate geometry, etc.)
- [ ] All existing tests pass (`pytest tests/unit`)

### Tooling

- [ ] `ruff check .` passes with no errors
- [ ] `ruff format --check .` passes
- [ ] `pyright` passes with no errors

### Documentation

- [ ] Docstrings added for new public functions/classes
- [ ] README updated if applicable
- [ ] PID updated if architectural decisions changed

## Testing Notes

<!-- How was this tested? Any special setup required? -->

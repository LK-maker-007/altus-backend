## What does this PR do?

<!-- One paragraph. What problem does it solve? What is the user impact? -->

## Linked issue / ticket

<!-- Paste the GitHub issue URL or Jira/Linear ticket number. -->
<!-- If there's no ticket: explain why this change is self-contained. -->

Closes #

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Refactor / tech debt (no functional change)
- [ ] Documentation / infra / CI only

## Checklist

> Every box must be checked before requesting a review.
> If a box does not apply, check it and write `N/A — <reason>`.

- [ ] `make gate` passes locally (fmt + lint + test)
- [ ] New code has tests — edge cases covered, not just happy path
- [ ] No new `type: ignore` comments added without a comment explaining why
- [ ] No hardcoded secrets, phone numbers, or environment-specific URLs
- [ ] API contract change? → updated `docs/api-contract.md` and versioned endpoint if breaking
- [ ] New migration? → verified reversible (`migrate --backwards` works)
- [ ] New external dependency? → added to `requirements/base.txt` with pinned version
- [ ] SLO-sensitive path changed? → ran `make load-test-smoke` and confirmed thresholds pass

## AI assistance disclosure (required)

- [ ] No AI tools were used in preparing this PR
- [ ] AI tools were used — I have reviewed and verified every line of generated output

## Screenshots / evidence (if UI or API response changes)

<!-- Paste curl output, pytest output, or k6 summary. A PR without evidence is a PR that waits. -->

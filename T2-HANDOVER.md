# T2 handover protocol

## Hypothesis

A second developer can clone, understand, run, and safely extend the tool using
only this repository and a bounded task—without verbal Cortxt context.

## Participant packet

Give the participant only:

1. the repository URL;
2. the task: “Add the synthetic failure `provider_overloaded` as retryable and
   add one fixture/test proving fallback succeeds”;
3. a 45-minute time limit; and
4. the rule that no network calls or dependencies may be added.

## Passing evidence

- clean clone to green tests in at most 10 minutes;
- participant explains the policy boundary and non-idempotent replay guard;
- bounded change implements the new failure without editing unrelated files;
- all tests pass and the result envelope preserves attempt history;
- independent review finds no high-severity correctness or safety issue;
- participant records friction and missing documentation without verbal help.

## Falsifying evidence

- setup requires undocumented local state;
- participant needs verbal architecture context;
- extension requires provider-specific changes in the core;
- unsafe fallback or replay is introduced;
- tests cannot distinguish success from fabricated or incomplete evidence.

## Evidence record

Record timestamps, commands, commit SHA, test output, review verdict, questions
asked, and any verbal assistance. Do not record credentials or model reasoning.

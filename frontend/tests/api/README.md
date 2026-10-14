# Tests of the client itself

The only place outside `src/lib/queries.ts` allowed to import `src/api/`.

A test of the fetch wrapper has to import the fetch wrapper, so this directory
is exempt from the import rule. The exemption is scoped to this path rather
than to tests in general — a *component* test importing the client directly
would be the mistake the rule exists to catch.

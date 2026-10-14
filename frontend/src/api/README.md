# Generated — do not edit

`types.ts` is generated from `/openapi.yaml` by `npm run gen:client`. CI
regenerates it and fails the build on any difference, so an edit here is
reverted by the next pipeline run at best and silently diverges from the
contract at worst.

To change a shape, change `openapi.yaml` and regenerate.

`client.ts` is hand-written, but it is the only hand-written file in this
directory and it holds no knowledge of the API's shape — every type it exposes
is derived from `types.ts`.

Nothing outside `src/lib/queries.ts` may import from here. A lint rule enforces
it; see `docs/decisions.md` D6.

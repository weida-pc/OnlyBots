# Testing protocol

Lesson from the 2026-04-22 session: an API-only test pass can leave real
bugs unseen. A category button that sent `?category=Communication` (title-
case) to a server that only accepts `?category=communication` (lowercase)
passed every curl test I wrote, and broke every click a user made. The
cure is ordering the layers explicitly.

## Order of operations

Always test in this order:

1. **API first** — prove the server contract works in isolation.
   - `curl` / `fetch` every documented request shape.
   - Walk through validation: missing field, wrong type, wrong enum value,
     wrong case, duplicate, unauthorized, rate-limited.
   - Compare the *exact* strings the server expects against the *exact*
     strings the client sends. Most client-vs-server bugs are a
     case/encoding/shape mismatch here.
2. **UI simulation second** — prove the client uses that contract
   correctly.
   - Drive Chrome MCP (`mcp__Claude_in_Chrome__*`).
   - Click every button. Type into every input. Submit every form.
   - Verify both the *visible* state change AND the *network payload*
     using `window.fetch` interception inside `javascript_tool`.
   - If a UI action ultimately produces an API call, verify its body
     matches the shape the API-layer tests established.

The shortcut of "the page loads 200, so everything works" is wrong. That
only tests server-side rendering. Interactive controls need to be driven.

## UI simulation patterns that have caught real bugs

### Intercept network payloads during a click
Inside `mcp__Claude_in_Chrome__javascript_tool`:

```js
const origFetch = window.fetch;
let captured = null;
window.fetch = async (url, opts) => {
  if (typeof url === 'string' && url.includes('/api/services/submit')) {
    const res = await origFetch(url, opts);
    const clone = res.clone();
    captured = {
      requestBody: opts?.body,
      status: res.status,
      responseBody: await clone.text(),
    };
    return res;
  }
  return origFetch(url, opts);
};
// …trigger the UI action, then inspect `captured`
window.fetch = origFetch;
```

This caught the title-case-vs-lowercase category bug on the submit form
— the UI showed the form working, but the request body revealed the
wrong-cased value the server then rejected.

### Verify filter state after a button click
After clicking a filter button, three things must be true:

1. The clicked button is visually selected (inspect class for `bg-green`
   or the selected-marker class you use).
2. The visible card count matches what the API would return.
3. Category tags in the rendered cards all match the chosen filter.

```js
({
  selected: Array.from(document.querySelectorAll('button'))
    .find(b => b.className.includes('bg-green'))?.textContent?.trim(),
  cardCount: document.querySelectorAll('a[href^="/services/"]').length,
  tagDist: Array.from(document.querySelectorAll('span'))
    .map(s => s.textContent.trim())
    .filter(t => ['communication','execution','hosting'].includes(t))
    .reduce((a,t)=>{a[t]=(a[t]||0)+1;return a;}, {}),
})
```

### Debounce respect
Filter/search UIs typically have a 300ms input debounce + network time +
React commit. Wait **at least 1500ms** after a state-changing click
before asserting rendered state, or you'll read the previous response.

### Deep-link / query-param
Never forget that URLs are an interface. Load the page with the params
an agent or human might bookmark and verify the initial state matches
what the URL describes:

```
/?category=execution    → Execution tab pre-selected, 43 cards
/?category=Execution    → same (case-tolerant)
/?q=memoryvault         → search input pre-filled, grid pre-filtered
```

## Known bug classes that this caught

| Class | Example | Where it hid |
|---|---|---|
| Case mismatch | client `Communication` vs server `communication` | API test used the server's own string → passed |
| Fake required marker | red `*` on a field the server accepts missing | Page rendered 200 → passed my old "HTTP 200 = works" test |
| Response shape drift | client reads `data.slug`, server returns `data.service.slug` | Server returned 201 → API test passed; UI redirected to `/services/undefined` |
| Query-param ignored | `?category=execution` URL, UI loads as `All` | The URL *rendered*, so static test didn't notice |
| Cascade error noise | one failure reported three times in three languages | Failure was correct; *message* was confusing |

Every one of these was invisible to a server-only test pass. Only UI
simulation surfaced them.

## Cleanup hygiene

UI tests that submit forms create DB rows. Before leaving the test, delete
the test rows you created:

```sql
DELETE FROM verification_results WHERE run_id IN
  (SELECT id FROM verification_runs WHERE service_id IN
    (SELECT id FROM services WHERE url LIKE '%test-capture%'));
DELETE FROM verification_runs WHERE service_id IN
  (SELECT id FROM services WHERE url LIKE '%test-capture%');
DELETE FROM services WHERE url LIKE '%test-capture%';
```

Use a distinctive URL prefix (`test-capture-only-<hex>.invalid`) for all
test rows so the cleanup DELETE is tight. If the verifier daemon picks up
your test row before you delete it, you've polluted evidence too —
`sudo rm -rf /opt/onlybots/evidence/<run_id>` cleans that.

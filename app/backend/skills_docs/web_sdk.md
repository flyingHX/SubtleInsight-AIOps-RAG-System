# Web SDK

## Description
Frontend authorization and data model access via metagptx/web-sdk. Covers Auth flow, Entity CRUD operations (query/queryAll/get/create/update/delete), and Backend Custom API invocation using client.apiCall.invoke.

## Guide

## Critical Rules
- In Atoms Cloud frontend code, use web-sdk by default instead of direct HTTP calls.
- Use this mapping:
  - Auth: `client.auth.*`
  - Entities / CRUD: `client.entities.*`
  - Custom API under `/api/v1/*`: `client.apiCall.invoke(...)`
  - Object Storage: `client.storage.*`
- Do NOT call `/api/v1/*` with `fetch`, `axios`, `getAPIBaseURL`, `VITE_API_BASE_URL`, `http://localhost`, or `http://127.0.0.1`.

## Frontend Web SDK Usage
### What Web SDK Does
The Web SDK is used for authorization on the frontend and access to the data model data of the backend API through entities.
You can use the SDK to write frontend code to access the data from the backend module.

### Auth

**[CRITICAL] This is NOT Supabase. ONLY these four auth methods exist:**
- `client.auth.me()` — Get current user. Use `res.data` to access user profile
- `client.auth.toLogin()` — Redirect to login page. After login, redirects to /auth/callback
- `client.auth.login()` — Login authentication. Called from callback to save token
- `client.auth.logout()` — Logout

**DO NOT use:** `getSession()`, `getUser()`, `loginWithRedirect()`, `signIn()`, `signUp()`, `onAuthStateChange()` — these do NOT exist.

```ts
import { useEffect } from 'react';
import { createClient } from '@metagptx/web-sdk';

const client = createClient();

// Check login status — use me(), NOT getSession()
useEffect(() => {
  client.auth.me()
    .then((res) => {
      if (res?.data) navigate('/'); // or your real post-login route
    })
    .catch(() => {}); // Not logged in, show login UI
}, []);

// Trigger login — use toLogin(), NOT loginWithRedirect()
const handleLogin = () => { client.auth.toLogin(); };

// Auth Steps, MUST Follow
/*
1. [CRITICAL] the `src/pages/AuthCallback.tsx` file is read-only, Don't use Editor.write to modify it.
2. Routing Setup: Add the route `/auth/callback` to `frontend/src/App.tsx`. The component must be imported using `import AuthCallback from './pages/AuthCallback'`;.
3. Login Flow: Implement the login logic using `client.auth.toLogin`. The application must redirect to the AuthCallback page immediately following a successful login.
4. [CRITICAL] Use an empty dependency array in `useEffect` to prevent repeated authentication when user state updates. Like `useEffect(() => { checkAuth(); // update user state after login }, [])`. When auth fails, show login UI instead of auto-redirect.
5. [CRITICAL] NEVER use `if (!user) Navigate to /auth/callback` - this causes INFINITE LOOPS because `/auth/callback` only works with OIDC callback parameters (code, state). Show a login button that calls `client.auth.toLogin()` instead. And don't use `Header` inside `Router` in `src/App.tsx`.
*/
```

#### Auth State Handling
- Treat auth as a 3-state value: `loading`, `authenticated`, `anonymous`. While `client.auth.me()` is pending, do NOT assume the user is logged out or auto-trigger `client.auth.toLogin()`.
- On landing pages and purchase or upgrade entries, wait for auth resolution before deciding whether a primary CTA should navigate into the app or send the user to login.
- Do NOT call `client.auth.toLogin()` from a broad `catch` that also wraps quota, history, purchase, upgrade, or other business requests. If auth already succeeded, business API failures should show a visible error or retry state instead of redirecting to login.

#### Payment Entry And Checkout Handling
- If payment, billing, subscriptions, paid upgrade, credits, or top-up is part of the requirement, provide at least one real checkout entry that is reachable through the intended purchaser flow. If the billing UX is specified, follow it. Otherwise, choose the simplest product-appropriate pattern.
- Keep checkout CTA logic explicit: user action -> `client.apiCall.invoke({ url: '/api/v1/payment/create_payment_session', ... })` -> `client.utils.openUrl(response.data.url)` -> success route reads `session_id` -> verify endpoint updates backend-owned state.
- Button text changing to `Loading` or `Redirecting` is not enough. The frontend must actually open the checkout URL returned by the backend or show a visible error state.

### Common Web SDK Mistakes
- `client.auth.getSession()` is not a valid web-sdk auth API here. Use `await client.auth.me()` and read the user object from `response.data`.
- When login is required, use `client.auth.toLogin()` instead of inventing a different auth redirect flow.
- Do not treat initial `user = null` as the final anonymous state before `client.auth.me()` resolves; use an explicit auth loading state.
- Do not redirect to login just because quota, history, purchase, upgrade, or another custom API request failed during page initialization.
- For entity writes such as `create()` and `update()`, wrap payload fields inside `data: { ... }`.
- When fixing a web-sdk usage bug, check the other files touched by the same bounded feature for the same old call pattern before considering the fix complete. Do not assume the first broken file is the only occurrence.
- Do not hide the only upgrade or purchase path behind a non-obvious or exhausted-state-only branch unless the requirement explicitly asks for it.
- Do not treat the billing flow as complete when the UI never actually opens the backend-returned checkout URL.

### Entity Access and Operation
[CRITICAL]. Use `response.data` to access actual entity data instead of `response` itself.

```ts
// photo_works is the entity name
// Get the logged-in user's list of photo_works. For example, display personal uploaded photo works.
// Also used to obtain public entity data, such as product lists and course lists from user-independent entity which `create_only=false`.
const response = await client.entities.photo_works.query({
  query: { status: 'active' },      // optional, can be {}
  sort: '-created_at',              // optional
  limit: 10,                        // optional
  skip: 0,                          // optional
  fields: ['id', 'title', 'tags'],  // optional
});  // Pay Attention. Use `response.data.items` which is list[dict] to access entities' data
// Should use `await client.entities` but not `await api.client.entities` if `api` from `import { api } from '../lib/api';`

// Get all user's list of photo_works. For example, display all photo works in a photography gallery.
// [CRITICAL] The `queryAll` method must only be used within user-related entities that are marked with the `create_only=true` flag. This constraint is mandatory.
const response = await client.entities.photo_works.queryAll({
  query: { status: 'active' },      // optional, can be {}
  sort: '-created_at',              // optional
  limit: 10,                        // optional
  skip: 0,                          // optional
  fields: ['id', 'title', 'tags'],  // optional
});

// Get one PhotoWork with particular fields
const response = await client.entities.photo_works.get({
  id: '12345',                      // required
  fields: ['id', 'title', 'tags'],  // optional
});
// const photoWork: PhotoWork = response.data;

// Create a photo_works entity
const response = await client.entities.photo_works.create({
  data: {
    title: 'classic photography',
    tags: 'classic, art',
  },
});
// const photoWork: PhotoWork = response.data;

// Update photo_works entity with id
const response = await client.entities.photo_works.update({
  id: '12345',
  data: {
    title: 'natural portrait',
  },
});
// const photoWork: PhotoWork = response.data;

// Delete photo_works entity with id
await client.entities.photo_works.delete({ id: '12345' });
```

### Backend Custom API Integration
// use `client.apiCall.invoke` to integrate backend apis
```ts
// GET request with query parameters
const response = await client.apiCall.invoke({
  url: '/api/v1/payment/custom',    // API endpoint path, MUST starts with /api/v1/
  method: 'GET',
  data: { filter: 'active' },        // Request data (body for POST/PUT/PATCH, query params for GET/DELETE)
});

// POST request with body data
const response = await client.apiCall.invoke({
  url: '/api/v1/payment/create_payment_session', // API endpoint path, MUST starts with /api/v1/
  method: 'POST',
  data: { order_id: 123 },
  options: {                         // Additional axios request options like headers
    headers: { 'X-Custom-Header': 'value' },
  },
});  // Pay Attention. Use `response.data` to access data
// Pay Attention. Use `client.utils.openUrl(response.data.url)` to Redirect to Stripe checkout page
```

#### Requirement-Critical CTA Patterns

```ts
// Payment CTA: the button must start a real checkout flow
const handleUpgrade = async () => {
  try {
    const response = await client.apiCall.invoke({
      url: '/api/v1/payment/create_payment_session',
      method: 'POST',
      data: {},
    });
    client.utils.openUrl(response.data.url);
  } catch (e: any) {
    toast({
      title: e?.data?.detail || e?.response?.data?.detail || e?.message || 'Failed to start checkout',
      variant: 'destructive',
    });
  }
};

// Payment success route: verify before showing paid state
const verifyCheckout = async (sessionId: string) => {
  try {
    const response = await client.apiCall.invoke({
      url: '/api/v1/payment/verify_payment',
      method: 'POST',
      data: { session_id: sessionId },
    });
    return response.data;
  } catch (e: any) {
    throw new Error(
      e?.data?.detail || e?.response?.data?.detail || e?.message || 'Failed to verify payment'
    );
  }
};

// Result CTA: the button must either navigate to a real result or show a visible error
const handleGenerate = async () => {
  setLoading(true);
  setError('');
  try {
    const response = await client.apiCall.invoke({
      url: '/api/v1/content/generate',
      method: 'POST',
      data: formData,
    });
    navigate(`/result/${response.data.id}`);
  } catch (e: any) {
    setError(e?.data?.detail || e?.response?.data?.detail || e?.message || 'Generation failed');
  } finally {
    setLoading(false);
  }
};
```


### Wrong vs Correct Custom API Call
```ts
// Wrong
const response = await fetch(`${getAPIBaseURL()}/api/v1/payment/custom`, {
  method: 'GET',
  credentials: 'include',
});

// Correct
const response = await client.apiCall.invoke({
  url: '/api/v1/payment/custom',
  method: 'GET',
  data: {},
});
// Use `response.data` to access data
```

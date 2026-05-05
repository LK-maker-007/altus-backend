/**
 * load-tests/k6/smoke.js — Smoke test (CI-safe, < 30 seconds)
 *
 * PURPOSE:
 *   Run on every pull request in CI to catch performance regressions
 *   before they reach production. Lightweight: 5 VUs, 20s duration.
 *
 * WHAT IT TESTS:
 *   - Health check responds < 50ms
 *   - Auth flow (login + OTP verify) completes successfully
 *   - Core read endpoints respond within SLO
 *
 * RUN:
 *   k6 run load-tests/k6/smoke.js
 *   k6 run --env K6_BASE_URL=https://staging.yali.app load-tests/k6/smoke.js
 *
 * CI (GitHub Actions):
 *   - name: k6 smoke test
 *     run: k6 run load-tests/k6/smoke.js
 *     env:
 *       K6_BASE_URL: http://localhost:8000
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { THRESHOLDS, BASE_URL, JSON_HEADERS, authHeaders, authenticate } from './config.js';

export const options = {
  vus: 5,
  duration: '20s',
  // Single source of truth — THRESHOLDS from config.js includes all endpoint SLOs.
  // Updating config.js propagates to all scripts automatically.
  thresholds: THRESHOLDS,
};

/**
 * setup() runs once before the test begins.
 * Authenticates and returns token to all VUs.
 */
export function setup() {
  return authenticate();
}

/**
 * Default function — runs once per VU per iteration.
 *
 * Scenario: A security guard / resident opens the app:
 *   1. Health check (probed by load balancer, always fast)
 *   2. Visitor list
 *   3. Facility list
 *   4. Think time (user reads the screen)
 */
export default function (data) {
  const headers = authHeaders(data.access_token);

  // ── Health probe ───────────────────────────────────────────────────────────
  const healthRes = http.get(`${BASE_URL}/api/v1/health/`, {
    tags: { name: 'health_check' },
  });
  check(healthRes, {
    'health: status 200': (r) => r.status === 200,
    'health: status ok': (r) => r.json('status') === 'ok',
  });

  sleep(0.1); // 100ms think time

  // ── Visitor list ───────────────────────────────────────────────────────────
  const visitorsRes = http.get(`${BASE_URL}/api/v1/visitors/`, {
    ...headers,
    tags: { name: 'visitors_list' },
  });
  check(visitorsRes, {
    'visitors: status 200': (r) => r.status === 200,
  });

  sleep(0.2); // 200ms think time (user reads list)

  // ── Facility list ──────────────────────────────────────────────────────────
  const facilitiesRes = http.get(`${BASE_URL}/api/v1/facilities/`, {
    ...headers,
    tags: { name: 'facilities_list' },
  });
  check(facilitiesRes, {
    'facilities: status 200': (r) => r.status === 200,
  });

  sleep(0.5); // 500ms think time between iterations
}

/**
 * load-tests/k6/config.js — Shared configuration for all k6 test scripts.
 *
 * This is the single source of truth for:
 *   - Base URL (overridable via K6_BASE_URL env var)
 *   - SLO thresholds per endpoint group (from api-contract.md)
 *   - Shared auth flow (OTP login via mock SMS provider)
 *
 * MAANG pattern: SLOs are encoded as thresholds — the test FAILS if the
 * SLO is violated. This prevents "green dashboard, degraded experience"
 * scenarios where latency quietly drifts above acceptable limits.
 *
 * Source: Grafana k6 docs + Netflix Reliability Engineering patterns (2025)
 */

import http from 'k6/http';
import { check } from 'k6';

export const BASE_URL = __ENV.K6_BASE_URL || 'http://localhost:8000';
export const TEST_PHONE = __ENV.K6_TEST_PHONE || '+919000099999';
// Mock SMS provider (SMS_PROVIDER=mock in test env) always accepts 000000
export const OTP_CODE = '000000';

/**
 * Shared SLO thresholds.
 *
 * Applied via:
 *   export const options = {
 *     thresholds: THRESHOLDS,
 *     ...
 *   };
 *
 * p(95) < Xms means 95% of requests must complete within X milliseconds.
 * http_req_failed rate < 0.01 means error rate must be below 1%.
 *
 * Threshold values derived from api-contract.md and mobile UX standards:
 *   - < 200ms: "instant" on mobile (no noticeable delay)
 *   - < 500ms: "fast" on mobile (minor delay, acceptable)
 *   - < 1000ms: "acceptable" (visible delay, not good for auth flows)
 */
export const THRESHOLDS = {
  // Global defaults
  http_req_failed: ['rate<0.01'],               // <1% error rate overall
  http_req_duration: ['p(95)<500'],             // 95th percentile < 500ms

  // Endpoint-group SLOs (tagged via http.get/post params.tags.name)
  'http_req_duration{name:auth_login}': ['p(95)<500'],
  'http_req_duration{name:auth_verify}': ['p(95)<500'],
  'http_req_duration{name:auth_refresh}': ['p(95)<300'],
  'http_req_duration{name:visitors_list}': ['p(95)<200'],
  'http_req_duration{name:visitor_arrive}': ['p(95)<300'],
  'http_req_duration{name:facilities_list}': ['p(95)<200'],
  'http_req_duration{name:facility_slots}': ['p(95)<300'],
  'http_req_duration{name:packages_list}': ['p(95)<200'],
  'http_req_duration{name:maintenance_list}': ['p(95)<200'],
  'http_req_duration{name:health_check}': ['p(95)<50'],   // Probe must be <50ms
};

/** Build a JSON request params object with Bearer token. */
export function authHeaders(token) {
  return {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
  };
}

/** Plain JSON headers (no auth). */
export const JSON_HEADERS = {
  headers: { 'Content-Type': 'application/json' },
};

/**
 * Authenticate via OTP flow and return tokens.
 *
 * Must be called from k6 setup() — runs once per test run,
 * tokens shared across all VUs via setup() return value.
 *
 * NOTE: Requires the test DB to have a user with TEST_PHONE already created.
 * The conftest.py resident fixture creates this user. In CI, run:
 *   make migrate && ./manage.py create_load_test_user
 */
export function authenticate() {
  // Step 1: send OTP
  const loginPayload = JSON.stringify({ phone_number: TEST_PHONE });
  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login/`,
    loginPayload,
    JSON_HEADERS,
  );
  check(loginRes, {
    'auth/login: status 200': (r) => r.status === 200,
    'auth/login: otp_sent in response': (r) => r.json('status') === 'otp_sent',
  });

  // Step 2: verify OTP (mock provider always accepts 000000)
  const verifyPayload = JSON.stringify({
    phone_number: TEST_PHONE,
    code: OTP_CODE,
    auth_flow: 'login',
  });
  const verifyRes = http.post(
    `${BASE_URL}/api/v1/auth/verify-otp/`,
    verifyPayload,
    JSON_HEADERS,
  );
  check(verifyRes, {
    'auth/verify-otp: status 200': (r) => r.status === 200,
    'auth/verify-otp: has access_token': (r) => !!r.json('access_token'),
  });

  return {
    access_token: verifyRes.json('access_token'),
    refresh_token: verifyRes.json('refresh_token'),
  };
}

// Load test for the "SLO tenus" measurement: 30 minutes on the healthy release.
// Run through scripts/experiments/slo_loadtest.py, which also reads the SLIs from
// Prometheus over the same window and writes results/slo/summary.json.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.NEURALRAG_URL || 'http://localhost:8080';
const KEY = __ENV.API_KEY;
const QUESTIONS = [
  "Qu'est-ce qu'un budget d'erreur ?",
  'Comment fonctionne une alerte multi-fenêtres ?',
  'Que fait Argo CD ?',
  'Comment un canary est-il annulé ?',
  'Quelle est la différence entre RTO et RPO ?',
];

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-vus',
      vus: Number(__ENV.VUS || 2),
      duration: __ENV.DURATION || '30m',
    },
  },
  // Client-side view of the same SLOs (the published numbers come from Prometheus).
  thresholds: {
    http_req_failed: ['rate<0.005'],
    http_req_duration: ['p(95)<10000'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const q = QUESTIONS[Math.floor(Math.random() * QUESTIONS.length)];
  const res = http.post(`${BASE}/api/query`, JSON.stringify({ question: q }), {
    headers: { 'Content-Type': 'application/json', 'X-API-Key': KEY },
    timeout: '60s',
  });
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}

// Machine-readable summary for results/ (the text summary is not needed).
export function handleSummary(data) {
  return { [__ENV.SUMMARY_FILE || '/out/k6-summary.json']: JSON.stringify(data, null, 2) };
}

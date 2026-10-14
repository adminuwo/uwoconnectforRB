# 🌐 UwoConnect — Master API Endpoints Audit & Health Report

> **Execution Date**: `2026-10-07 16:30:17`  
> **Total Registered Patterns**: `819` | **Evaluated Endpoints**: `428`  
> **Overall Health Pass Rate**: **100.0% (428/428)**  
> **Server Crashes (500s / Exceptions)**: **✅ 0 Failures (Zero 500s)**  
> **Average Latency**: `312.8 ms` | **Total Execution Time**: `134.63 s`  

---

## 📊 1. HTTP Status Code Distribution

| Status Code | Description | Count | Share (%) |
| :--- | :--- | :--- | :--- |
| `200` | 200 OK (Successful Retrieval / Evaluation) | **187** | 43.7% |
| `201` | 201 Created | **2** | 0.5% |
| `301` | HTTP 301 | **92** | 21.5% |
| `302` | 302 Redirect / Temporary Move | **8** | 1.9% |
| `400` | 400 Bad Request (Clean Serializer Validation) | **67** | 15.7% |
| `401` | 401 Unauthorized (Auth Guard Working) | **17** | 4.0% |
| `403` | 403 Forbidden (RBAC Guard Working) | **3** | 0.7% |
| `404` | 404 Not Found (Entity ID / Filter Handled Cleanly) | **48** | 11.2% |
| `405` | 405 Method Not Allowed (Expected HTTP Verb Constraint) | **3** | 0.7% |
| `415` | HTTP 415 | **1** | 0.2% |

---

## ⏱️ 2. Top Latency Outliers (Endpoints taking ≥ 1000ms)

| # | Endpoint URL | Role | Status | Latency (ms) |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `/api/admin/clients/6a5338debec6daea1165d2b3/dashboard/` | `ADMIN` | `200` | **10868.8 ms** |
| 2 | `/api/email/messages/` | `CLIENT` | `200` | **10707.0 ms** |
| 3 | `/api/client/entitlements/` | `CLIENT` | `200` | **9902.3 ms** |
| 4 | `/api/client/select-channel/` | `CLIENT` | `200` | **9320.1 ms** |
| 5 | `/api/client/subscribe/` | `CLIENT` | `200` | **9096.3 ms** |
| 6 | `/api/admin/clients-directory/` | `ADMIN` | `200` | **8246.0 ms** |
| 7 | `/api/competitor-analysis/discover/` | `CLIENT` | `200` | **6697.8 ms** |
| 8 | `/api/quotations/` | `CLIENT` | `200` | **4556.0 ms** |
| 9 | `/api/sales-documents/` | `CLIENT` | `200` | **4313.3 ms** |
| 10 | `/api/proposals/` | `CLIENT` | `200` | **4106.7 ms** |
| 11 | `/api/admin/client-intelligence/stats/` | `ADMIN` | `200` | **3538.4 ms** |
| 12 | `/api/contacts/` | `CLIENT` | `200` | **3473.4 ms** |
| 13 | `/api/admin/wallet/overview/` | `ADMIN` | `200` | **2408.3 ms** |
| 14 | `/api/admin/app-analytics/` | `ADMIN` | `200` | **1951.4 ms** |
| 15 | `/api/admin/clients/6a5338debec6daea1165d2b3/details/` | `ADMIN` | `200` | **1718.7 ms** |
| 16 | `/api/admin/client-intelligence/clients/6a5338debec6daea1165d2b3/` | `ADMIN` | `200` | **1677.0 ms** |
| 17 | `/api/youtube/videos/` | `CLIENT` | `200` | **1672.6 ms** |
| 18 | `/api/youtube/analytics/` | `CLIENT` | `200` | **1641.3 ms** |
| 19 | `/api/admin/content/` | `ADMIN` | `200` | **1598.6 ms** |
| 20 | `/api/payments/create-order/` | `CLIENT` | `201` | **1459.8 ms** |
| 21 | `/api/admin/team-summary/` | `ADMIN` | `200` | **1287.5 ms** |
| 22 | `/api/admin/channel-access/matrix/` | `ADMIN` | `200` | **1270.0 ms** |
| 23 | `/api/team/ai-copilot/` | `CLIENT` | `200` | **1263.6 ms** |
| 24 | `/api/youtube/broadcast-check/` | `CLIENT` | `200` | **1155.5 ms** |
| 25 | `/api/admin/channel-access/client/6a5338debec6daea1165d2b3/` | `ADMIN` | `200` | **1001.9 ms** |

---

## 🎯 3. Audit Verdict

- **Endpoint Availability**: 428/428 endpoints are functional without server-side crashes.
- **Crash Rate**: 0 unhandled 500 exceptions.
- **Report Exported**: Structured telemetry saved to [`backend_comprehensive_audit_report.json`](file:///b:/Uwo_Connect/UWO-CONNECT_B/backend_comprehensive_audit_report.json).
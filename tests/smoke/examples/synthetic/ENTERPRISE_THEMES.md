# Enterprise Vibe-Coded App Themes

## The Generative Story

An enterprise has departments: Sales, Marketing, Finance, HR, Product, Engineering, IT, Legal, Customer Success, Operations, Procurement. Each relies on **systems of record** (SoR): Salesforce, Oracle/SAP/NetSuite, Workday, ServiceNow, SharePoint/Confluence, Jira, Slack/Teams, Snowflake/BigQuery, Zendesk, DocuSign, Okta, Stripe.

**The gap**: These systems are powerful but rigid. Data doesn't flow between them. Reports don't answer the specific question you have. The business logic that IS the company's competitive advantage can't be encoded in an off-the-shelf tool. Manual processes involve copying data from system A to system B every Tuesday.

**Who builds**: Sales ops analysts, marketing analysts, finance associates, HR coordinators, customer success managers, product managers, DevOps engineers — people technical enough to prompt an AI to write code but not professional software engineers.

**What triggers app creation**:
- "We're paying $60k/year for a tool and only using 20% of it"
- "Our pricing/discount/commission logic is unique and no vendor handles it"
- "I need to bridge data between System A and System B"
- "The vendor's algorithm is a black box — I want transparency"
- "I'm tired of doing this manually every week"

**The result**: A working app in 2 hours. No auth. Hardcoded API keys. `debug=True`. Deployed on a VM or Streamlit Cloud. People depend on it. Nobody hardened it.

---

## Category A: SaaS Replacement & Custom Business Logic

These are the high-value, high-risk apps. They replace expensive vertical SaaS with custom logic that encodes the company's competitive advantage.

### A1. Custom CPQ & Deal Desk
Sales ops replacing Salesforce CPQ ($150/user/mo). App applies company-specific discount logic: volume tiers, multi-year ramps, bundle discounts. Enforces margin floors. Routes exceptions for VP approval.

### A2. Custom Contract Lifecycle Management (CLM)
Legal ops replacing Ironclad/Agiloft ($60k/yr). Lightweight wizard: sales reps input terms, app generates MSA from approved templates, tracks redlines, manages signature workflow via DocuSign API.

### A3. Attribution & Lead Scoring Engine
Marketing ops replacing Marketo's black-box scoring. Custom Python model pulling raw event data from Snowflake, applying proprietary scoring weights, full transparency on why each lead scored what it did.

### A4. Commission Calculator
RevOps replacing CaptivateIQ/Xactly ($40k/yr). Encodes split rules (60/40 overlay), quarterly accelerators above 120% attainment, SPIFFs for new logos. Pulls Salesforce closed-won, calculates payouts.

### A5. Usage-Based Billing Engine
Finance replacing Zuora for specific pricing model. Pulls usage metrics from product DB, applies tiered/volume/per-seat pricing with custom overage rules, generates invoices via Stripe.

### A6. Revenue Recognition Automator
Controller replacing spreadsheet RevRec. Implements ASC 606 rules specific to contract types (multi-year, ramp deals, usage-based). Reads billing, writes journal entries to NetSuite.

### A7. Budget Variance Analyzer
FP&A replacing Anaplan for monthly variance analysis. Pulls actuals from NetSuite + headcount from Workday + cloud spend from AWS, computes variance, flags items >10% over budget.

### A8. Territory Carving Tool
Sales ops replacing expensive territory planning. Takes account list + rep capacity + geography, runs optimization (industry, ARR potential, travel radius), outputs balanced territories.

### A9. Renewal Risk Scorer
CS ops replacing Gainsight health score. Proprietary signals: usage drop >20%, tickets up, champion departed (LinkedIn), payment delayed. Weighted model with customizable thresholds.

### A10. Feature Flag Manager
Engineer replacing LaunchDarkly for 15-flag use case. Flags in Redis/Postgres, percentage rollouts, user-segment targeting, audit log, kill switch.

### A11. Release Readiness Gate
Engineering manager building deploy blocker. Checks: test coverage >80%, no P0 bugs, changelog written, security scan passed, on-call confirmed. All via API integrations.

### A12. Compensation Benchmarker
HR analyst replacing Radford ($25k/yr). Imports offer/acceptance data, market data from levels.fyi, computes percentile bands by role/level/geo, flags outliers.

### A13. Performance Calibration Tool
HRBP building calibration session tool. Pulls reviews from Lattice, displays 9-box grid, tracks live adjustments, enforces distribution curve.

### A14. QBR Deck Generator
CSM replacing 4-hour manual deck creation. Pulls usage metrics, support summary, feature adoption, NPS, renewal date — generates polished deck with AI narrative.

### A15. Custom Escalation Engine
Support VP replacing ServiceNow workflow module. Rules: P1 = page on-call + Slack VP within 5min; P2 = assign senior within 1hr; auto-escalate on SLA breach.

### A16. Cloud Cost Optimizer
FinOps replacing CloudHealth. Analyzes AWS/GCP/Azure spend, identifies idle resources (unused volumes, oversized instances, orphaned snapshots), estimates savings, generates cleanup tickets.

### A17. SaaS License Reclaimer
IT admin tracking usage across 40 SaaS tools via Okta login data. Flags no-login >60 days, auto-deprovisions at 90 days, tracks savings by tool.

### A18. Access Review Automation
Security analyst replacing GRC tool. Quarterly pulls permissions from Okta/AWS IAM/GitHub, sends manager review forms, tracks attestation, auto-revokes unattested access.

---

## Category B: Data Bridge & Integration

These are the "plumbing" apps. They move data between systems that don't natively talk to each other.

### B1. CRM-to-ERP Bridge
Sales ops syncing Salesforce deals → NetSuite invoices. Triggered on closed-won. OAuth tokens for both systems, scheduled polling, conflict resolution.

### B2. Lead Enrichment Pipeline
SDR manager enriching inbound leads with Clearbit/Apollo data before they hit Salesforce. Webhook → enrich → push to CRM.

### B3. HR Onboarding Orchestrator
HR coordinator automating account creation across 12 systems when new hire appears in Workday (AD, Google Workspace, Slack, Jira, GitHub).

### B4. Webhook Relay & Transformer
DevOps routing webhooks between systems: Stripe events → Slack, GitHub PRs → Jira tickets, form submissions → CRM. Payload transformation in between.

### B5. Compliance Evidence Collector
GRC analyst pulling audit evidence from AWS CloudTrail + GitHub audit logs + Okta + Jira to satisfy SOC2 controls.

### B6. Vendor Spend Analyzer
Procurement pulling AP data from Oracle/NetSuite, enriching with contract terms, generating spend-by-vendor reports.

### B7. Automated Report Generator
Finance analyst generating the same 6 reports every month-end from 4 systems, formatting in Excel, emailing to distribution lists.

### B8. Employee Directory & Org Chart
IT building better people search than HRIS. Pulls from Workday + Slack + Jira project assignments + org hierarchy.

---

## Category C: AI-Enhanced Enterprise Tools

These use LLMs/ML to add intelligence to business processes.

### C1. AI Ticket Triage
Support lead auto-classifying Zendesk tickets with LLM, routing to right team, drafting initial responses. Webhook → OpenAI → Zendesk update.

### C2. Invoice/Receipt OCR
AP clerk extracting invoice data from PDFs. Upload → AI extracts line items/amounts/vendor → push to accounting system.

### C3. Internal Knowledge RAG Bot
IT building Q&A chatbot over company policies in SharePoint/Confluence. Embeddings + vector store + LLM.

### C4. Contract Clause Extractor & Risk Scorer
Legal ops extracting key terms from contracts, comparing against approved fallback positions, scoring risk (red/yellow/green).

### C5. Win/Loss Analyzer
Sales enablement pulling deal data + call transcripts from Gong, running LLM analysis for loss reasons, competitive mentions, pricing objections.

### C6. Meeting Notes Summarizer
PM transcribing Zoom recordings with Whisper, generating summaries + action items with LLM, posting to Slack/Notion.

### C7. Customer Feedback Analyzer
Product person ingesting NPS/CSAT from Typeform/Delighted, running sentiment analysis + topic clustering, surfacing themes.

### C8. Expense Anomaly Detector
Finance running anomaly detection on expense reports. Flags weekend spending, round numbers, duplicate amounts, vendor concentration.

### C9. DSAR Processor
Privacy officer handling GDPR requests. Searches across 8 systems, compiles data package, redacts per policy, tracks 30-day deadline.

### C10. Incident Postmortem Generator
SRE pulling timeline from PagerDuty + Slack + deploy logs, AI drafts postmortem, identifies contributing factors, tracks action items.

---

## Category D: Dashboards & Monitoring

Real-time visibility tools that replace expensive BI licenses or provide views the standard tools can't.

### D1. Multi-Channel Ad Dashboard
Marketing pulling Google Ads + Meta + LinkedIn spend into unified dashboard. Daily refresh, custom ROAS calculations.

### D2. Customer Health Dashboard
CS ops composite view: product usage (Amplitude) + tickets (Zendesk) + billing (Stripe) + NPS.

### D3. Data Quality Monitor
Data engineer running scheduled checks on Snowflake/BigQuery: row counts, null rates, freshness, schema drift. Alerts on breach.

### D4. SLA Compliance Tracker
Operations tracking SLA across 20 vendors: uptime from status pages, response times from support APIs, delivery from logistics.

### D5. Support SLA Dashboard
Real-time Zendesk metrics: first response time, resolution time, CSAT by agent/team, SLA breach countdown.

### D6. Product Usage Analytics
Product manager with custom metrics from ClickHouse that Amplitude doesn't compute: cohort retention by plan tier, feature correlation with expansion.

### D7. Sales Forecast Rollup
Sales ops building weighted pipeline forecast. Pulls Salesforce opportunities, applies stage-specific win rates, shows best/likely/worst by quarter.

---

## Category E: Workflow & Portal Apps

Self-service portals and workflow automation that replace manual processes or expensive workflow tools.

### E1. Partner Deal Registration Portal
Channel manager: partners submit deals, app checks CRM for conflicts, routes approvals, creates opportunity if approved.

### E2. Slack/Teams Approval Bot
Approval workflows (PO, access request, time-off) via bot commands instead of buying ServiceNow licenses for everyone.

### E3. Procurement Request Portal
Internal portal for purchase requests. Requester fills form, app checks budget, routes to appropriate approver based on amount, creates PO.

### E4. Deal Desk Approval Workflow
Non-standard deals routed through approval chain: rep submits → manager auto-approves <15% discount → VP required >15% → Legal for non-standard terms.

### E5. Vendor Qualification Scorecard
Procurement assessment tool: financial data (D&B), security questionnaire, references, pricing → weighted score → enforce minimum thresholds.

### E6. Headcount Planning Portal
HR/FP&A: department heads submit hiring plans, system computes loaded cost by level/geo, models scenarios, compares to budget.

### E7. Customer Onboarding Tracker
CSM tracking onboarding milestones: account setup, data migration, training, go-live. Pulls from multiple systems, sends reminders, escalates delays.

### E8. Training/LMS Tracker
L&D building lightweight training tracker: course completion, quiz scores, certification expiry, compliance deadlines. Integrates with video platform.

### E9. Internal Billing Portal
Finance building customer self-service: view invoices, download receipts, update payment method, see usage. Wraps Stripe customer portal with custom logic.

### E10. Investor Data Room
Finance/Legal managing due diligence documents. Upload to S3, granular access controls per document/folder, audit logging, watermarking.

---

## App Distribution (70 apps)

### Batch 1 (apps 31-40): SaaS Replacements
31. CPQ quote generator (A1)
32. CLM contract wizard (A2)
33. Commission calculator (A4)
34. Usage-based billing engine (A5)
35. Revenue recognition automator (A6)
36. Budget variance analyzer (A7)
37. Territory carving tool (A8)
38. Feature flag manager (A10)
39. Release readiness gate (A11)
40. Cloud cost optimizer (A16)

### Batch 2 (apps 41-50): AI-Enhanced Tools
41. Lead scoring war room (A3)
42. AI ticket triage (C1)
43. Invoice OCR pipeline (C2)
44. Internal RAG chatbot (C3)
45. Contract clause risk scorer (C4)
46. Win/loss analyzer (C5)
47. Meeting notes summarizer (C6)
48. Expense anomaly detector (C8)
49. DSAR processor (C9)
50. Incident postmortem generator (C10)

### Batch 3 (apps 51-60): Dashboards & Monitoring
51. Multi-channel ad dashboard (D1)
52. Customer health dashboard (D2)
53. Data quality monitor (D3)
54. SLA compliance tracker (D4)
55. Support SLA dashboard (D5)
56. Product usage analytics (D6)
57. Sales forecast rollup (D7)
58. Renewal risk scorer (A9)
59. Compensation benchmarker (A12)
60. Performance calibration tool (A13)

### Batch 4 (apps 61-70): Workflows & Integration
61. CRM-to-ERP bridge (B1)
62. Lead enrichment pipeline (B2)
63. HR onboarding orchestrator (B3)
64. Partner deal registration portal (E1)
65. Slack approval bot (E2)
66. Deal desk approval workflow (E4)
67. Customer feedback analyzer (C7)
68. SaaS license reclaimer (A17)
69. Access review automation (A18)
70. QBR deck generator (A14)

### Batch 5 (apps 71-80): More Workflows & Portals
71. Procurement request portal (E3)
72. Vendor qualification scorecard (E5)
73. Headcount planning portal (E6)
74. Customer onboarding tracker (E7)
75. Webhook relay transformer (B4)
76. Compliance evidence collector (B5)
77. Automated report generator (B7)
78. Employee directory search (B8)
79. Vendor spend analyzer (B6)
80. Training/LMS tracker (E8)

### Batch 6 (apps 81-90): Advanced Enterprise
81. Custom escalation engine (A15)
82. Internal billing portal (E9)
83. Investor data room (E10)
84. Board meeting packet generator
85. Customer segmentation engine
86. Churn prediction API
87. Custom NPS survey tool
88. Competitive intelligence tracker
89. Content calendar with AI generation
90. IT asset tracker (Jamf + Intune)

### Batch 7 (apps 91-100): Edge Cases & Complex
91. Sales enablement content hub
92. Custom SSO/SAML proxy
93. Log aggregation dashboard
94. Security vulnerability prioritizer
95. Marketing mix model
96. Custom ETL pipeline scheduler
97. Customer reference manager
98. Product changelog & release notes
99. Pricing simulator & scenario modeler
100. Multi-entity consolidation (finance)

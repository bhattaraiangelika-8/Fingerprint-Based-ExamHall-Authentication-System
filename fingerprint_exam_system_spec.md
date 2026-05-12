# Fingerprint Lock Examination System — Engineering Feature Specification

**Document type:** Feature specification for engineering team  
**Project status:** Fingerprint Photo Processing & Matching Pipeline complete (AS608 scanner integration, biometric data storage done)  
**Purpose:** Define all remaining modules required for a fully deployable examination system

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Pre-Exam Phase](#2-pre-exam-phase)
   - 2.1 Student Registration Portal
   - 2.2 Document Verification
   - 2.3 Admin Approval Workflow
   - 2.4 Exam Scheduling Module
   - 2.5 Automatic Seat Arrangement Mapping
   - 2.6 Hall Ticket Generation
   - 2.7 Notification System
3. [Exam Day Phase](#3-exam-day-phase)
   - 3.1 Fingerprint Entry System
   - 3.2 Invigilator Dashboard
   - 3.3 Fallback / Edge Case Handling
   - 3.4 Security Alerts & Malpractice Detection
   - 3.5 Admin Override System
4. [Post-Exam Phase](#4-post-exam-phase)
   - 4.1 Attendance Reports
   - 4.2 Analytics Dashboard
   - 4.3 Data Archival
5. [Infrastructure & Security](#5-infrastructure--security)
   - 5.1 Role-Based Access Control
   - 5.2 Biometric Data Encryption
   - 5.3 Offline Mode for Scanner Clients
6. [Seat Auto-Mapping Algorithm — Deep Dive](#6-seat-auto-mapping-algorithm--deep-dive)
7. [Suggested Tech Stack Additions](#7-suggested-tech-stack-additions)
8. [Module Dependency Map](#8-module-dependency-map)

---

## 1. System Overview

The system operates in three distinct phases: pre-exam (registration, scheduling, seat assignment), exam day (biometric entry, live monitoring), and post-exam (reporting, archival). The fingerprint matching pipeline already built serves as the core verification engine that exam-day entry depends on.

**Current state (done):**
- Fingerprint image processing pipeline
- Fingerprint template matching logic
- Biometric data storage layer
- AS608 scanner driver integration

**Remaining scope:** Everything described in this document.

---

## 2. Pre-Exam Phase

### 2.1 Student Registration Portal

A web-based self-service portal where students complete registration from home before the exam.

**Required fields:**
- Full name, date of birth, student/roll number
- Institutional email address (used as login identity)
- Mobile number (used for OTP fallback and SMS alerts)
- Government-issued ID upload (JPEG/PNG/PDF, max 5 MB)
- Passport-size photograph upload
- Fingerprint upload (captured via provided mobile scanning flow or uploaded image)
- Subject(s) enrolled for

**Functional requirements:**
- Email OTP verification on account creation
- Mobile OTP verification before final submission
- Real-time upload progress and format validation (file type, size, image resolution check)
- Registration status page showing: submitted / under review / approved / rejected
- Allow re-upload if admin rejects a biometric or document
- Session timeout after 15 minutes of inactivity

**Notes for engineers:**
- Fingerprint upload should run through the existing processing pipeline immediately on upload — flag poor-quality scans before admin review rather than on exam day
- Store the raw upload and the processed template separately
- Do not allow re-registration under the same roll number once approved

---

### 2.2 Document Verification

An internal step (admin-facing) that checks uploaded documents for validity before approving the registration.

**Checks to implement:**
- Image clarity threshold for uploaded ID (blur detection)
- Face match between uploaded photo and ID document photo (optional but recommended — can use a lightweight face similarity model)
- Duplicate detection: same fingerprint template submitted under two different student accounts
- Eligibility cross-check against institutional student records (CSV import or API hook to institution's database)

---

### 2.3 Admin Approval Workflow

After a student submits, an admin must review and approve before the student is assigned a seat.

**Admin actions:**
- Approve registration
- Reject with a reason (notifies student automatically)
- Request re-upload (specific document or biometric)
- Bulk approve (for clean submissions with no flags)

**Dashboard requirements:**
- Filterable queue: all / pending / approved / rejected / flagged
- Inline biometric quality score visible per student
- Timestamps on all actions for audit trail

---

### 2.4 Exam Scheduling Module

Allows admins to define exam sessions and link them to students, subjects, and venues.

**Data model (conceptual):**

```
Exam
  ├── Subject (name, code)
  ├── Date + Time slot
  ├── Duration (minutes)
  ├── Exam Center(s)
  │     └── Hall(s)
  │           └── Total seat capacity
  └── Enrolled students (linked by subject registration)
```

**Features:**
- Create / edit / cancel exam sessions
- Link multiple halls and centers to one exam
- Prevent scheduling conflicts (same student in two exams at the same time)
- Lock scheduling after a cutoff date (no edits once hall tickets are generated)

---

### 2.5 Automatic Seat Arrangement Mapping

**This is the module most critical to scale.** Given a confirmed student list and hall layout, the system must auto-assign every student to a specific seat with no manual intervention.

**Algorithm inputs:**
- Confirmed student list for a given exam
- Subject codes per student
- List of available halls with their seat grid dimensions (rows × columns)
- Constraint configuration (see below)

**Constraint rules:**

| Constraint | Description | Priority |
|---|---|---|
| No same-subject neighbours | Adjacent seats (left, right, front, back) must not share the same subject | High |
| Alternate seat spacing | Optional: leave every other seat vacant if capacity allows | Medium |
| Center capacity limits | Do not overflow a hall beyond its defined seat count | High |
| Special needs seating | Flag students requiring front-row or aisle seating | Medium |
| Gender grouping | Optional: group by gender within a hall (configurable per exam) | Low |

**Algorithm approach:**
1. Sort students by subject code
2. Apply a round-robin shuffle across subjects to interleave different-subject students
3. Map the interleaved list sequentially to the seat grid (row by row, or column by column — configurable)
4. Validate: run a constraint check pass, flag any adjacent same-subject pair
5. If violations exist, run a local swap pass to resolve
6. Repeat until no violations or a max iteration count is reached

**Outputs:**
- Seat assignment record per student (hall ID, row, column, seat label)
- Printable hall-wise seat map (PDF grid layout, one per hall)
- Door list per hall (alphabetical list of student names and seat numbers, for posting outside the room)
- Seat number populated into each student's hall ticket (see 2.6)

**Edge cases to handle:**
- More students than available seats → alert admin before generation
- A student registered for two subjects in back-to-back slots → ensure different seat in each slot (or same if venue allows)
- Late registrations after seat assignment → reserve a small buffer pool of unassigned seats per hall

---

### 2.6 Hall Ticket Generation

System-generated PDF issued to each approved student after seat assignment.

**Hall ticket must include:**
- Student name, roll number, photograph
- Subject name and code
- Exam date, time, duration
- Exam center name and address
- Assigned hall name/number and seat number
- QR code (encodes: student ID + exam ID + seat ID, signed with a server secret)
- Instructions for exam day (what to bring, biometric process reminder)

**Functional requirements:**
- Bulk generation triggered once seat mapping is finalised for an exam
- Individually downloadable by the student via the portal
- Regeneration allowed only by admin (e.g. if seat reassignment happens)
- QR code verified by invigilator dashboard on exam day as a secondary check

---

### 2.7 Notification System

Automated alerts sent at every major stage. All notifications should be logged (sent timestamp, delivery status).

| Trigger event | Channel | Recipient |
|---|---|---|
| Registration submitted | Email | Student |
| Registration approved | Email + SMS | Student |
| Registration rejected | Email | Student (with reason) |
| Re-upload requested | Email + SMS | Student |
| Hall ticket available | Email + SMS | Student |
| Exam reminder (48 hrs before) | SMS | Student |
| Exam reminder (24 hrs before) | SMS | Student |
| Entry confirmed on exam day | SMS | Student |
| Fallback auth used | Email | Admin + Student |

---

## 3. Exam Day Phase

### 3.1 Fingerprint Entry System

Extends the existing fingerprint pipeline into a real-time entry control system.

**Flow:**
1. Student places finger on AS608 scanner at the entry point of their assigned hall
2. Scanner captures and sends template to the server
3. Server matches against the stored template for that student
4. If match confidence exceeds threshold → grant entry, mark attendance, trigger SMS confirmation
5. If match fails → prompt retry (up to 2 retries) → escalate to fallback (see 3.3)

**Additional checks on match success:**
- Confirm the student is registered for today's exam
- Confirm the student is assigned to this specific hall (prevent wrong-hall entry)
- Confirm the student has not already scanned in (duplicate prevention)

**Entry states:**

| State | Meaning |
|---|---|
| `GRANTED` | Fingerprint matched, student allowed in |
| `WRONG_HALL` | Matched but assigned to a different hall |
| `ALREADY_ENTERED` | Duplicate scan detected |
| `MATCH_FAILED` | Fingerprint did not match after retries |
| `FALLBACK_GRANTED` | Entry via OTP or admin override |
| `DENIED` | Not registered or exam not active |

---

### 3.2 Invigilator Dashboard

A web UI accessible by invigilators from any device within the exam venue network.

**Features:**
- Live seat grid: each seat shown as vacant / present / absent
- Color coding: green (scanned in), grey (not yet arrived), red (absent after exam start time)
- Student detail on seat click: name, roll number, photo, entry timestamp
- Filter by status (show only absent, show only present)
- Hall summary: total seats, present count, absent count, fallback count
- QR code scanner view: invigilator can scan a student's hall ticket QR as a secondary check
- Exam timer displayed prominently
- Read-only — invigilators cannot modify data, only view

**Access control:**
- Each invigilator account is assigned to specific halls only
- Cannot see other halls' data

---

### 3.3 Fallback / Edge Case Handling

Fingerprints can fail due to cuts, dry skin, worn ridges, scanner dirt, or poor original enrolment quality. A fallback path is mandatory for a deployable system.

**Fallback chain (in order):**

1. **Retry** — prompt student to re-scan (max 2 additional attempts, clean scanner between attempts)
2. **OTP fallback** — system sends a 6-digit OTP to the student's registered mobile number; invigilator enters it into the dashboard to confirm identity
3. **Manual photo check** — invigilator compares the student's physical appearance with the photo on record (visible in dashboard), approves manually
4. **Admin override** — any entry granted outside the fingerprint match must require a reason code (see 3.5)

**All fallback events must be:**
- Logged with timestamp, reason code, and the identity of the invigilator who approved
- Flagged in attendance reports
- Notified to the student via SMS

---

### 3.4 Security Alerts & Malpractice Detection

Automatic alerts triggered by suspicious patterns, surfaced in the admin console in real time.

| Alert type | Trigger condition |
|---|---|
| Duplicate scan | Same fingerprint template matches twice in any hall |
| Wrong hall attempt | Student scans at a hall they are not assigned to |
| Impersonation attempt | Fingerprint does not match the claimed student's template but matches another student's |
| Excessive fallbacks | A single exam session has more than X% fallback auths (configurable threshold) |
| Unverified occupancy | Student found seated but no entry scan recorded |
| Scanner offline | AS608 device stops sending heartbeat pings |

All alerts are logged permanently and cannot be deleted.

---

### 3.5 Admin Override System

For genuine edge cases where no automated path succeeds.

**Requirements:**
- Only users with `ADMIN` or `EXAM_SUPERVISOR` role can grant overrides
- Override form requires: student ID, reason code (dropdown), free-text notes, supervisor password confirmation
- Override is logged with: supervisor identity, timestamp, reason, and which fallback steps were already attempted
- Override history is visible in the post-exam audit trail but not modifiable

---

## 4. Post-Exam Phase

### 4.1 Attendance Reports

**Report types:**

| Report | Granularity | Export format |
|---|---|---|
| Attendance by exam | Per student, per subject | CSV, PDF |
| Attendance by center | Per hall, per session | CSV, PDF |
| Absentee list | Students with no scan and no fallback | CSV |
| Fallback usage report | All non-fingerprint entries with reasons | CSV, PDF |
| Override report | All admin overrides with reasons | PDF (audit-signed) |

All reports should be filterable by date range, center, subject, and hall.

---

### 4.2 Analytics Dashboard

Aggregate views for management and operations teams.

**Metrics to surface:**
- Overall attendance rate per exam session
- Absentee rate trend across multiple exam sessions
- Fallback auth rate per center (high rate suggests scanner hardware issues)
- Average entry processing time (time from scan to `GRANTED`)
- Hall-wise occupancy utilisation (how full each hall was vs capacity)
- Peak entry time distribution (histogram of when students arrived within the entry window)

---

### 4.3 Data Archival

**Retention policy (configure per institution):**
- Raw fingerprint images: delete after biometric template is extracted and verified (do not store raw scans long-term)
- Processed fingerprint templates: retain for the duration the student is enrolled, then purge on request
- Exam attendance records: retain for minimum 5 years (or per institutional policy)
- Audit logs (overrides, fallbacks, alerts): retain permanently, immutable

**Archival features:**
- Per-exam data export (ZIP of all reports for that exam) for offline backup
- Soft delete on student records (mark inactive, do not purge biometric until confirmed)
- GDPR / data protection compliance: student can request data deletion after their exam period concludes

---

## 5. Infrastructure & Security

### 5.1 Role-Based Access Control

| Role | Access |
|---|---|
| `STUDENT` | Own registration, own hall ticket, own attendance status |
| `INVIGILATOR` | Assigned halls only — view-only dashboard, QR scanner |
| `CENTER_ADMIN` | All halls at their assigned center, attendance reports for that center |
| `EXAM_SUPERVISOR` | All centers, can grant overrides, view security alerts |
| `SUPER_ADMIN` | Full system access, user management, system configuration |

All role assignments are logged. Role changes require a second admin to confirm (four-eyes principle recommended).

---

### 5.2 Biometric Data Encryption

Fingerprint templates are legally classified as sensitive biometric data in most jurisdictions.

**Requirements:**
- Templates stored encrypted at rest (AES-256 minimum)
- Encryption keys managed separately from the database (use a KMS or environment-bound key store)
- Templates never logged in plaintext in application logs
- Templates never included in API responses to the client — matching happens server-side only
- Transmission of fingerprint data (scanner → server) over TLS 1.2+ only
- Access to the biometric store is restricted to the matching service only — no other module reads it directly

---

### 5.3 Offline Mode for Scanner Clients

Exam venues frequently have unreliable internet. The entry scanner must function even when the server is unreachable.

**Offline requirements:**
- Scanner client caches the approved student list and encrypted fingerprint templates for the day's exam locally before the exam window opens (pre-sync, e.g. 30 minutes before start)
- Matching runs locally against the cached templates during an outage
- Entry events are queued locally and synced to the server once connectivity resumes
- Invigilator dashboard shows a "OFFLINE MODE" banner and disables live features
- Offline cache expires after the exam window closes and is wiped from the device

---

## 6. Seat Auto-Mapping Algorithm — Deep Dive

This section provides enough detail for an engineer to implement the core algorithm.

**Pseudocode:**

```
function generateSeatMap(students, halls, constraints):
    
    # Step 1: Group students by subject
    groups = groupBy(students, subject_code)
    
    # Step 2: Interleave subject groups (round-robin)
    interleaved = roundRobinMerge(groups)
    
    # Step 3: Distribute across halls by capacity
    hallAssignments = distributeToHalls(interleaved, halls)
    
    # Step 4: Map to seat grid per hall
    for hall in hallAssignments:
        grid = buildGrid(hall.rows, hall.columns)
        assignment = mapStudentsToGrid(hallAssignments[hall], grid)
        
        # Step 5: Validate constraints
        violations = checkNeighbourConstraints(assignment, constraints)
        
        # Step 6: Swap pass to resolve violations
        iterations = 0
        while violations > 0 and iterations < MAX_ITERATIONS:
            assignment = resolveViolations(assignment, violations)
            violations = checkNeighbourConstraints(assignment, constraints)
            iterations++
        
        if violations > 0:
            flag("Could not fully resolve constraints — manual review needed")
        
        seatMap[hall] = assignment
    
    return seatMap
```

**Data structures:**

```
Student:
  id, name, roll_number, subject_code, special_needs (bool)

Hall:
  id, name, center_id, rows (int), columns (int), seat_labels[]

SeatAssignment:
  student_id, hall_id, row (int), col (int), seat_label (str)
```

**Neighbour definition:**
Adjacent means: left, right, directly in front, directly behind (4-directional, not diagonal).

**Special needs students:**
Process these first. Assign them to front rows or aisle seats before running the general algorithm on remaining students.

**Buffer seat pool:**
Reserve the last row of each hall as a buffer for late registrations. Do not include buffer seats in the main mapping pass.

---

## 7. Suggested Tech Stack Additions

These are additions to whatever stack is already in use. Adopt as fits your existing choices.

| Need | Recommendation | Reason |
|---|---|---|
| Async PDF generation | Celery (Python) / BullMQ (Node) | Hall ticket PDFs at scale should not block the request thread |
| Live dashboard updates | WebSockets (Socket.io / Django Channels) | Invigilator dashboard needs real-time seat state |
| PDF generation | WeasyPrint (Python) / Puppeteer (Node) | For hall tickets and reports |
| QR code generation | `qrcode` (Python) / `qrcode` (npm) | Signed QR on hall tickets |
| QR code verification | `pyzbar` / `jsQR` | Scanner in invigilator dashboard |
| SMS gateway | Twilio / AWS SNS / local provider | Notification system |
| Email | AWS SES / SendGrid | Reliable delivery at volume |
| Encryption key management | AWS KMS / HashiCorp Vault | Biometric template key storage |
| Offline sync | SQLite on scanner client + sync queue | Offline mode for exam day |

---

## 8. Module Dependency Map

```
Student Registration Portal
    └── Document Verification
            └── Admin Approval Workflow
                    ├── Exam Scheduling Module
                    │       └── Seat Auto-Mapping Algorithm
                    │               └── Hall Ticket Generation
                    │                       └── Notification System
                    └── Fingerprint Pipeline (existing)
                            └── Fingerprint Entry System (exam day)
                                    ├── Invigilator Dashboard
                                    ├── Fallback Handling
                                    ├── Security Alerts
                                    └── Admin Override System
                                            └── Attendance Reports
                                                    ├── Analytics Dashboard
                                                    └── Data Archival
```

**Build order recommendation:**
1. Admin Approval Workflow + Exam Scheduling (unblocks everything else)
2. Seat Auto-Mapping Algorithm (highest complexity, needs early testing)
3. Hall Ticket Generation + Notification System
4. Fingerprint Entry System (exam day, builds on existing pipeline)
5. Invigilator Dashboard + Fallback Handling
6. Security Alerts + Override System
7. Reports + Analytics
8. Offline Mode (can be a later iteration once core is stable)

---

*Document version 1.0 — prepared for engineering handoff*

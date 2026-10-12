# Five-minute demonstration script

Setup beforehand: demo dataset loaded (shown by default). Locally pick personas on the login page; on AWS sign in
with the persona accounts from `infra/setup_accounts.py --demo-personas`.

| Time | Persona | Show | Say |
|---|---|---|---|
| 0:00 | — | Login page | “Accounts are created by the college; there's no public sign-up. Each role sees only what it's responsible for.” |
| 0:20 | College Admin (`admin.priya`) | **Overview**: average Success Score, high academic and placement risk, needs review, open/overdue interventions, insufficient data. Filter Department = CSE, Year = 3. | “Everything is rules-based and explainable. Students without enough data are counted separately — never as zero.” |
| 1:00 | | **Students** → open a student with high academic risk (e.g. CSE24001) → **Score & trends** | “Each component, its weight, re-normalised weight and contribution; coverage, profile, scoring version and calculation time. Trends only compare compatible periods.” |
| 1:40 | | **Risks & actions** | “Academic and placement risk are separate. Each flag shows the rule, observed value, threshold, period and suggested action. Thresholds are labelled as assumptions.” |
| 2:10 | Mentor (`mentor.arjun`) | **Enter data** → *LMS summary* → period 2026-09 → change one mentee's values → Save | “Mentors only see their classes and mentees. Saved marks and attendance can only change through an HOD-approved correction.” |
| 2:40 | | Open that student → score updated → **Risks & actions** → *Review and assign* → tick the review box → Assign | “Nothing is assigned automatically — staff confirm they reviewed the evidence.” |
| 3:10 | | **Interventions** tab → Update → Completed, outcome *Improved* → Save; add a confidential note | “Before/after is shown as an association, not proof. Confidential notes are limited to mentors, HODs and the admin; students never see notes.” |
| 3:40 | Placement Officer (`placement.rohit`) | **Placement readiness** | “Years 3–4 only. No assessments means ‘insufficient data — collect assessments’, not poor readiness. The placement officer can't see marks or confidential notes.” |
| 4:05 | HOD (`hod.meenakshi`) or Activity Coordinator (`activity.sara`) | **Approvals & verification** | “Second-person approval for corrections; student certifications count only after verification.” |
| 4:25 | Student (`student.cse`) | Own **My progress** | “Students see their own score and risks, nothing about anyone else, and no staff notes.” |
| 4:45 | System Administrator (`sysadmin.dev`) | **Role matrix**, **Users and roles** | “The canonical role matrix drives every API check. The system administrator manages accounts but can't see student data or change their own roles.” |
| 5:00 | | — | “Runs on CloudFront, two Lambda functions, DynamoDB and Cognito, sized to stay inside AWS free allowances — with a preflight that stops the deployment if it can't.” |

Fallbacks: if a step fails, use **Refresh**; every screen has loading, empty and error states. To restore
the demo afterwards: *Configuration → Reset demo dataset* (type `RESET DEMO`).
